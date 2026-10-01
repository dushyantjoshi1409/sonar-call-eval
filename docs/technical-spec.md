# Technical specification

Version 1.1 | Codex | 2026-10-01 | Implemented local MVP contract

> Implementation update: provider-specific Sarvam/OpenAI sections below are retained as research provenance but are superseded. The implementation uses one optional Gemini Developer API adapter for inline audio transcription and schema-constrained judging, plus a credential-free manual transcript path and labelled synthetic fixture. Scenario profiles remove restaurant assumptions from the evaluator.

Scope, assumptions and acceptance are owned by [requirements.md](requirements.md); metric semantics by [eval-rubric.md](eval-rubric.md). This is a new local application and introduces no breaking changes to existing APIs or consumers. The implemented package, SQLite initialization, and local HTTP workflow are described below.

All numeric operational defaults below are **proposed**, except explicitly cited provider capabilities, status codes, formulas and version/identifier notation.

## Architecture and stack

Browser -> FastAPI -> SQLite job/store + private local files -> durable worker -> batch STT -> normalized segments -> speaker review -> deterministic metrics + schema-constrained judge -> validated immutable report -> browser/export. The [inline SVG overview](overview.html) labels the data and evidence paths.

| Module | Responsibility and interface |
|---|---|
| Web application | Python 3.12, FastAPI/Pydantic, Uvicorn; serve Jinja2 pages plus vanilla JavaScript and native audio playback. HTTP contracts below. One process, one Uvicorn worker |
| Recording intake | Stream upload, hash, probe/decode with FFmpeg/ffprobe via argument arrays, preserve original channels, create private paths and validated metadata |
| Job/store | Python stdlib SQLite, short explicit transactions, foreign keys, schema migrations, WAL on local disk; own state transitions, leases, deduplication and immutable revisions |
| Worker | Lifespan-managed asynchronous polling loop; claim a persisted job, checkpoint each external operation, resume from stored state. Never rely on a request-scoped background task as the queue |
| STT adapter | Optional Gemini inline-audio adapter plus manual transcript and labelled fixture paths. Timeouts are ambiguous submissions and are not blindly retried. Model timing and speaker boundaries require review. |
| Evaluation module | `evaluate(snapshot) -> report`; deterministic counts and WER alignment, optional narrow Gemini semantic prompts, schema/evidence validation, and no tool access. |
| Review/export | Evidence, mapping corrections, trusted-reference attestation, findings, missing-input badges and JSON download; suggestions do not change the live agent |

Use a Gemini `generateContent` request with response JSON schema, followed by independent Pydantic and source-evidence validation. The free-only configuration allowlists reviewed model IDs and requires the operator to confirm the project tier; application flags cannot override account billing. Pin resolved dependencies in `requirements.lock`. Python 3.12 is the supported baseline.

The adapter seams have real variation: provider-backed and fixture-backed execution. Avoid a generic orchestration framework or a provider marketplace. FFmpeg is a process dependency because safe metadata/decode checks and channel preservation are concrete requirements. JiWER supplies audited edit alignment rather than ad hoc string scoring. Pytest and Ruff are proposed test/lint tools; choose one Python type checker in the build.

## Intake and processing

1. Upload to a random private temporary filename outside static roots while enforcing the byte limit. Hash contents, check signature/MIME, ffprobe metadata and bounded decode. Reject remote URLs, playlists, archives, executable formats, corrupt data, zero duration and unsupported channel counts. Limits from NFR-01 apply before external submission. MIME checks alone do not establish safety or consent.
2. Preserve original bytes and sample/channel metadata. If stereo channels demonstrably separate participants, retain each channel and record mapping; stereo may instead contain duplicate/mixed audio, so do not assume left=agent. Default mixed/mono path uses diarization. Produce derived PCM WAV only when required; store conversion arguments, version and hash. Never destroy source evidence by downmixing the only copy.
3. Atomically rename validated media into a UUID directory; commit recording and job together. If DB commit fails, delete the unreferenced file. A startup sweeper removes stale orphan temporary files after checking live job references.
4. If Gemini is explicitly enabled, submit bounded inline audio to the allowlisted model and require schema-constrained segments. No provider call occurs from a key alone. A timeout is an ambiguous submission and is not blindly retried. Files over the inline limit require manual transcript import rather than a second provider stack. Never fetch a URL mentioned in a transcript.
5. Validate finite, nonnegative timestamps and `end >= start`; ensure spans fit decoded duration, carry explicit granularity, and do not silently clamp invalid output. Overlapping spans are valid evidence of overlap, not a sorting error. Missing or unreliable data sets quality flags. Normalize provider speaker IDs to stable local IDs, without claiming identity.
6. Present transcript/audio and a proposed role map. Confirm/correct roles or explicitly proceed with affected checks UNKNOWN. When timing chunks do not identify turns, do not derive precise per-turn duration. Group adjacent same-speaker chunks only when no intervening speaker is known; record the grouping rule and incomplete boundaries.
7. Snapshot all input revisions, configuration and hashes. Run deterministic metrics and the separate judge prompts. Validate schema, evidence references, quote spans and policy IDs before publishing. Persist report atomically and expose warnings distinctly from job failure.

