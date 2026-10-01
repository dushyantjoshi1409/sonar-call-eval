from __future__ import annotations

import json

from fastapi.testclient import TestClient


def test_manual_transcript_upload_review_evaluate_export_and_delete(
    client: TestClient,
    wav_bytes: bytes,
    dental_profile: dict[str, object],
    transcript_json: str,
) -> None:
    response = client.post(
        "/api/jobs",
        files={"audio": ("appointment.wav", wav_bytes, "audio/wav")},
        data={
            "profile_json": json.dumps(dental_profile),
            "transcript_json": transcript_json,
            "trusted_reference": (
                "I need a cleaning appointment next Tuesday. "
                "I can help with a cleaning appointment next Tuesday."
            ),
            "reference_attested": "true",
        },
        headers={"Idempotency-Key": "dental-1"},
    )
    assert response.status_code == 201
    job = response.json()
    assert job["status"] == "review_ready"
    assert job["profile"]["id"] == "dental-appointment"

    duplicate = client.post(
        "/api/jobs",
        files={"audio": ("appointment.wav", wav_bytes, "audio/wav")},
        data={
            "profile_json": json.dumps(dental_profile),
            "transcript_json": transcript_json,
            "trusted_reference": (
                "I need a cleaning appointment next Tuesday. "
                "I can help with a cleaning appointment next Tuesday."
            ),
            "reference_attested": "true",
        },
        headers={"Idempotency-Key": "dental-1"},
    )
    assert duplicate.status_code == 200
    assert duplicate.json()["id"] == job["id"]

    revised = client.put(f"/api/jobs/{job['id']}/transcript", json=json.loads(transcript_json))
    assert revised.status_code == 200
    assert revised.json()["transcript_revision"] == 2

    evaluated = client.post(f"/api/jobs/{job['id']}/evaluate")
    assert evaluated.status_code == 200
    report = evaluated.json()["report"]
    assert report["profile_snapshot"]["hash"]
    assert {finding["metric_id"] for finding in report["findings"]} == {
        "semantic_uptake",
        "unnecessary_repetition",
        "scenario_flow",
        "response_length",
    }
    assert report["aggregate_score"] is None
    assert report["unknowns"]
    assert report["wer"]["value"] == 0
    assert report["cer"]["value"] == 0
    assert report["coverage"]["trusted_reference_supplied"] is True
    assert all(
        finding["verdict"] == "UNKNOWN"
        for finding in report["findings"]
        if finding["metric_id"] != "response_length"
    )

    rerun = client.post(f"/api/jobs/{job['id']}/evaluate")
    assert rerun.status_code == 200
    assert rerun.json()["report"]["run_version"] == 2

    exported = client.get(f"/api/jobs/{job['id']}/export")
    assert exported.status_code == 200
    assert exported.json()["report"]["run_version"] == 2
    assert [run["version"] for run in exported.json()["history"]["runs"]] == [1, 2]
    assert [
        revision["revision"] for revision in exported.json()["history"]["transcript_revisions"]
    ] == [1, 2]

    deleted = client.delete(f"/api/jobs/{job['id']}")
    assert deleted.status_code == 200
    assert client.get(f"/api/jobs/{job['id']}").status_code == 410


def test_same_idempotency_key_with_changed_payload_conflicts(
    client: TestClient,
    wav_bytes: bytes,
    dental_profile: dict[str, object],
    transcript_json: str,
) -> None:
    request = {
        "files": {"audio": ("appointment.wav", wav_bytes, "audio/wav")},
        "headers": {"Idempotency-Key": "same-key"},
    }
    first = client.post(
        "/api/jobs",
        data={"profile_json": json.dumps(dental_profile), "transcript_json": transcript_json},
        **request,
    )
    assert first.status_code == 201

    changed = dict(dental_profile)
    changed["expected_outcome"] = "A materially different outcome."
    second = client.post(
        "/api/jobs",
        data={"profile_json": json.dumps(changed), "transcript_json": transcript_json},
        **request,
    )
    assert second.status_code == 409

    assert client.delete(f"/api/jobs/{first.json()['id']}").status_code == 200
    deleted_replay = client.post(
        "/api/jobs",
        data={
            "profile_json": json.dumps(dental_profile),
            "transcript_json": transcript_json,
        },
        **request,
    )
    assert deleted_replay.status_code == 410


def test_real_audio_without_transcript_or_key_needs_transcript(
    client: TestClient, wav_bytes: bytes, dental_profile: dict[str, object]
) -> None:
    response = client.post(
        "/api/jobs",
        files={"audio": ("appointment.wav", wav_bytes, "audio/wav")},
        data={"profile_json": json.dumps(dental_profile)},
    )
    assert response.status_code == 201
    assert response.json()["status"] == "needs_transcript"
    assert response.json()["status_detail"] == "GEMINI_API_KEY is not configured"


def test_manual_transcript_cannot_exceed_audio_duration(
    client: TestClient, wav_bytes: bytes, dental_profile: dict[str, object]
) -> None:
    transcript = json.dumps(
        [
            {
                "id": "late",
                "speaker": "agent",
                "start": 7.0,
                "end": 12.0,
                "text": "This timestamp is outside the recording.",
                "precision": "manual",
            }
        ]
    )
    response = client.post(
        "/api/jobs",
        files={"audio": ("appointment.wav", wav_bytes, "audio/wav")},
        data={"profile_json": json.dumps(dental_profile), "transcript_json": transcript},
    )
    assert response.status_code == 422
    assert "timestamps exceed" in response.json()["detail"]


def test_public_wer_interface_requires_trusted_reference(client: TestClient) -> None:
    missing = client.post(
        "/api/metrics/wer", json={"trusted_reference": None, "hypothesis": "order mila"}
    )
    assert missing.json() == {
        "status": "UNKNOWN",
        "reason": "MISSING_REFERENCE",
        "wer": None,
        "cer": None,
    }
    missing_hypothesis = client.post(
        "/api/metrics/wer", json={"trusted_reference": "order mila", "hypothesis": None}
    )
    assert missing_hypothesis.json()["reason"] == "MISSING_HYPOTHESIS"
    observed = client.post(
        "/api/metrics/wer",
        json={"trusted_reference": "order nahi mila", "hypothesis": "order mila"},
    )
    assert observed.json()["status"] == "OBSERVED"
    assert observed.json()["wer"]["deletions"] == 1
    assert observed.json()["cer"]["value"] > 0


def test_same_origin_guards_and_html_escaping(
    client: TestClient,
    wav_bytes: bytes,
    dental_profile: dict[str, object],
) -> None:
    blocked = client.post("/api/demo", headers={"Origin": "http://localhost.evil"})
    assert blocked.status_code == 403
    assert client.get("/", headers={"Host": "example.com"}).status_code == 400

    transcript = json.dumps(
        [
            {
                "id": "unsafe",
                "speaker": "customer",
                "start": 0,
                "end": 1,
                "text": "<script>alert('x')</script>",
                "precision": "manual",
            },
            {
                "id": "safe",
                "speaker": "agent",
                "start": 1,
                "end": 2,
                "text": "I will treat that as transcript data.",
                "precision": "manual",
            },
        ]
    )
    created = client.post(
        "/api/jobs",
        files={"audio": ("call.wav", wav_bytes, "audio/wav")},
        data={"profile_json": json.dumps(dental_profile), "transcript_json": transcript},
    )
    page = client.get(f"/jobs/{created.json()['id']}")
    assert "<script>alert('x')</script>" not in page.text
    assert "&lt;script&gt;alert" in page.text
