"""
WhatsApp link for "Book Dev" through Twilio's WhatsApp API.

Incoming: bookdev_webhook.py receives Twilio's webhook and appends each message
from the owner's number to bookdev/inbox.jsonl.
Outgoing: send() posts a message to the owner through Twilio's REST API.

Settings (.env): TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN,
TWILIO_WHATSAPP_FROM (e.g. whatsapp:+14155238886), BOOKDEV_OWNER (whatsapp:+<number>).
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

# WhatsApp messages through Twilio are capped at 1,600 characters.
_CHUNK = 1500


def config() -> dict:
    load_dotenv(os.path.join(ROOT, ".env"), override=True)
    cfg = {
        "sid": os.getenv("TWILIO_ACCOUNT_SID", "").strip(),
        "token": os.getenv("TWILIO_AUTH_TOKEN", "").strip(),
        "from": os.getenv("TWILIO_WHATSAPP_FROM", "").strip(),
        "owner": os.getenv("BOOKDEV_OWNER", "").strip(),
    }
    missing = [k for k, v in (("TWILIO_ACCOUNT_SID", cfg["sid"]), ("TWILIO_AUTH_TOKEN", cfg["token"]),
                              ("TWILIO_WHATSAPP_FROM", cfg["from"]), ("BOOKDEV_OWNER", cfg["owner"])) if not v]
    cfg["missing"] = missing
    return cfg


def _append(path: str, entry: dict):
    os.makedirs(DIR, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _chunks(text: str) -> list[str]:
    text = text.strip()
    parts = []
    while len(text) > _CHUNK:
        cut = text.rfind("\n", 0, _CHUNK)
        if cut < _CHUNK // 2:
            cut = text.rfind(" ", 0, _CHUNK)
        if cut <= 0:
            cut = _CHUNK
        parts.append(text[:cut].rstrip())
        text = text[cut:].lstrip()
    if text:
        parts.append(text)
    if len(parts) > 1:
        parts = [f"({i}/{len(parts)}) {p}" for i, p in enumerate(parts, 1)]
    return parts


def send(text: str) -> dict:
    """Send *text* to the owner on WhatsApp (split into several messages if long)."""
    cfg = config()
    if cfg["missing"]:
        return {"ok": False, "message": f"Missing in .env: {', '.join(cfg['missing'])}"}
    url = f"https://api.twilio.com/2010-04-01/Accounts/{cfg['sid']}/Messages.json"
    sent, errors = [], []
    for part in _chunks(text):
        r = requests.post(url, auth=(cfg["sid"], cfg["token"]), timeout=30,
                          data={"From": cfg["from"], "To": cfg["owner"], "Body": part})
        if r.status_code >= 300:
            try:
                err = r.json().get("message", r.text)
            except ValueError:
                err = r.text
            errors.append(f"HTTP {r.status_code}: {err[:200]}")
            break
        sent.append(r.json().get("sid"))
    return {"ok": not errors, "messages_sent": len(sent), "errors": errors}


def _read_state() -> dict:
    try:
        with open(STATE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"read": 0}


def inbox(mark_read: bool = True) -> list[dict]:
    """Messages from the owner not yet read (oldest first)."""
    if not os.path.exists(INBOX):
        return []
    with open(INBOX, encoding="utf-8") as f:
        lines = [json.loads(ln) for ln in f if ln.strip()]
    state = _read_state()
    new = lines[state.get("read", 0):]
    if mark_read and new:
        state["read"] = len(lines)
        with open(STATE, "w", encoding="utf-8") as f:
            json.dump(state, f)
    return new
