from __future__ import annotations

import json
import wave
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from voice_eval.app import create_app
from voice_eval.config import Settings


@pytest.fixture
def wav_bytes(tmp_path: Path) -> bytes:
    path = tmp_path / "sample.wav"
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(8_000)
        audio.writeframes(b"\x00\x00" * 8_000 * 8)
    return path.read_bytes()


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    settings = Settings(
        _env_file=None,
        data_dir=tmp_path / "data",
        database_path=tmp_path / "data" / "app.sqlite3",
        ffprobe_path="internal-wave",
        start_worker=False,
        GEMINI_API_KEY=None,
        GEMINI_MODEL="gemini-3.5-flash-lite",
        GEMINI_FREE_TIER_CONFIRMED=False,
        allowed_hosts={"testserver", "localhost", "127.0.0.1"},
    )
    app = create_app(settings)
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def dental_profile() -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "id": "dental-appointment",
        "name": "Dental appointment",
        "task_description": "Help a caller arrange a dental appointment.",
        "expected_outcome": "Understand the need and agree on a clear next step.",
        "required_information": ["appointment reason", "preferred date or time"],
        "policies": [],
        "custom_criteria": ["Do not claim calendar booking without backend evidence."],
    }


@pytest.fixture
def transcript_json() -> str:
    return json.dumps(
        [
            {
                "id": "seg-1",
                "speaker": "customer",
                "start": 0.0,
                "end": 3.0,
                "text": "I need a cleaning appointment next Tuesday.",
                "precision": "manual",
            },
            {
                "id": "seg-2",
                "speaker": "agent",
                "start": 3.0,
                "end": 7.0,
                "text": "I can help with a cleaning appointment next Tuesday.",
                "precision": "manual",
            },
        ]
    )
