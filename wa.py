"""WhatsApp Cloud API: Graph calls and message builders. Env is read per call so tests need none."""
import os
from pathlib import Path

import httpx


def _url(path):
    return f"https://graph.facebook.com/{os.environ['GRAPH_VERSION']}/{path}"


def _auth():
    return {"Authorization": f"Bearer {os.environ['WA_TOKEN']}"}


def graph_post(path, json=None, data=None, files=None):
    response = httpx.post(_url(path), headers=_auth(), json=json, data=data, files=files, timeout=15)
    response.raise_for_status()
    return response.json()


def send(to, message):
    return graph_post(
        f"{os.environ['WA_PHONE_NUMBER_ID']}/messages",
        json={"messaging_product": "whatsapp", "recipient_type": "individual", "to": to, **message},
    )


def mark_read(message_id):
    """Blue ticks plus a typing indicator (shown up to 25 s or until we reply)."""
    graph_post(
        f"{os.environ['WA_PHONE_NUMBER_ID']}/messages",
        json={"messaging_product": "whatsapp", "status": "read", "message_id": message_id,
              "typing_indicator": {"type": "text"}},
    )


def download_media(media_id):
    """Media URL from the webhook's id is valid ~5 minutes, so call this immediately."""
    meta = httpx.get(_url(media_id), headers=_auth(), timeout=15)
    meta.raise_for_status()
    media = httpx.get(meta.json()["url"], headers=_auth(), timeout=30)
    media.raise_for_status()
    return media.content


def upload_media(path, mime):
    with open(path, "rb") as f:
        return graph_post(
            f"{os.environ['WA_PHONE_NUMBER_ID']}/media",
            data={"messaging_product": "whatsapp", "type": mime},
            files={"file": (Path(path).name, f, mime)},
        )["id"]


def text(body):
    return {"type": "text", "text": {"body": body}}


def buttons(body, choices):
    return {"type": "interactive", "interactive": {
        "type": "button",
        "body": {"text": body},
        "action": {"buttons": [{"type": "reply", "reply": {"id": i, "title": t}} for i, t in choices]},
    }}


def list_message(body, button, rows):
    return {"type": "interactive", "interactive": {
        "type": "list",
        "body": {"text": body},
        "action": {"button": button, "sections": [{"title": button, "rows": [{"id": i, "title": t} for i, t in rows]}]},
    }}


def voice_note(media_id):
    """OGG/Opus with voice=true renders as a voice message (play icon only if <= 512 KB)."""
    return {"type": "audio", "audio": {"id": media_id, "voice": True}}
