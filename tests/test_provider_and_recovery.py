from __future__ import annotations

import base64
import json
import subprocess
import wave
from pathlib import Path
from typing import Any

import httpx
import pytest

from voice_eval.domain import Segment
from voice_eval.profiles import get_preset
from voice_eval.providers import (
    GeminiAdapter,
    ProviderAmbiguousSubmit,
    ProviderAuthenticationError,
    ProviderError,
    ProviderInvalidRequest,
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


class CapturingTransport(FakeTransport):
    def __init__(self, response: httpx.Response) -> None:
        super().__init__(response)
        self.body: dict[str, Any] | None = None

    def post(
        self,
        url: str,
        *,
        headers: dict[str, str],
        json: dict[str, Any],
        timeout: float,
    ) -> httpx.Response:
        self.body = json
        return super().post(url, headers=headers, json=json, timeout=timeout)


@pytest.fixture
def fake_pcm_normalizer(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    command: list[str] = []

    def run(arguments: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        command.extend(arguments)
        output = Path(arguments[-1])
        with wave.open(str(output), "wb") as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(16_000)
            audio.writeframes(b"\x00\x00" * 160)
        return subprocess.CompletedProcess(arguments, 0)

    monkeypatch.setattr("voice_eval.media.subprocess.run", run)
    return command


def transcript_response() -> httpx.Response:
    payload = {
        "segments": [
            {
                "id": "provider-seg-1",
                "speaker": "unknown",
                "start": 0,
                "end": 0.01,
                "text": "Hello",
                "precision": "model_estimated",
            }
        ],
        "timestamp_warning": "Review timing and speakers.",
        "model": "ignored",
    }
    return httpx.Response(
        200,
        json={"candidates": [{"content": {"parts": [{"text": json.dumps(payload)}]}}]},
    )


def test_gemini_transcription_sends_normalized_pcm_wave(
    tmp_path: Path, fake_pcm_normalizer: list[str]
) -> None:
    audio = tmp_path / "mixed-stream.mp3"
    audio.write_bytes(b"ID3audio-with-attached-image")
    transport = CapturingTransport(transcript_response())

    result = GeminiAdapter(
        "secret-not-logged",
        "gemini-3.5-flash-lite",
        transport,
    ).transcribe(audio, "audio/mpeg")

    assert result.segments[0].text == "Hello"
    assert fake_pcm_normalizer[:5] == ["ffmpeg", "-nostdin", "-v", "error", "-y"]
    assert fake_pcm_normalizer[
        fake_pcm_normalizer.index("-map") : fake_pcm_normalizer.index("-map") + 2
    ] == ["-map", "0:a:0"]
    assert "-vn" in fake_pcm_normalizer
    assert transport.body is not None
    inline = transport.body["contents"][0]["parts"][0]["inlineData"]
    assert inline["mimeType"] == "audio/wav"
    assert base64.b64decode(inline["data"]).startswith(b"RIFF")
    assert b"attached-image" not in base64.b64decode(inline["data"])


def test_provider_rejected_request_is_safe_and_actionable(
    tmp_path: Path, fake_pcm_normalizer: list[str]
) -> None:
    audio = tmp_path / "call.mp3"
    audio.write_bytes(b"ID3")
    leaked = "secret-not-logged and private transcript"
    adapter = GeminiAdapter(
        "secret-not-logged",
        "gemini-3.5-flash-lite",
        FakeTransport(httpx.Response(400, json={"error": {"message": leaked}})),
    )

    with pytest.raises(ProviderInvalidRequest) as rejected:
        adapter.transcribe(audio, "audio/mpeg")

    message = str(rejected.value)
    assert "rejected the submitted content or model settings" in message
    assert "reviewed transcript" in message
    assert "secret-not-logged" not in message
    assert "private transcript" not in message


def test_gemini_api_key_reason_on_http_400_is_typed_and_redacted(
    tmp_path: Path, fake_pcm_normalizer: list[str]
) -> None:
    audio = tmp_path / "call.mp3"
    audio.write_bytes(b"ID3")
    leaked = "secret-not-logged was rejected for private@example.com"
    response = httpx.Response(
        400,
        json={
            "error": {
                "status": "INVALID_ARGUMENT",
                "message": leaked,
                "details": [
                    {
                        "@type": "type.googleapis.com/google.rpc.ErrorInfo",
                        "reason": "API_KEY_INVALID",
                        "metadata": {"credential": "secret-not-logged"},
                    }
                ],
            }
        },
    )
    adapter = GeminiAdapter(
        "secret-not-logged",
        "gemini-3.5-flash-lite",
        FakeTransport(response),
    )

    with pytest.raises(ProviderAuthenticationError) as rejected:
        adapter.transcribe(audio, "audio/mpeg")

    message = str(rejected.value)
    assert "rejected the session credential" in message
    assert "secret-not-logged" not in message
    assert "private@example.com" not in message
    assert "metadata" not in message


def test_provider_rate_limit_and_ambiguous_timeout_are_typed(
    tmp_path: Path, fake_pcm_normalizer: list[str]
) -> None:
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


def test_provider_response_size_is_bounded(
    tmp_path: Path, fake_pcm_normalizer: list[str]
) -> None:
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
