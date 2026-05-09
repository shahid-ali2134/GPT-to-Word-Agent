"""
Thread-safe bridge that lets a sync agent thread (running in a ThreadPoolExecutor)
send a Discord message and block until the user replies in that channel.

Flow
----
1. Before running the agent, the Discord command handler calls
   ``make_input_fn(channel_id, send_fn, loop)`` to get a sync callable.
2. The callable is passed to ``agent_core.configure_figure_input_fn(fn)``.
3. When the agent needs manual input it calls ``fn(message_text)`` which:
      a. Registers a Queue for this channel.
      b. Dispatches the Discord message (fire-and-forget into the event loop).
      c. Blocks on Queue.get() until the user replies or the timeout expires.
4. The bot's ``on_message`` event calls ``deliver(channel_id, content)``
   which puts the reply text into the waiting Queue.
5. The command handler must call ``agent_core.configure_figure_input_fn(None)``
   after the executor completes (the finally block) to clean up.
"""

import asyncio
import threading
from queue import Empty, Queue
from typing import Callable, Coroutine

_lock = threading.Lock()
_waiters: dict[int, "Queue[str]"] = {}  # channel_id → reply queue


def deliver(channel_id: int, content: str) -> bool:
    """Route an incoming Discord message to a waiting agent thread.

    Returns True if the message was consumed (agent was waiting), False otherwise.
    """
    with _lock:
        q = _waiters.get(channel_id)
    if q is not None:
        q.put(content)
        return True
    return False


def _register(channel_id: int) -> "Queue[str]":
    q: "Queue[str]" = Queue()
    with _lock:
        _waiters[channel_id] = q
    return q


def _unregister(channel_id: int) -> None:
    with _lock:
        _waiters.pop(channel_id, None)


def make_input_fn(
    channel_id: int,
    send_fn: Callable[[str], Coroutine],
    loop: asyncio.AbstractEventLoop,
    timeout_sec: float = 300.0,
) -> Callable[[str], "str | None"]:
    """Return a sync callable suitable for ``agent_core.configure_figure_input_fn``.

    Parameters
    ----------
    channel_id:  Discord channel ID to listen on.
    send_fn:     Async coroutine callable ``(text: str) -> None`` that sends a
                 Discord message to the channel.
    loop:        The running asyncio event loop (from ``asyncio.get_running_loop()``).
    timeout_sec: How long to wait for the user's reply before returning None.
    """
    def input_fn(text: str) -> "str | None":
        # Register BEFORE sending so we never miss a fast reply
        q = _register(channel_id)
        try:
            asyncio.run_coroutine_threadsafe(send_fn(text), loop)
            return q.get(timeout=timeout_sec)
        except Empty:
            return None
        finally:
            _unregister(channel_id)

    return input_fn
