"""
"Book Dev": message the book workflow from your phone.

Incoming messages from either listener (bookdev_discord.py, or the Twilio
WhatsApp webhook bookdev_webhook.py) are appended to bookdev/inbox.jsonl.
send() replies on the channel set by BOOKDEV_CHANNEL in .env ("discord",
the default, or "whatsapp").
"""

import json
import os
import time

import requests
from dotenv import load_dotenv

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIR = os.path.join(ROOT, "bookdev")
INBOX = os.path.join(DIR, "inbox.jsonl")
OUTBOX = os.path.join(DIR, "outbox.jsonl")
STATE = os.path.join(DIR, "state.json")
DISCORD_STATE = os.path.join(DIR, "discord_state.json")

_DISCORD_CHUNK = 1900  # Discord caps messages at 2,000 characters


def read_json(path: str, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def write_json(path: str, data):
    os.makedirs(DIR, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)


def append(path: str, entry: dict):
    os.makedirs(DIR, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def chunks(text: str, size: int) -> list[str]:
    text = text.strip()
    parts = []
    while len(text) > size:
        cut = text.rfind("\n", 0, size)
        if cut < size // 2:
            cut = text.rfind(" ", 0, size)
        if cut <= 0:
            cut = size
        parts.append(text[:cut].rstrip())
        text = text[cut:].lstrip()
    if text:
        parts.append(text)
    if len(parts) > 1:
        parts = [f"({i}/{len(parts)}) {p}" for i, p in enumerate(parts, 1)]
    return parts


def channel() -> str:
    load_dotenv(os.path.join(ROOT, ".env"), override=True)
    return (os.getenv("BOOKDEV_CHANNEL") or "discord").strip().lower()


def _send_discord(text: str) -> dict:
    load_dotenv(os.path.join(ROOT, ".env"), override=True)
    token = os.getenv("DISCORD_TOKEN", "").strip()
    ch = read_json(DISCORD_STATE, {}).get("channel_id")
    if not token:
        return {"ok": False, "errors": ["DISCORD_TOKEN missing in .env"]}
    if not ch:
        return {"ok": False, "errors": ["No Discord channel yet: message Book Dev once first."]}
    sent, errors = 0, []
    for part in chunks(text, _DISCORD_CHUNK):
        r = requests.post(f"https://discord.com/api/v10/channels/{ch}/messages", timeout=30,
                          headers={"Authorization": f"Bot {token}"}, json={"content": part})
        if r.status_code >= 300:
            errors.append(f"HTTP {r.status_code}: {r.text[:200]}")
            break
        sent += 1
    return {"ok": not errors, "messages_sent": sent, "errors": errors}


def send(text: str) -> dict:
    """Reply to the owner on the configured channel."""
    via = channel()
    if via == "whatsapp":
        from tools.whatsapp_tool import send as wa_send
        res = wa_send(text)
    else:
        res = _send_discord(text)
    append(OUTBOX, {"time": time.strftime("%Y-%m-%d %H:%M:%S"), "via": via, "text": text,
                    "ok": res.get("ok"), "errors": res.get("errors", [])})
    return {"via": via, **res}


FIXLOG = os.path.join(DIR, "fixlog.jsonl")


def note_fixes(where: str, fixes: list[str]):
    """Record automatic fixes; report_fixes() later sends them in one message."""
    if fixes:
        append(FIXLOG, {"time": time.strftime("%Y-%m-%d %H:%M:%S"), "where": where, "fixes": fixes})


def report_fixes(title: str) -> dict:
    """Send every fix recorded since the last report as one AUTO-FIX message."""
    if not os.path.exists(FIXLOG):
        return {"ok": True, "sent": False, "fixes": 0}
    with open(FIXLOG, encoding="utf-8") as f:
        entries = [json.loads(ln) for ln in f if ln.strip()]
    state = read_json(STATE, {"read": 0})
    new = entries[state.get("fixes_reported", 0):]
    lines = [f"• {e['where']}: {fx}" for e in new for fx in e["fixes"]]
    if not lines:
        return {"ok": True, "sent": False, "fixes": 0}
    if len(lines) > 25:
        lines = lines[:25] + [f"• … and {len(lines) - 25} more (bookdev/fixlog.jsonl)"]
    res = send(f"🛠️ AUTO-FIX REPORT: {title.upper()}\n" + "\n".join(lines))
    if res.get("ok"):
        state["fixes_reported"] = len(entries)
        write_json(STATE, state)
    return {"sent": res.get("ok"), "fixes": len(lines), **res}


def alert(title: str, lines: list[str]) -> dict:
    """Serious problem: ping the owner right away."""
    ping = ""
    if channel() == "discord":
        owner = read_json(DISCORD_STATE, {}).get("owner_id")
        ping = f"<@{owner}> " if owner else ""
    body = "\n".join(f"• {ln}" for ln in lines)
    return send(f"🚨 {ping}SERIOUS: {title.upper()}\n{body}")


def inbox(mark_read: bool = True) -> list[dict]:
    """Messages from the owner not yet read (oldest first)."""
    if not os.path.exists(INBOX):
        return []
    with open(INBOX, encoding="utf-8") as f:
        lines = [json.loads(ln) for ln in f if ln.strip()]
    state = read_json(STATE, {"read": 0})
    new = lines[state.get("read", 0):]
    if mark_read and new:
        state["read"] = len(lines)
        write_json(STATE, state)
    return new
