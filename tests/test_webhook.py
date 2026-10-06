import hashlib
import hmac
import json

import httpx
import pytest
from fastapi.testclient import TestClient

import app
import speech
from conftest import APP_SECRET

client = TestClient(app.app)
USER = "923001234567"


def post(payload, secret=APP_SECRET, signature=None):
    raw = json.dumps(payload).encode()
    if signature is None:
        signature = "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    return client.post("/webhook", content=raw, headers={"X-Hub-Signature-256": signature, "Content-Type": "application/json"})


def envelope(message=None, status=None):
    value = {"messaging_product": "whatsapp", "metadata": {"phone_number_id": "PHONE1"}}
    if message:
        value["contacts"] = [{"wa_id": USER, "profile": {"name": "Test"}}]
        value["messages"] = [{"from": USER, "id": "wamid.in1", "timestamp": "1790000000", **message}]
    if status:
        value["statuses"] = [status]
    return {"object": "whatsapp_business_account",
            "entry": [{"id": "WABA1", "changes": [{"field": "messages", "value": value}]}]}


def messages_sent(calls):
    return [body for path, body in calls if path == "PHONE1/messages" and "status" not in body]


def test_verify_handshake(sent):
    ok = client.get("/webhook", params={"hub.mode": "subscribe", "hub.verify_token": "verify-me", "hub.challenge": "42"})
    assert (ok.status_code, ok.text) == (200, "42")
    bad = client.get("/webhook", params={"hub.mode": "subscribe", "hub.verify_token": "nope", "hub.challenge": "42"})
    assert bad.status_code == 403


def test_signature_rejected(sent):
    payload = envelope({"type": "text", "text": {"body": "hi"}})
    assert post(payload, secret="wrong").status_code == 403
    assert post(payload, signature="").status_code == 403
    assert post(payload, signature="sha1=abc").status_code == 403
    assert sent == []


def test_text_answer_with_related_buttons(sent):
    assert post(envelope({"type": "text", "text": {"body": "kya hpv vaccine mehfooz hai"}})).status_code == 200
    read, reply = sent
    assert read[1]["status"] == "read" and read[1]["typing_indicator"] == {"type": "text"}
    body = reply[1]
    assert body["to"] == USER and body["interactive"]["type"] == "button"
    assert body["interactive"]["body"]["text"].startswith("[PLACEHOLDER – tibbi mashwara nahi] HPV vaccine duniya")
    assert [b["reply"]["id"] for b in body["interactive"]["action"]["buttons"]] == ["hpv.side_effects", "hpv.fertility_myth"]


def test_danger_sends_emergency_text_and_logs(sent):
    post(envelope({"type": "text", "text": {"body": "teeka lagne ke baad behosh ho gayi"}}))
    (reply,) = messages_sent(sent)
    assert reply["type"] == "text" and "1122" in reply["text"]["body"]
    log = (app.DATA_DIR / "turns.jsonl").read_text(encoding="utf-8")
    assert '"kind": "escalation"' in log


def test_out_of_scope_sends_topic_list(sent):
    post(envelope({"type": "text", "text": {"body": "bitcoin price"}}))
    (reply,) = messages_sent(sent)
    rows = reply["interactive"]["action"]["sections"][0]["rows"]
    assert reply["interactive"]["type"] == "list" and len(rows) == 6


def test_button_tap_serves_unit_in_users_language(sent):
    post(envelope({"type": "text", "text": {"body": "کیا ایچ پی وی ویکسین محفوظ ہے؟"}}))
    sent.clear()
    tap = {"type": "interactive", "id": "wamid.in2",
           "interactive": {"type": "button_reply", "button_reply": {"id": "hpv.side_effects", "title": "مضر اثرات"}}}
    post(envelope(tap))
    (reply,) = messages_sent(sent)
    assert reply["interactive"]["body"]["text"].startswith("[عارضی متن")


def test_list_reply_serves_unit(sent):
    tap = {"type": "interactive",
           "interactive": {"type": "list_reply", "list_reply": {"id": "hpv.where_to_get", "title": "Where to get it"}}}
    post(envelope(tap))
    (reply,) = messages_sent(sent)
    assert "government health centres" in reply["interactive"]["body"]["text"]


VOICE_NOTE = {"type": "audio", "audio": {"id": "MEDIA_IN", "mime_type": "audio/ogg; codecs=opus", "voice": True}}


def test_voice_note_answered_with_text_then_urdu_voice_note(sent, monkeypatch):
    monkeypatch.setattr(speech, "transcribe", lambda audio: ("kya hpv vaccine mehfooz hai", 0.95))
    app.AUDIO_DIR.mkdir()
    (app.AUDIO_DIR / "hpv.safety.ur.ogg").write_bytes(b"OggS")
    post(envelope(VOICE_NOTE))
    assert (app.DATA_DIR / "inbound" / "MEDIA_IN.ogg").read_bytes() == b"OggS-fake-audio"
    uploads = [body for path, body in sent if path == "PHONE1/media"]
    assert uploads == [{"messaging_product": "whatsapp", "type": "audio/ogg"}]
    first, second = messages_sent(sent)
    assert first["interactive"]["body"]["text"].startswith("[PLACEHOLDER – tibbi mashwara nahi] HPV vaccine duniya")
    assert second == {"messaging_product": "whatsapp", "recipient_type": "individual", "to": USER,
                      "type": "audio", "audio": {"id": "MEDIA1", "voice": True}}
    log = (app.DATA_DIR / "turns.jsonl").read_text(encoding="utf-8")
    assert '"audio": "hpv.safety.ur.ogg"' in log and '"text": "kya hpv vaccine mehfooz hai"' in log