## Job state machine

| State | Allowed transitions and meaning |
|---|---|
| NEEDS_TRANSCRIPT | Valid media is stored, but no reviewed transcript or configured Gemini path exists |
| NEEDS_CONFIGURATION | A key exists, but the operator has not confirmed the project is free-tier eligible |
| QUEUED | One persisted job waits for the local worker |
| TRANSCRIBING | Worker owns the synchronous inline Gemini request |
| REVIEW_READY | A versioned transcript exists and speaker/text review is available |
| COMPLETED | An immutable report version exists; corrections and reruns append revisions |
| FAILED | Provider, schema, ambiguous-submit, or internal worker failure with sanitized detail |
| DELETED | Immediate access tombstone after local media, transcript revisions, and reports are removed |

Upload validation failures can return directly before a job exists. Queue/decode validation is defense in depth. COMPLETED means processing completed, never that the call passed. A valid report can contain UNKNOWN metrics. Provider outage or invalid whole response is FAILED with earlier artifacts available for review, not a report of all passes. Fixture reports have a persistent `execution_mode=fixture` banner.

One in-process worker claims jobs through a short `BEGIN IMMEDIATE` transaction. Gemini `generateContent` is synchronous and returns no resumable provider handle. Therefore a process restart during TRANSCRIBING marks the job FAILED with an ambiguous-submit explanation instead of issuing a duplicate request. Late worker writes after deletion are rejected by the tombstone predicate. No distributed exactly-once guarantee is claimed.

## Retries and idempotency

Provider requests have a 120-second bound. HTTP 429 retains its typed rate-limit category, and a timeout is an ambiguous submission. Neither condition triggers an automatic provider retry or paid fallback. This conservative policy is bounded and duplicate-safe for the current synchronous API. The user can import a reviewed transcript instead.

The browser supplies `Idempotency-Key` for upload. The store binds it to a fingerprint over media, profile, transcript, reference, and attestation. Same key plus fingerprint returns the original response; the same key with different inputs returns 409. Rerunning evaluation appends a report version and never overwrites prior run history.

## HTTP API contract

Base `/api`, JSON except multipart/media; loopback only, same-origin UI, no public auth scheme in P0. Host is allowlisted and mutating requests with an Origin header must exactly match the request origin. No CORS middleware or remote bind is enabled.

| Method/path | Request | Response |
|---|---|---|
| POST `/jobs` | Multipart audio, profile JSON, and optional reviewed transcript/reference | 201 persisted job, 200 idempotent replay, 409 conflict, 422 invalid input, or 429 full queue |
| GET `/jobs/{id}` | None | Persisted status, sanitized media metadata, profile, transcript, and latest report |
| GET `/jobs/{id}/audio` | Range header allowed by the file response | Original local media; deleted jobs return 410 |
| PUT `/jobs/{id}/transcript` | Array of validated segments | New immutable transcript revision and REVIEW_READY state |
| POST `/jobs/{id}/evaluate` | None | New evidence-validated report version or explicit 409/503 failure |
| GET `/jobs/{id}/export` | None | JSON attachment with job, report, history, and provider-retention note |
| DELETE `/jobs/{id}` | None | Tombstone plus removal of local media/text/report history |
| POST `/metrics/wer` | Trusted reference and hypothesis | WER/CER observation or explicit UNKNOWN reason |

Errors use FastAPI's typed HTTP status plus a safe `detail` string; credentials and raw provider responses are never returned. Pydantic rejects extra behavioral fields. An initial upload may reach REVIEW_READY when a transcript is supplied, or NEEDS_TRANSCRIPT without credentials.

## Persistence model and output schema

