"""WhatsApp webhook: verify, authenticate, dedupe, ack fast, handle in the background."""
import hashlib
import hmac
import json
import os
import time
from collections import OrderedDict
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, Query, Request, Response
from fastapi.responses import PlainTextResponse

import brain
import wa

ROOT = Path(__file__).parent
DATA_DIR = ROOT / "data"
TEST_VOICE = ROOT / "assets" / "test_voice.ogg"
SEEN_MAX = 10_000
UNSUPPORTED_TYPES = {"image", "video", "document", "sticker", "location", "contacts"}

content = brain.Content(os.environ.get("CONTENT_PATH", ROOT / "content" / "hpv_placeholder.yaml"))
seen_ids = OrderedDict()  # Meta retries undelivered webhooks; message ids make handling idempotent
user_lang = {}  # TODO: key on BSUID once Meta sends it; phone may be omitted for username users
voice_media_id = None  # uploaded once; Meta keeps uploads 30 days

app = FastAPI()


def log_event(kind, **fields):
    DATA_DIR.mkdir(exist_ok=True)
    with open(DATA_DIR / "turns.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": round(time.time(), 3), "kind": kind, **fields}, ensure_ascii=False) + "\n")


def unit_message(unit, lang):
    body = unit["text"][lang]
    related = [content.units[r] for r in unit["related_units"]]
    if not related:
        return wa.text(body)
    return wa.buttons(body, [(r["id"], r["title"][lang]) for r in related])


def menu_message(body, units, lang):
    return wa.list_message(body, content.messages["topics_button"][lang], [(u["id"], u["title"][lang]) for u in units])


@app.get("/webhook")
def verify(
    mode: str = Query("", alias="hub.mode"),
    token: str = Query("", alias="hub.verify_token"),
    challenge: str = Query("", alias="hub.challenge"),
):
    if mode == "subscribe" and hmac.compare_digest(token.encode(), os.environ["WA_VERIFY_TOKEN"].encode()):
        return PlainTextResponse(challenge)
    return Response(status_code=403)


@app.post("/webhook")
async def receive(request: Request, background_tasks: BackgroundTasks):
    raw = await request.body()
    expected = "sha256=" + hmac.new(os.environ["WA_APP_SECRET"].encode(), raw, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected.encode(), request.headers.get("x-hub-signature-256", "").encode()):
        return Response(status_code=403)
    try:
        payload = json.loads(raw)
    except ValueError:
        log_event("malformed", size=len(raw))
        return Response(status_code=200)  # a retry would be just as malformed

    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            for status in value.get("statuses", []):
                log_event("status", message_id=status.get("id"), status=status.get("status"))
            for msg in value.get("messages", []):
                if msg["id"] in seen_ids:
                    continue
                seen_ids[msg["id"]] = None
                if len(seen_ids) > SEEN_MAX:
                    seen_ids.popitem(last=False)
                background_tasks.add_task(handle, msg)
    return Response(status_code=200)


def handle(msg):
    global voice_media_id
    started = time.monotonic()
    user, kind = msg["from"], msg["type"]
    lang = user_lang.get(user, "en")
    turn = {"message_id": msg["id"], "user": hashlib.sha256(user.encode()).hexdigest()[:12], "type": kind}

    if kind == "text":
        wa.mark_read(msg["id"])
        text = msg["text"]["body"]
        lang = user_lang[user] = brain.detect_lang(text) or lang
        action, unit, ranked = content.decide(text)
        if action == "escalate":
            log_event("escalation", message_id=msg["id"], text=text)
            wa.send(user, wa.text(unit["text"][lang]))
        elif action == "answer":
            wa.send(user, unit_message(unit, lang))
        elif action == "clarify":
            candidates = [u for u, _ in ranked if not u["id"].startswith("sys.")][:3]
            wa.send(user, menu_message(content.messages["clarify"][lang], candidates, lang))
        else:  # greeting or deflect
            wa.send(user, menu_message(unit["text"][lang], content.topics, lang))
        turn.update(text=text, lang=lang, action=action, unit=unit and unit["id"],
                    top=[(u["id"], round(s, 3)) for u, s in ranked[:3]])

    elif kind == "interactive":
        reply = msg["interactive"]
        unit = content.units.get(reply.get(reply["type"], {}).get("id"))
        if unit:
            wa.send(user, unit_message(unit, lang))
        turn.update(lang=lang, action="tap", unit=unit and unit["id"])

    elif kind == "audio":
        wa.mark_read(msg["id"])
        media_id = msg["audio"]["id"]
        audio = wa.download_media(media_id)
        (DATA_DIR / "inbound").mkdir(parents=True, exist_ok=True)
        (DATA_DIR / "inbound" / f"{media_id}.ogg").write_bytes(audio)
        # Spike 4: text then voice note back-to-back to the same user.
        wa.send(user, wa.text(content.messages["voice_received"][lang]))
        if voice_media_id is None:
            voice_media_id = wa.upload_media(TEST_VOICE, "audio/ogg")
        wa.send(user, wa.voice_note(voice_media_id))
        turn.update(lang=lang, action="voice_placeholder", bytes=len(audio),
                    download_lag_s=round(time.time() - int(msg["timestamp"]), 1))

    elif kind in UNSUPPORTED_TYPES:
        wa.send(user, menu_message(content.messages["unsupported"][lang], content.topics, lang))
        turn.update(lang=lang, action="unsupported")

    else:
        turn.update(action="ignored")

    turn["latency_ms"] = round((time.monotonic() - started) * 1000)
    log_event("turn", **turn)
