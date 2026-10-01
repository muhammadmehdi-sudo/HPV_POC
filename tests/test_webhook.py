import hashlib
import hmac
import json

from fastapi.testclient import TestClient

import app
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


def test_voice_note_downloaded_then_text_and_voice_reply(sent):
    post(envelope({"type": "audio", "audio": {"id": "MEDIA_IN", "mime_type": "audio/ogg; codecs=opus", "voice": True}}))
    assert (app.DATA_DIR / "inbound" / "MEDIA_IN.ogg").read_bytes() == b"OggS-fake-audio"
    uploads = [body for path, body in sent if path == "PHONE1/media"]
    assert uploads == [{"messaging_product": "whatsapp", "type": "audio/ogg"}]
    first, second = messages_sent(sent)
    assert first["type"] == "text"
    assert second == {"messaging_product": "whatsapp", "recipient_type": "individual", "to": USER,
                      "type": "audio", "audio": {"id": "MEDIA1", "voice": True}}


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
