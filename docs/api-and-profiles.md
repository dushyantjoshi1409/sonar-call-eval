# API and scenario profiles

## HTTP workflow

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/provider-session` | Read nonsecret session provider metadata |
| `POST` | `/api/provider-session` | Store one provider key in expiring server memory |
| `DELETE` | `/api/provider-session` | Clear future access to the current session credential |
| `POST` | `/api/jobs` | Upload media plus profile and optional reviewed transcript |
| `GET` | `/api/jobs/{id}` | Read persisted status, transcript, and report |
| `GET` | `/api/jobs/{id}/audio` | Stream the locally stored source recording |
| `PUT` | `/api/jobs/{id}/transcript` | Save a new transcript/role revision |
| `POST` | `/api/jobs/{id}/evaluate` | Create an immutable report version |
| `GET` | `/api/jobs/{id}/export` | Download the complete JSON export |
| `DELETE` | `/api/jobs/{id}` | Tombstone the job and remove local media/text/results |
| `POST` | `/api/metrics/wer` | Observe WER/CER only from an explicitly trusted reference |
| `GET` | `/api/regression-runs` | List recent synthetic fixed-suite results |
| `POST` | `/api/regression-runs` | Run the fixed suite with an optional compatible baseline |

`POST /api/jobs` is multipart form data with `audio`, `profile_json`, optional `transcript_json`, optional `trusted_reference`, and `reference_attested`. Supply `Idempotency-Key`; the same key and payload returns the existing job, while changed inputs return HTTP 409. A reference affects WER only when the reviewer attests that it matches the same audio.

`POST /api/provider-session` accepts `provider`, `api_key`, `judge_model`, optional `transcription_model` and `base_url`, plus `free_tier_attested` and `allow_paid_use`. The response never contains the key or credential handle. The cookie selects one isolated in-memory credential; jobs capture an internal opaque handle so later session changes cannot switch an in-flight job to another key. Clear, expiry, or restart makes future use fail with a reconnect instruction. An already submitted synchronous request may still finish.

Custom base URLs must use HTTPS, contain no userinfo/query/fragment, and resolve only to public IP addresses. Custom is chat-only. Gemini, OpenAI, and Groq have distinct reviewed audio payloads rather than one assumed compatibility contract. Gemini input is normalized locally to 16 kHz mono PCM WAV and capped at 14 MiB before base64 encoding so the complete inline request remains below the documented 20 MB limit.

Regression results distinguish the call `actual` verdict from the expectation `outcome`: `met`, `mismatched`, `unresolved`, or `error`. Baseline `comparison` is `improved`, `newly_failing`, `unchanged`, or `unresolved`. Suite, prompt, and rubric versions must match. No aggregate is produced.

## Profile schema 1.0

```json
{
  "schema_version": "1.0",
  "id": "insurance-renewal",
  "name": "Insurance renewal",
  "task_description": "Discuss a policy renewal request.",
  "expected_outcome": "Capture renewal intent and a truthful next step.",
  "required_information": ["renewal intent"],
  "policies": [],
  "custom_criteria": ["Do not invent a premium or completed payment."]
}
```

Unknown keys are rejected. The exact canonical profile is hashed with SHA-256 and copied into each report. Profile and transcript content are untrusted data and cannot enable tools or override evaluator instructions.

## Finding contract

Every schema `1.1` finding has one of `PASS`, `FAIL`, `NOT_APPLICABLE`, or `UNKNOWN`, plus a rationale, explicit typed outputs, and zero or more evidence objects. Evidence contains `segment_id`, an exact `quote`, and `[start_char, end_char)` offsets. The report is rejected if the quote does not exactly resolve in the stored transcript. Findings remain separate and `aggregate_score` is always null.

```json
{
  "metric_id": "unnecessary_repetition",
  "verdict": "FAIL",
  "rationale": "An identical agent turn appears more than once.",
  "evidence": [
    {"segment_id": "agent-2", "quote": "Could you confirm that?", "start_char": 0, "end_char": 23}
  ],
  "boolean_result": {
    "name": "unnecessary_repetition",
    "value": true,
    "pass_when": false,
    "measurement_kind": "schema_judge"
  },
  "grade_result": {
    "scale": "proposed-quality-v1",
    "value": 0,
    "classification": "NEEDS_IMPROVEMENT",
    "measurement_kind": "schema_judge"
  },
  "measurements": [
    {"name": "exact_repeated_turns", "value": 3, "unit": "count", "measurement_kind": "deterministic"}
  ],
  "candidate_verdict": null,
  "value": {}
}
```

Boolean values are strict JSON booleans, not `0`, `1`, or strings. Null means unknown, while `false` remains an observed No. Grade values are strict integers on the proposed 0-2 quality scale: 0 `NEEDS_IMPROVEMENT`, 1 `PARTIAL`, and 2 `MEETS_EXPECTATIONS`. Numeric measurements must be finite and carry a unit plus provenance. UNKNOWN and NOT_APPLICABLE force Boolean and grade values to null.

`evidence` is capped at 20 exact excerpts per finding. When more turns match, the rationale identifies the list as a sample and full counts remain in `measurements`; source transcript segments are not discarded. Stored schema `1.0` reports remain readable through the legacy `value` field, while new runs write schema `1.1`.
