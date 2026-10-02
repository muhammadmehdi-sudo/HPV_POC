"""ElevenLabs speech-to-text (inbound voice notes) and text-to-speech (offline answer audio)."""
import os

import httpx

API = "https://api.elevenlabs.io/v1"
STT_MODEL = "scribe_v2"
TTS_MODEL = "eleven_v3"  # the only ElevenLabs TTS model that accepts language_code "ur"
VOICE_ID = "JBFqnCBsd6RMkjVDRZzb"  # premade voice; swap for a reviewed Urdu voice
TTS_FORMAT = "opus_48000_32"  # mono Ogg/Opus, which WhatsApp renders as a voice note


def _auth():
    return {"xi-api-key": os.environ["ELEVENLABS_API_KEY"]}


def transcribe(audio, language_code=None):
    # Audio-event tags ("[beep]", "(laughter)") would otherwise be matched as if the user said them.
    data = {"model_id": STT_MODEL, "tag_audio_events": "false"}
    if language_code:
        data["language_code"] = language_code
    response = httpx.post(f"{API}/speech-to-text", headers=_auth(), data=data,
                          files={"file": ("voice.ogg", audio, "audio/ogg")}, timeout=60)
    response.raise_for_status()
    result = response.json()
    # Spoken Urdu is often detected as Hindi and written in Devanagari, which retrieval cannot match.
    if not language_code and result["language_code"] not in ("eng", "urd"):
        return transcribe(audio, "urd")
    return result["text"].strip()


def synthesize(text, lang):
    response = httpx.post(f"{API}/text-to-speech/{VOICE_ID}", params={"output_format": TTS_FORMAT}, headers=_auth(),
                          json={"text": text, "model_id": TTS_MODEL, "language_code": lang}, timeout=120)
    response.raise_for_status()
    return response.content
