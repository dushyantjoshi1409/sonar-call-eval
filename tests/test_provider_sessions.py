from __future__ import annotations

import json
import time
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from voice_eval.app import create_app
from voice_eval.config import Settings
from voice_eval.domain import Segment
from voice_eval.profiles import get_preset
from voice_eval.provider_sessions import ProviderSessionVault
from voice_eval.providers import (
    OpenAICompatibleAdapter,
    ProviderAuthenticationError,
    ProviderConfig,
    ProviderRateLimited,
    ProviderUnsupported,
    validate_custom_base_url,
)


def _judge_findings() -> list[dict[str, object]]:
    common_grade = {
        "scale": "proposed-quality-v1",
        "value": 2,
        "classification": "MEETS_EXPECTATIONS",
        "measurement_kind": "schema_judge",
    }
    return [
        {
            "metric_id": "semantic_uptake",
            "verdict": "PASS",
            "rationale": "Meaning is preserved.",
            "evidence": [{"segment_id": "s1", "quote": "not", "start_char": 9, "end_char": 12}],
            "boolean_result": {
                "name": "meaning_respected",
                "value": True,
                "pass_when": True,
                "measurement_kind": "schema_judge",
            },
            "grade_result": common_grade,
            "measurements": [],
        },
        {
            "metric_id": "unnecessary_repetition",
            "verdict": "PASS",
            "rationale": "No repetition.",
            "evidence": [
                {"segment_id": "s2", "quote": "understand", "start_char": 2, "end_char": 12}
            ],
            "boolean_result": {
                "name": "unnecessary_repetition",
                "value": False,
                "pass_when": False,
                "measurement_kind": "schema_judge",
            },
            "grade_result": common_grade,
            "measurements": [],
        },
        {
            "metric_id": "scenario_flow",
            "verdict": "PASS",
            "rationale": "The flow is complete.",
            "evidence": [{"segment_id": "s2", "quote": "order", "start_char": 15, "end_char": 20}],
            "boolean_result": {
                "name": "flow_followed",
                "value": True,
                "pass_when": True,
                "measurement_kind": "schema_judge",
            },
            "grade_result": common_grade,
            "measurements": [],
        },
    ]


