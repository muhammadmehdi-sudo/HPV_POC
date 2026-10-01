import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import app  # noqa: E402
import wa  # noqa: E402

APP_SECRET = "test-secret"


@pytest.fixture
def sent(monkeypatch, tmp_path):
    """Isolated app state; returns the list of Graph POSTs as (path, json) instead of hitting Meta."""
    monkeypatch.setenv("WA_APP_SECRET", APP_SECRET)
    monkeypatch.setenv("WA_VERIFY_TOKEN", "verify-me")
    monkeypatch.setenv("WA_PHONE_NUMBER_ID", "PHONE1")
    monkeypatch.setattr(app, "DATA_DIR", tmp_path)
    monkeypatch.setattr(app, "seen_ids", type(app.seen_ids)())
    monkeypatch.setattr(app, "user_lang", {})
    monkeypatch.setattr(app, "voice_media_id", None)
    calls = []

    def fake_graph_post(path, json=None, data=None, files=None):
        calls.append((path, json if json is not None else data))
        return {"id": "MEDIA1", "messages": [{"id": "wamid.out"}]}

    monkeypatch.setattr(wa, "graph_post", fake_graph_post)
    monkeypatch.setattr(wa, "download_media", lambda media_id: b"OggS-fake-audio")
    return calls