def test_voice_note_without_rendered_audio_gets_text_only(sent, monkeypatch):
    monkeypatch.setattr(speech, "transcribe", lambda audio: ("is hpv vaccine safe", 0.95))
    post(envelope(VOICE_NOTE))
    (reply,) = messages_sent(sent)
    assert reply["interactive"]["body"]["text"].startswith("[PLACEHOLDER – not medical advice] The HPV vaccine")
    assert [path for path, _ in sent if path == "PHONE1/media"] == []


def failing_stt(audio):
    raise httpx.HTTPStatusError("500", request=httpx.Request("POST", "https://stt"), response=httpx.Response(500))


@pytest.mark.parametrize("stt", [lambda audio: ("", 0.0), failing_stt])
def test_unclear_voice_note_gets_topic_list(sent, monkeypatch, stt):
    monkeypatch.setattr(speech, "transcribe", stt)
    post(envelope(VOICE_NOTE))
    (reply,) = messages_sent(sent)
    assert reply["interactive"]["type"] == "list"
    assert reply["interactive"]["body"]["text"].startswith("Sorry, I could not understand")
    assert '"action": "voice_unclear"' in (app.DATA_DIR / "turns.jsonl").read_text(encoding="utf-8")


def test_low_confidence_voice_note_asks_to_confirm(sent, monkeypatch):
    monkeypatch.setattr(speech, "transcribe", lambda audio: ("کیا HPV vaccine safe ہے؟", 0.6))
    post(envelope(VOICE_NOTE))
    (reply,) = messages_sent(sent)
    assert reply["interactive"]["body"]["text"] == "کیا آپ نے اس بارے میں پوچھا: کیا یہ محفوظ ہے؟"
    assert [b["reply"]["id"] for b in reply["interactive"]["action"]["buttons"]] == ["confirm:hpv.safety", "menu"]
    assert '"action": "confirm"' in (app.DATA_DIR / "turns.jsonl").read_text(encoding="utf-8")


def test_confirm_tap_sends_answer_text_then_voice_note(sent):
    app.user_lang[USER] = "ur"
    app.AUDIO_DIR.mkdir()
    (app.AUDIO_DIR / "hpv.safety.ur.ogg").write_bytes(b"OggS")
    tap = {"type": "interactive", "interactive": {"type": "button_reply", "button_reply": {"id": "confirm:hpv.safety", "title": "جی ہاں"}}}
    post(envelope(tap))
    text, voice = messages_sent(sent)
    assert text["interactive"]["body"]["text"].startswith("[عارضی متن")
    assert voice["audio"] == {"id": "MEDIA1", "voice": True}


def test_topics_tap_after_confirm_sends_topic_list(sent):
    tap = {"type": "interactive", "interactive": {"type": "button_reply", "button_reply": {"id": "menu", "title": "Topics"}}}
    post(envelope(tap))
    (reply,) = messages_sent(sent)
    assert reply["interactive"]["type"] == "list" and reply["interactive"]["body"]["text"] == "Did you mean one of these?"


def test_low_confidence_emergency_is_not_held_for_confirmation(sent, monkeypatch):
    monkeypatch.setattr(speech, "transcribe", lambda audio: ("teeka lagne ke baad behosh ho gayi", 0.4))
    post(envelope(VOICE_NOTE))
    reply = messages_sent(sent)[0]
    assert reply["type"] == "text" and "1122" in reply["text"]["body"]


def test_unsupported_type_gets_explanation(sent):
    post(envelope({"type": "image", "image": {"id": "IMG1", "mime_type": "image/jpeg"}}))
    (reply,) = messages_sent(sent)
    assert reply["interactive"]["body"]["text"].startswith("I can only read text")


def test_status_only_webhook_sends_nothing(sent):
    post(envelope(status={"id": "wamid.out", "status": "played", "timestamp": "1790000001", "recipient_id": USER}))
    assert sent == []
    assert '"status": "played"' in (app.DATA_DIR / "turns.jsonl").read_text(encoding="utf-8")


def test_duplicate_delivery_handled_once(sent):
    payload = envelope({"type": "text", "text": {"body": "hi"}})
    post(payload)
    post(payload)
    assert len(messages_sent(sent)) == 1


def test_malformed_json_acked(sent):
    raw = b"{not json"
    sig = "sha256=" + hmac.new(APP_SECRET.encode(), raw, hashlib.sha256).hexdigest()
    response = client.post("/webhook", content=raw, headers={"X-Hub-Signature-256": sig})
    assert response.status_code == 200 and sent == []
