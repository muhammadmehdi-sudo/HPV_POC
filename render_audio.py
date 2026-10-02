"""Pre-render every unit's answer audio: python render_audio.py (needs ELEVENLABS_API_KEY in .env).

Writes assets/audio/<unit_id>.<en|ur>.ogg. Roman Urdu users get the Urdu-script audio: TTS must never
read Roman Urdu (POC_TECH_ANALYSIS.md §3.4).
"""
import os
import sys

from dotenv import load_dotenv

import app
import brain
import speech

MAX_VOICE_BYTES = 512 * 1024  # larger files arrive as an audio attachment, not a voice-note bubble


def main():
    load_dotenv()
    content = brain.Content(os.environ.get("CONTENT_PATH", app.ROOT / "content" / "hpv_placeholder.yaml"))
    app.AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    for unit in content.units.values():
        for lang in ("en", "ur"):
            # eleven_v3 treats [bracketed] text as a performance tag and would skip the placeholder marker.
            text = unit["text"][lang].replace("[", "").replace("]", ".")
            audio = speech.synthesize(text, lang)
            if len(audio) > MAX_VOICE_BYTES:
                sys.exit(f"{unit['id']}.{lang}: {len(audio)} bytes > {MAX_VOICE_BYTES}; shorten the text")
            (app.AUDIO_DIR / f"{unit['id']}.{lang}.ogg").write_bytes(audio)
            print(f"{unit['id']}.{lang}.ogg  {len(audio)} bytes")


if __name__ == "__main__":
    main()
