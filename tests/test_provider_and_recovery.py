from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from voice_eval.domain import Segment
from voice_eval.profiles import get_preset
from voice_eval.providers import (
    GeminiAdapter,
    ProviderAmbiguousSubmit,
    ProviderError,
    ProviderRateLimited,
)
from voice_eval.store import Store, job_values


class FakeTransport:
    def __init__(self, response: httpx.Response | Exception) -> None:
        self.response = response

    def post(
        self,
        url: str,
        *,
        headers: dict[str, str],
        json: dict[str, Any],
        timeout: float,
    ) -> httpx.Response:
        assert headers["x-goog-api-key"] == "secret-not-logged"
        assert "secret-not-logged" not in url
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def test_provider_rate_limit_and_ambiguous_timeout_are_typed(tmp_path: Path) -> None:
    audio = tmp_path / "call.mp3"
    audio.write_bytes(b"ID3")
    limited = GeminiAdapter(
        "secret-not-logged",
        "gemini-3.5-flash-lite",
        FakeTransport(httpx.Response(429, headers={"Retry-After": "30"})),
    )
    with pytest.raises(ProviderRateLimited) as rate_limit:
        limited.transcribe(audio, "audio/mpeg")
    assert rate_limit.value.retry_after == "30"

    timed_out = GeminiAdapter(
        "secret-not-logged",
        "gemini-3.5-flash-lite",
        FakeTransport(httpx.ReadTimeout("uncertain")),
    )
    with pytest.raises(ProviderAmbiguousSubmit, match="resubmission is disabled"):
        timed_out.transcribe(audio, "audio/mpeg")


def test_inline_audio_limit_rejects_before_provider_request(tmp_path: Path) -> None:
    audio = tmp_path / "large.mp3"
    with audio.open("wb") as output:
        output.truncate(70 * 1024 * 1024 + 1)
    adapter = GeminiAdapter(
        "secret-not-logged",
        "gemini-3.5-flash-lite",
        FakeTransport(AssertionError("transport must not be called")),
    )
    with pytest.raises(ProviderError, match="too large"):
        adapter.transcribe(audio, "audio/mpeg")


def test_provider_response_size_is_bounded(tmp_path: Path) -> None:
    audio = tmp_path / "call.mp3"
    audio.write_bytes(b"ID3")
    adapter = GeminiAdapter(
        "secret-not-logged",
        "gemini-3.5-flash-lite",
        FakeTransport(httpx.Response(200, content=b"x" * (5 * 1024 * 1024 + 1))),
    )
    with pytest.raises(ProviderError, match="5 MiB"):
        adapter.transcribe(audio, "audio/mpeg")


def test_provider_judge_validates_boolean_polarity_and_grade() -> None:
    segments = [
        Segment(id="s1", speaker="customer", text="Order nahi mila"),
        Segment(id="s2", speaker="agent", text="I understand order nahi mila"),
    ]
    findings = [
        {
            "metric_id": "semantic_uptake",
            "verdict": "PASS",
            "rationale": "The reply preserves the caller's negation.",
            "evidence": [
                {"segment_id": "s1", "quote": "nahi", "start_char": 6, "end_char": 10}
            ],
            "boolean_result": {
                "name": "meaning_respected",
                "value": True,
                "pass_when": True,
                "measurement_kind": "schema_judge",
            },
            "grade_result": {
                "scale": "proposed-quality-v1",
                "value": 2,
                "classification": "MEETS_EXPECTATIONS",
                "measurement_kind": "schema_judge",
            },
            "measurements": [],
        },
        {
            "metric_id": "unnecessary_repetition",
            "verdict": "PASS",
            "rationale": "No avoidable repeat was present.",
            "evidence": [
                {
                    "segment_id": "s2",
                    "quote": "I understand",
                    "start_char": 0,
                    "end_char": 12,
                }
            ],
            "boolean_result": {
                "name": "unnecessary_repetition",
                "value": False,
                "pass_when": False,
                "measurement_kind": "schema_judge",
            },
            "grade_result": {
                "scale": "proposed-quality-v1",
                "value": 2,
                "classification": "MEETS_EXPECTATIONS",
                "measurement_kind": "schema_judge",
            },
            "measurements": [],
        },
        {
            "metric_id": "scenario_flow",
            "verdict": "UNKNOWN",
            "rationale": "Configured flow needs more context.",
            "evidence": [],
            "boolean_result": {
                "name": "flow_followed",
                "value": None,
                "pass_when": True,
                "measurement_kind": "schema_judge",
            },
            "grade_result": {
                "scale": "proposed-quality-v1",
                "value": None,
                "classification": None,
                "measurement_kind": "schema_judge",
            },
            "measurements": [],
        },
    ]

    def response_for(payload: list[dict[str, Any]]) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {"content": {"parts": [{"text": json.dumps({"findings": payload})}]}}
                ]
            },
        )

    adapter = GeminiAdapter(
        "secret-not-logged",
        "gemini-3.5-flash-lite",
        FakeTransport(response_for(findings)),
    )
    result = adapter.judge(segments, get_preset("food-delivery"))
    repetition = next(
        item for item in result.findings if item.metric_id == "unnecessary_repetition"
    )
    assert repetition.boolean_result is not None
    assert repetition.boolean_result.value is False

    invalid = json.loads(json.dumps(findings))
    invalid[1]["boolean_result"]["value"] = True
    invalid_adapter = GeminiAdapter(
        "secret-not-logged",
        "gemini-3.5-flash-lite",
        FakeTransport(response_for(invalid)),
    )
    with pytest.raises(ProviderError, match="schema validation"):
        invalid_adapter.judge(segments, get_preset("food-delivery"))

    invalid_grade = json.loads(json.dumps(findings))
    invalid_grade[0]["grade_result"]["value"] = True
    invalid_grade_adapter = GeminiAdapter(
        "secret-not-logged",
        "gemini-3.5-flash-lite",
        FakeTransport(response_for(invalid_grade)),
    )
    with pytest.raises(ProviderError, match="schema validation"):
        invalid_grade_adapter.judge(segments, get_preset("food-delivery"))


def test_store_recovers_claim_and_prevents_late_write_after_delete(tmp_path: Path) -> None:
    store = Store(tmp_path / "db.sqlite3")
    media = tmp_path / "audio.wav"
    media.write_bytes(b"audio")
    values = job_values(
        job_id="job-1",
        idempotency_key=None,
        payload_hash="a" * 64,
        status="queued",
        status_detail="queued",
        original_name="audio.wav",
        media_path=media,
        media={"duration_seconds": 1},
        profile={"id": "generic-conversation"},
        profile_hash="b" * 64,
        transcript=None,
    )
    store.create_job(values)
    claimed = store.claim_next()
    assert claimed is not None
    assert claimed["status"] == "transcribing"
    assert store.recover_interrupted() == 1
    recovered = store.get_job("job-1")
    assert recovered["status"] == "failed"
    assert "automatic resubmission is disabled" in recovered["status_detail"]
    store.delete_job("job-1")
    with pytest.raises(PermissionError):
        store.update("job-1", status="completed", report_json=json.dumps({"late": True}))
