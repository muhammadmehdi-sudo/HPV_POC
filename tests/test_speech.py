import math

import httpx

import speech


def test_hindi_detection_retried_as_urdu(monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "k")
    calls = []

    def fake_post(url, headers=None, data=None, files=None, timeout=None):
        calls.append(data)
        result = {"language_code": data.get("language_code", "hin"),
                  "text": " بے ہوش " if "language_code" in data else "बेहोश",
                  "words": [{"text": "بے", "type": "word", "logprob": math.log(0.9)},
                            {"text": " ", "type": "spacing", "logprob": 0.0},
                            {"text": "ہوش", "type": "word", "logprob": math.log(0.5)}]}
        return httpx.Response(200, json=result, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "post", fake_post)
    text, confidence = speech.transcribe(b"OggS")
    assert text == "بے ہوش" and round(confidence, 3) == 0.7
    assert [c.get("language_code") for c in calls] == [None, "urd"]
    assert all(c["tag_audio_events"] == "false" for c in calls)
