"""Speech-to-text for inbound voice notes (ElevenLabs) and text-to-speech for offline answer audio
(Uplift for Urdu, ElevenLabs for English)."""
import math
import os
import subprocess

import httpx

API = "https://api.elevenlabs.io/v1"
STT_MODEL = "scribe_v2"
TTS_MODEL = "eleven_v3"
VOICE_ID = "EXAVITQu4vr4xnSDxMaL"  # premade "Sarah"
UPLIFT_TTS = "https://api.upliftai.org/v1/synthesis/text-to-speech"
UPLIFT_VOICE_ID = "v_8eelc901"  # "Info/Edu"; others: v_kwmp7zxt Gen Z, v_yypgzenx Dada Jee, v_30s70t3a Nostalgic News
TTS_FORMAT = "opus_48000_32"  # mono Ogg/Opus, which WhatsApp renders as a voice note


def _auth():
    return {"xi-api-key": os.environ["ELEVENLABS_API_KEY"]}


def transcribe(audio, language_code=None):
    """(text, confidence): confidence is the mean word probability, 0.0 when no words were heard.
    language_probability is not used: it scored a clear "Is it safe?" at 0.125."""
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
    words = [w for w in result.get("words", []) if w.get("type") == "word"]
    confidence = sum(math.exp(w["logprob"]) for w in words) / len(words) if words else 0.0
    return result["text"].strip(), confidence


def synthesize(text, lang):
    if lang == "ur":
        response = httpx.post(UPLIFT_TTS, headers={"Authorization": f"Bearer {os.environ['UPLIFT_API_KEY']}"},
                              json={"voiceId": UPLIFT_VOICE_ID, "text": text, "outputFormat": "OGG_22050_16"}, timeout=120)
        response.raise_for_status()
        # Uplift's OGG is Vorbis; WhatsApp only renders Ogg/Opus as a voice note.
        return subprocess.run(["ffmpeg", "-v", "error", "-i", "pipe:0", "-c:a", "libopus", "-b:a", "32k", "-ac", "1",
                               "-ar", "48000", "-f", "ogg", "pipe:1"], input=response.content, capture_output=True, check=True).stdout
    response = httpx.post(f"{API}/text-to-speech/{VOICE_ID}", params={"output_format": TTS_FORMAT}, headers=_auth(),
                          json={"text": text, "model_id": TTS_MODEL, "language_code": lang}, timeout=120)
    response.raise_for_status()
    return response.content