def test_openai_compatible_contracts_are_provider_specific(tmp_path: Path) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.headers["authorization"] == "Bearer browser-secret"
        if request.url.path.endswith("/chat/completions"):
            body = json.loads(request.content)
            assert body["response_format"]["json_schema"]["strict"] is True
            assert body["model"] == "gpt-4o-mini"
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {"message": {"content": json.dumps({"findings": _judge_findings()})}}
                    ]
                },
            )
        assert request.url.path.endswith("/audio/transcriptions")
        assert b'name="response_format"' in request.content
        assert b"verbose_json" in request.content
        assert b'name="model"' in request.content
        assert b"whisper-1" in request.content
        return httpx.Response(
            200,
            json={
                "text": "Order not delivered",
                "segments": [{"start": 0.0, "end": 1.2, "text": "Order not delivered"}],
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    config = ProviderConfig(
        provider="openai",
        api_key="browser-secret",
        judge_model="gpt-4o-mini",
        transcription_model="whisper-1",
        allow_paid_use=True,
    )
    audio = tmp_path / "call.wav"
    audio.write_bytes(b"RIFF-audio")
    segments = [
        Segment(id="s1", speaker="customer", text="Order is not here"),
        Segment(id="s2", speaker="agent", text="I understand order status"),
    ]

    with OpenAICompatibleAdapter(config, client) as adapter:
        judged = adapter.judge(segments, get_preset("food-delivery"))
        transcript = adapter.transcribe(audio, "audio/wav")

    assert len(judged.findings) == 3
    assert transcript.segments[0].speaker == "unknown"
    assert transcript.segments[0].precision == "model_estimated"
    assert len(requests) == 2


def test_provider_errors_are_typed_and_never_echo_upstream_body(tmp_path: Path) -> None:
    secret = "top-secret-browser-key"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/chat/completions"):
            return httpx.Response(401, text=f"echoed {secret} and transcript input")
        return httpx.Response(429, headers={"Retry-After": "7"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    config = ProviderConfig(
        provider="openai",
        api_key=secret,
        judge_model="gpt-4o-mini",
        transcription_model="whisper-1",
        allow_paid_use=True,
    )
    adapter = OpenAICompatibleAdapter(config, client)
    segments = [
        Segment(id="s1", speaker="customer", text="Order is not here"),
        Segment(id="s2", speaker="agent", text="I understand order status"),
    ]
    with pytest.raises(ProviderAuthenticationError) as denied:
        adapter.judge(segments, get_preset("food-delivery"))
    assert secret not in str(denied.value)
    assert "transcript input" not in str(denied.value)

    audio = tmp_path / "call.wav"
    audio.write_bytes(b"RIFF-audio")
    with pytest.raises(ProviderRateLimited) as limited:
        adapter.transcribe(audio, "audio/wav")
    assert limited.value.retry_after == "7"


def test_chat_only_custom_provider_rejects_transcription() -> None:
    config = ProviderConfig(
        provider="custom",
        api_key="custom-secret",
        judge_model="compatible-model",
        base_url="https://api.example.com/v1",
        allow_paid_use=True,
    )
    adapter = OpenAICompatibleAdapter(
        config, httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(500)))
    )
    with pytest.raises(ProviderUnsupported, match="reviewed transcript"):
        adapter.transcribe(Path("unused.wav"), "audio/wav")


@pytest.mark.parametrize(
    "url,addresses",
    [
        ("http://public.example/v1", ["93.184.216.34"]),
        ("https://user:pass@public.example/v1", ["93.184.216.34"]),
        ("https://public.example/v1?key=value", ["93.184.216.34"]),
        ("https://localhost/v1", ["127.0.0.1"]),
        ("https://public.example/v1", ["10.0.0.4"]),
        ("https://public.example/v1", ["2001:db8::1"]),
    ],
)
def test_custom_endpoint_rejects_unsafe_destinations(url: str, addresses: list[str]) -> None:
    with pytest.raises(ValueError):
        validate_custom_base_url(url, resolver=lambda _: addresses)


def test_provider_vault_isolates_clears_and_drops_credentials_on_restart() -> None:
    first = ProviderSessionVault(ttl_seconds=60)
    one = first.connect(
        ProviderConfig(
            provider="groq",
            api_key="session-one-secret",
            judge_model="openai/gpt-oss-20b",
            transcription_model="whisper-large-v3-turbo",
            free_tier_attested=True,
        )
    )
    two = first.connect(
        ProviderConfig(
            provider="groq",
            api_key="session-two-secret",
            judge_model="openai/gpt-oss-20b",
            transcription_model="whisper-large-v3-turbo",
            free_tier_attested=True,
        )
    )
    assert first.resolve_cookie(one.cookie_token).api_key == "session-one-secret"
    assert first.resolve_cookie(two.cookie_token).api_key == "session-two-secret"
    first.clear(one.cookie_token)
    assert first.resolve_cookie(one.cookie_token) is None
    assert first.resolve_cookie(two.cookie_token) is not None
    assert ProviderSessionVault(ttl_seconds=60).resolve_handle(two.credential_handle) is None


def test_provider_vault_expires_credentials() -> None:
    vault = ProviderSessionVault(ttl_seconds=1)
    session = vault.connect(
        ProviderConfig(
            provider="gemini",
            api_key="short-lived-secret",
            judge_model="gemini-3.5-flash-lite",
            transcription_model="gemini-3.5-flash-lite",
            free_tier_attested=True,
        )
    )

    time.sleep(1.01)

    assert vault.resolve_cookie(session.cookie_token) is None
    assert vault.resolve_handle(session.credential_handle) is None


def test_session_endpoint_never_persists_or_returns_key(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,
        data_dir=tmp_path / "data",
        database_path=tmp_path / "data" / "app.sqlite3",
        ffprobe_path="internal-wave",
        start_worker=False,
        GEMINI_API_KEY=None,
        allowed_hosts={"testserver"},
    )
    secret = "browser-only-key-123"
    with TestClient(create_app(settings)) as client:
        response = client.post(
            "/api/provider-session",
            json={
                "provider": "groq",
                "api_key": secret,
                "judge_model": "openai/gpt-oss-20b",
                "transcription_model": "whisper-large-v3-turbo",
                "free_tier_attested": True,
                "allow_paid_use": False,
            },
        )
        assert response.status_code == 201
        assert secret not in response.text
        assert "HttpOnly" in response.headers["set-cookie"]
        assert "SameSite=strict" in response.headers["set-cookie"]
        assert secret.encode() not in settings.database_path.read_bytes()

        metadata = client.get("/api/provider-session")
        assert metadata.json()["provider"] == "groq"
        cleared = client.delete("/api/provider-session")
        assert cleared.status_code == 200
        assert client.get("/api/provider-session").json()["connected"] is False


def test_malformed_credential_request_redacts_validation_input(client: TestClient) -> None:
    secret = "sentinel-validation-secret"
    response = client.post(
        "/api/provider-session",
        json={
            "provider": "not-a-provider",
            "api_key": secret,
            "judge_model": {"invalid": secret},
        },
    )
    assert response.status_code == 422
    assert secret not in response.text
    assert response.json() == {"detail": "Invalid provider session configuration"}


def test_cost_policy_requires_explicit_session_attestation_or_opt_in() -> None:
    with pytest.raises(ValueError, match="free-tier attestation"):
        ProviderConfig(
            provider="gemini",
            api_key="key",
            judge_model="gemini-3.5-flash-lite",
            transcription_model="gemini-3.5-flash-lite",
        )
    with pytest.raises(ValueError, match="paid-use opt-in"):
        ProviderConfig(
            provider="openai",
            api_key="key",
            judge_model="gpt-4o-mini",
            transcription_model="whisper-1",
        )


def test_job_captures_session_handle_and_clear_fails_without_env_fallback(
    client: TestClient,
    wav_bytes: bytes,
    dental_profile: dict[str, object],
    transcript_json: str,
) -> None:
    secret = "captured-session-only-secret"
    connected = client.post(
        "/api/provider-session",
        json={
            "provider": "gemini",
            "api_key": secret,
            "judge_model": "gemini-3.5-flash-lite",
            "transcription_model": "gemini-3.5-flash-lite",
            "free_tier_attested": True,
        },
    )
    assert connected.status_code == 201
    created = client.post(
        "/api/jobs",
        files={"audio": ("appointment.wav", wav_bytes, "audio/wav")},
        data={
            "profile_json": json.dumps(dental_profile),
            "transcript_json": transcript_json,
        },
    )
    assert created.status_code == 201
    job_id = created.json()["id"]
    assert created.json()["provider_handle"] is None
    internal = client.app.state.runtime.store.get_job(job_id)
    assert internal["provider_handle"]
    assert secret.encode() not in client.app.state.runtime.settings.database_path.read_bytes()

    assert client.delete("/api/provider-session").status_code == 200
    evaluated = client.post(f"/api/jobs/{job_id}/evaluate")
    assert evaluated.status_code == 503
    assert "reconnect" in evaluated.json()["detail"].lower()


def test_provider_transcript_mode_requires_audio_capable_connection(
    client: TestClient, wav_bytes: bytes, dental_profile: dict[str, object]
) -> None:
    missing = client.post(
        "/api/jobs",
        files={"audio": ("appointment.wav", wav_bytes, "audio/wav")},
        data={
            "profile_json": json.dumps(dental_profile),
            "transcript_mode": "provider",
        },
    )
    assert missing.status_code == 409
    assert "connect" in missing.json()["detail"].lower()
    assert list(client.app.state.runtime.media_root.rglob("*")) == []

    connected = client.post(
        "/api/provider-session",
        json={
            "provider": "gemini",
            "api_key": "chat-only-test-key",
            "judge_model": "gemini-3.5-flash-lite",
            "transcription_model": None,
            "free_tier_attested": True,
        },
    )
    assert connected.status_code == 201
    unsupported = client.post(
        "/api/jobs",
        files={"audio": ("appointment.wav", wav_bytes, "audio/wav")},
        data={
            "profile_json": json.dumps(dental_profile),
            "transcript_mode": "provider",
        },
    )
    assert unsupported.status_code == 422
    assert "chat-only" in unsupported.json()["detail"].lower()
    assert list(client.app.state.runtime.media_root.rglob("*")) == []


def test_provider_transcript_mode_captures_browser_session_without_external_call(
    client: TestClient, wav_bytes: bytes, dental_profile: dict[str, object]
) -> None:
    connected = client.post(
        "/api/provider-session",
        json={
            "provider": "gemini",
            "api_key": "provider-mode-test-key",
            "judge_model": "gemini-3.5-flash-lite",
            "transcription_model": "gemini-3.5-flash-lite",
            "free_tier_attested": True,
        },
    )
    assert connected.status_code == 201

    created = client.post(
        "/api/jobs",
        files={"audio": ("appointment.wav", wav_bytes, "audio/wav")},
        data={
            "profile_json": json.dumps(dental_profile),
            "transcript_mode": "provider",
        },
    )

    assert created.status_code == 201
    assert created.json()["status"] == "queued"
    internal = client.app.state.runtime.store.get_job(created.json()["id"])
    assert internal["provider_handle"]


def test_manual_mode_without_transcript_never_queues_connected_provider(
    client: TestClient, wav_bytes: bytes, dental_profile: dict[str, object]
) -> None:
    connected = client.post(
        "/api/provider-session",
        json={
            "provider": "gemini",
            "api_key": "manual-mode-test-key",
            "judge_model": "gemini-3.5-flash-lite",
            "transcription_model": "gemini-3.5-flash-lite",
            "free_tier_attested": True,
        },
    )
    assert connected.status_code == 201

    created = client.post(
        "/api/jobs",
        files={"audio": ("appointment.wav", wav_bytes, "audio/wav")},
        data={
            "profile_json": json.dumps(dental_profile),
            "transcript_mode": "manual",
        },
    )

    assert created.status_code == 201
    assert created.json()["status"] == "needs_transcript"