| Table / files | Key fields and invariant |
|---|---|
| jobs | UUID, idempotency fingerprint, status/detail, private media path/metadata, profile snapshot/hash, current transcript/reference/report versions, fixture/provider metadata, timestamps, and deletion tombstone |
| transcript_revisions | Job ID, monotonically increasing revision, validated segment JSON, creation time |
| runs | Job ID, monotonically increasing version, validated report JSON, creation time |
| private media | `data/media/{uuid}/original.{ext}` outside the static tree, with the client filename retained only as display metadata |

Segments are objects `{id,speaker,start,end,text,precision}`. `speaker` is agent/customer/other/unknown; time fields are finite seconds and may be null only together; precision is manual/model_estimated/chunk/unknown. Source text is stored unchanged. Arbitrary framework logs must be converted explicitly rather than silently treated as a trusted transcript.

The report contract is:

- `schema_version`, `run_version`, evaluator identifier, profile snapshot/hash, and transcript revision.
- Four independent findings with `metric_id`, fixed verdict enum, concise rationale, typed value map, and exact source evidence.
- Evidence objects contain `segment_id`, quote, and half-open character offsets. The server verifies every quote against stored source text; timestamps come from the referenced stored segment in the UI.
- Coverage records transcript/timing/role/policy/reference/trace availability.
- Trusted-reference WER/CER contain observed value, substitution/deletion/insertion counts, denominator, and normalization version. Missing or unattested reference leaves them null and adds an explicit unknown.
- `unknowns`, persistent fixture flag, and `aggregate_score=null`.

UNKNOWN carries `reason_code=INSUFFICIENT_EVIDENCE` or a narrower reason such as MISSING_REFERENCE/ROLE_UNCONFIRMED. UNKNOWN and NOT_APPLICABLE require null value; PASS/FAIL require typed value and admissible evidence. Numeric measurements can be recorded without an acceptance threshold using UNKNOWN + reason `THRESHOLD_NOT_DEFINED`, with the raw measurement in a separate `observed_value` field. The UI displays the number without inventing success. JSON booleans and numeric zero must never share a falsy default.

## Security, retention and provenance

Transcripts, audio-derived text, supplied agent prompts and raw provider responses are data. Put the evaluator rubric in an immutable higher-priority instruction and serialize evaluated material as bounded structured fields. The judge has no tools, network fetches, files, secrets or arbitrary function execution. Require allowlisted metric/policy IDs; reject instruction-like additions, extra fields, unsupported quotes and nonexistent segment IDs. Escape output in HTML. Prompt instructions alone are not a security boundary, so test injection plus output validation. Redact unnecessary identifiers before judge submission where feasible; retain exact evidence offsets using an explicit redaction map rather than silently rewriting source.

Store secrets only in environment configuration in a later build, never exports/logs. No remote URL ingestion, arbitrary shell, public storage path or public server bind. Limit JSON lengths, transcript size and provider-result bytes as proposed bounded settings (initially 1 MiB text and 5 MiB JSON); an exceeded budget returns an explicit error, not silent truncation. These are application safeguards, not malware-proof claims. Local storage relies on the host's access controls/disk protection; no compliance certification or secure-erasure guarantee is made.

Retention defaults to 24 hours. Startup cleanup removes stale upload temporaries and sweeps expired live jobs. Deletion first writes a tombstone that denies reads and late worker updates, clears transcript/reference/report fields and history, then removes local media. SQLite pages, host backups, and user-downloaded exports may retain recoverable copies, so this is local application deletion rather than a secure-erasure claim. Third-party retention cannot be controlled after a provider request and is disclosed in the UI/export.

## Demo, observability and evolution

The repository provides a pinned lockfile, documented FFmpeg requirement, private writable `data/`, and a `uvicorn voice_eval.app:app --host 127.0.0.1 --port 8000` launch. Fixture/manual modes need no network. Real-provider mode requires an API key plus explicit free-tier confirmation. This task does not deploy or publish the app.

Log job/run ID, stage, attempt, duration, error category and redacted request ID. Keep evaluator processing duration separate from agent runtime latency. UI shows rate-limit/deadline errors and actionable retries. Rollback means stop the local app and restore the previous code/lockfile plus a schema-compatible clean fixture DB; do not overwrite real data without a backup/approval plan. No existing data migration is needed yet.

Alternatives: Streamlit would reduce UI code but complicate persistent jobs and precise browser evidence review; React adds a separate build without current benefit. Redis/Celery and Postgres/object storage become useful when concurrent processes, remote users or independent scaling are demonstrated needs. Keep the evaluation interface and migrate durable storage/worker ownership first. P1 trace adapters should import normalized evidence, not build LiveKit/Pipecat agents. See [build-plan.md](build-plan.md) for failure/recovery, end-to-end and calibration tests.
