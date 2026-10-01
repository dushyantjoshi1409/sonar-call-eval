# API and scenario profiles

## HTTP workflow

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/jobs` | Upload media plus profile and optional reviewed transcript |
| `GET` | `/api/jobs/{id}` | Read persisted status, transcript, and report |
| `GET` | `/api/jobs/{id}/audio` | Stream the locally stored source recording |
| `PUT` | `/api/jobs/{id}/transcript` | Save a new transcript/role revision |
| `POST` | `/api/jobs/{id}/evaluate` | Create an immutable report version |
| `GET` | `/api/jobs/{id}/export` | Download the complete JSON export |
| `DELETE` | `/api/jobs/{id}` | Tombstone the job and remove local media/text/results |
| `POST` | `/api/metrics/wer` | Observe WER/CER only from an explicitly trusted reference |

`POST /api/jobs` is multipart form data with `audio`, `profile_json`, optional `transcript_json`, optional `trusted_reference`, and `reference_attested`. Supply `Idempotency-Key`; the same key and payload returns the existing job, while changed inputs return HTTP 409. A reference affects WER only when the reviewer attests that it matches the same audio.

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

Every finding has one of `PASS`, `FAIL`, `NOT_APPLICABLE`, or `UNKNOWN`, plus a rationale, typed values, and zero or more evidence objects. Evidence contains `segment_id`, an exact `quote`, and `[start_char, end_char)` offsets. The report is rejected if the quote does not exactly resolve in the stored transcript. Findings remain separate and `aggregate_score` is always null.
