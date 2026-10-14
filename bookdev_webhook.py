"""
"Book Dev" WhatsApp webhook: receives Twilio's incoming-message webhook and
stores messages from the owner's number in bookdev/inbox.jsonl, where the
Claude Code session running the book picks them up and replies through the
book-agent MCP tool whatsapp_send.

Run: python bookdev_webhook.py   (listens on http://127.0.0.1:8787/whatsapp)
Expose it with bookdev_start.ps1 (cloudflared tunnel) and set the printed URL as
"When a message comes in" in the Twilio WhatsApp sandbox settings.
"""

import base64
import hashlib
import hmac
import time
from xml.sax.saxutils import escape

from flask import Flask, Response, request

from tools.bookdev import INBOX
from tools.bookdev import append as _append
from tools.whatsapp_tool import config

PORT = 8787
ACK = "Book Dev got it. Working on it."

app = Flask(__name__)


def _signature_ok(token: str) -> bool:
    """Twilio signs each request: base64(HMAC-SHA1(auth token, URL + sorted POST params))."""
    sig = request.headers.get("X-Twilio-Signature", "")
    params = "".join(k + v for k, v in sorted(request.form.items()))
    hosts = {request.headers.get("X-Forwarded-Host"), request.headers.get("Host")}
    for host in filter(None, hosts):
        url = f"https://{host}{request.full_path.rstrip('?')}"
        digest = hmac.new(token.encode(), (url + params).encode(), hashlib.sha1).digest()
        if hmac.compare_digest(base64.b64encode(digest).decode(), sig):
            return True
    return False


def _twiml(text: str = "") -> Response:
    body = f"<Message>{escape(text)}</Message>" if text else ""
    return Response(f'<?xml version="1.0" encoding="UTF-8"?><Response>{body}</Response>',
                    mimetype="text/xml")


@app.post("/whatsapp")
def whatsapp():
    cfg = config()
    if cfg["token"] and not _signature_ok(cfg["token"]):
        return Response("bad signature", status=403)
    sender = request.form.get("From", "")
    if sender != cfg["owner"]:
        return _twiml()  # ignore anyone but the owner
    _append(INBOX, {"time": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "from": sender,
                    "text": request.form.get("Body", ""),
                    "media": int(request.form.get("NumMedia", "0") or 0)})
    return _twiml(ACK)


@app.get("/health")
def health():
    return "Book Dev webhook is running."


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=PORT)
