"""
"Book Dev" on Discord: a lightweight listener for the existing bot.

Messages to the bot (a DM, a mention, or any message in a channel named
"book-dev" / "bookdev") are appended to bookdev/inbox.jsonl, where the Claude Code
session running the book picks them up and replies through the book-agent MCP
tool bookdev_send. The first person who messages Book Dev becomes its owner;
messages from anyone else are ignored.

Do not run this together with discord_bot.py (same bot token).
The book-agent MCP server starts this automatically with every Claude Code
session in this folder (tools/bookdev.start_listener_watchdog) and passes
--parent <its PID>; the listener exits when that process is gone.
Manual run: python bookdev_discord.py
"""

import argparse
import asyncio
import json
import os
import time

import discord
from dotenv import load_dotenv

from tools.bookdev import DISCORD_STATE, INBOX, append, read_json, write_json

ROOT = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(ROOT, ".env"))
CHANNEL_NAMES = {"book-dev", "bookdev"}

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)


_parent_pid = None


async def _exit_with_parent():
    import psutil
    while psutil.pid_exists(_parent_pid):
        await asyncio.sleep(10)
    print(f"Parent process {_parent_pid} ended; Book Dev going offline.", flush=True)
    await client.close()


@client.event
async def on_ready():
    print(f"Book Dev listening as {client.user} (id {client.user.id})", flush=True)
    if _parent_pid and not getattr(client, "_parent_watch", None):
        client._parent_watch = asyncio.create_task(_exit_with_parent())


@client.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return
    is_dm = isinstance(message.channel, discord.DMChannel)
    named = getattr(message.channel, "name", "") in CHANNEL_NAMES
    mentioned = client.user in message.mentions
    if not (is_dm or named or mentioned):
        return

    state = read_json(DISCORD_STATE, {})
    owner = state.get("owner_id")
    if owner and owner != message.author.id:
        return
    text = message.content.replace(f"<@{client.user.id}>", "").strip()
    state.update({"owner_id": message.author.id, "owner_name": str(message.author),
                  "channel_id": message.channel.id})
    write_json(DISCORD_STATE, state)
    append(INBOX, {"time": time.strftime("%Y-%m-%d %H:%M:%S"), "via": "discord",
                   "from": str(message.author), "channel_id": message.channel.id,
                   "text": text, "attachments": [a.url for a in message.attachments]})
    try:
        await message.add_reaction("👀")
    except discord.HTTPException:
        pass


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--parent", type=int, help="exit when this process ends")
    _parent_pid = ap.parse_args().parent
    client.run(os.environ["DISCORD_TOKEN"])
