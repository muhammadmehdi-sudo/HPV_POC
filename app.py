"""WhatsApp webhook: verify, authenticate, dedupe, ack fast, handle in the background."""
import hashlib
import hmac
import json
import os
import time
from collections import OrderedDict
from pathlib import Path

import httpx
from fastapi import BackgroundTasks, FastAPI, Query, Request, Response
from fastapi.responses import PlainTextResponse

import brain
import speech
import wa

ROOT = Path(__file__).parent
DATA_DIR = ROOT / "data"
AUDIO_DIR = ROOT / "assets" / "audio"
SEEN_MAX = 10_000
STT_CONFIRM_BELOW = 0.80  # mean word confidence; placeholder until evaluate.py runs on real voice notes
CONFIRM_PREFIX, MENU_ID = "confirm:", "menu"  # reply-button ids on the confirm-back message
UNSUPPORTED_TYPES = {"image", "video", "document", "sticker", "location", "contacts"}

content = brain.Content(os.environ.get("CONTENT_PATH", ROOT / "content" / "hpv_placeholder.yaml"))
seen_ids = OrderedDict()  # Meta retries undelivered webhooks; message ids make handling idempotent
user_lang = {}  # TODO: key on BSUID once Meta sends it; phone may be omitted for username users
media_ids = {}  # audio filename -> uploaded media id; Meta keeps uploads 30 days

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


def answer(user, text, msg_id):
    """Reply to a typed or transcribed question; returns (turn fields, unit sent or None)."""
    lang = user_lang[user] = brain.detect_lang(text) or user_lang.get(user, "en")
    action, unit, ranked = content.decide(text)
    if action == "escalate":
        log_event("escalation", message_id=msg_id, text=text)
        wa.send(user, wa.text(unit["text"][lang]))
    elif action == "answer":
        wa.send(user, unit_message(unit, lang))
    elif action == "clarify":
        candidates = [u for u, _ in ranked if not u["id"].startswith("sys.")][:3]
        wa.send(user, menu_message(content.messages["clarify"][lang], candidates, lang))
    else:  # greeting or deflect
        wa.send(user, menu_message(unit["text"][lang], content.topics, lang))
    return dict(text=text, lang=lang, action=action, unit=unit and unit["id"],
                top=[(u["id"], round(s, 3)) for u, s in ranked[:3]]), unit


def send_voice_note(user, unit, lang):
    """Answer audio after the text (Spike 4); Roman Urdu users hear the Urdu-script audio. Returns the file sent."""
    audio_file = AUDIO_DIR / f"{unit['id']}.{'en' if lang == 'en' else 'ur'}.ogg"
    if not audio_file.exists():
        return None
    if audio_file.name not in media_ids:
        media_ids[audio_file.name] = wa.upload_media(audio_file, "audio/ogg")
    wa.send(user, wa.voice_note(media_ids[audio_file.name]))
    return audio_file.name


def handle(msg):
    started = time.monotonic()
    user, kind = msg["from"], msg["type"]
    lang = user_lang.get(user, "en")
    turn = {"message_id": msg["id"], "user": hashlib.sha256(user.encode()).hexdigest()[:12], "type": kind}

    if kind == "text":
        wa.mark_read(msg["id"])
        turn.update(answer(user, msg["text"]["body"], msg["id"])[0])

    elif kind == "interactive":
        reply = msg["interactive"]
        reply_id = reply.get(reply["type"], {}).get("id", "")
        confirmed = reply_id.startswith(CONFIRM_PREFIX)
        unit = content.units.get(reply_id.removeprefix(CONFIRM_PREFIX))
        if unit:
            wa.send(user, unit_message(unit, lang))
            if confirmed:  # the question came as a voice note, so the answer does too
                turn["audio"] = send_voice_note(user, unit, lang)
        elif reply_id == MENU_ID:
            wa.send(user, menu_message(content.messages["clarify"][lang], content.topics, lang))
        turn.update(lang=lang, action="confirmed" if confirmed else "tap", unit=unit and unit["id"])

    elif kind == "audio":
        wa.mark_read(msg["id"])
        media_id = msg["audio"]["id"]
        audio = wa.download_media(media_id)
        (DATA_DIR / "inbound").mkdir(parents=True, exist_ok=True)
        (DATA_DIR / "inbound" / f"{media_id}.ogg").write_bytes(audio)
        turn.update(bytes=len(audio), download_lag_s=round(time.time() - int(msg["timestamp"]), 1))
        stt_started = time.monotonic()
        try:
            transcript, stt_conf = speech.transcribe(audio)
        except httpx.HTTPError as error:
            log_event("stt_error", message_id=msg["id"], error=str(error))
            transcript, stt_conf = "", 0.0
        turn.update(stt_ms=round((time.monotonic() - stt_started) * 1000), stt_conf=round(stt_conf, 3))
        action, unit, ranked = content.decide(transcript)
        if not brain.detect_lang(transcript):
            wa.send(user, menu_message(content.messages["voice_unclear"][lang], content.topics, lang))
            turn.update(transcript=transcript, lang=lang, action="voice_unclear")
        elif action == "answer" and stt_conf < STT_CONFIRM_BELOW:  # escalations are never held back
            lang = user_lang[user] = brain.detect_lang(transcript)
            body = f"{content.messages['confirm'][lang]} {unit['title'][lang]}"
            wa.send(user, wa.buttons(body, [(CONFIRM_PREFIX + unit["id"], content.messages["confirm_yes"][lang]),
                                            (MENU_ID, content.messages["topics_button"][lang])]))
            turn.update(text=transcript, lang=lang, action="confirm", unit=unit["id"],
                        top=[(u["id"], round(s, 3)) for u, s in ranked[:3]])
        else:
            fields, unit = answer(user, transcript, msg["id"])
            turn.update(fields)
            if unit:
                turn["audio"] = send_voice_note(user, unit, fields["lang"])

    elif kind in UNSUPPORTED_TYPES:
        wa.send(user, menu_message(content.messages["unsupported"][lang], content.topics, lang))
        turn.update(lang=lang, action="unsupported")

    else:
        turn.update(action="ignored")

    turn["latency_ms"] = round((time.monotonic() - started) * 1000)
    log_event("turn", **turn)
