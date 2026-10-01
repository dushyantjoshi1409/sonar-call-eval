# Persistence Voice Eval

A local FastAPI application for uploading a recorded call, reviewing its transcript and speaker roles, and producing four independent, evidence-linked findings. Scenario behavior comes from a validated profile, so the evaluator supports dental appointments, food-delivery feedback, generic calls, and custom workflows without business-specific rules in its core.

## What works

- WAV, MP3, and M4A upload with size, signature, duration, channel, ffprobe, and bounded decode checks
- SQLite-backed job state, restart recovery, idempotency conflicts, immutable run versions, retention, and local deletion
- Reviewed manual transcript import, role correction, native audio playback, and evidence seeking
- Separate PASS, FAIL, NOT_APPLICABLE, and UNKNOWN findings for semantic uptake, repetition, scenario flow, and response length
- Explicit nullable Yes/No values, proposed 0-2 quality grades/classifications, and finite numeric measurements with provenance
- Exact source segment and quote-offset validation, explicit coverage and unknowns, and no aggregate score
- Synthetic demo that is visibly labelled and never substitutes for uploaded audio
- Optional Gemini audio transcription and schema-constrained judging, restricted to reviewed free-tier model IDs
- JSON export containing the profile snapshot/hash, transcript revision, findings, provenance, and limitations

## Local setup

Requirements: Python 3.12+, FFmpeg with `ffmpeg` and `ffprobe`, and a loopback-only browser.

```bash
python3.12 -m venv .venv
. .venv/bin/activate
pip install -r requirements.lock
pip install -e . --no-deps
cp .env.example .env
uvicorn voice_eval.app:app --host 127.0.0.1 --port 8000
```

Open <http://127.0.0.1:8000>. Fixture/demo mode and reviewed transcript imports require no credentials or network.

## Free-only Gemini setup

Gemini is optional. The current reviewed default is `gemini-3.5-flash-lite`, whose official pricing page lists free-tier standard input/output and audio support. The application accepts up to 100 MiB for local/manual workflows but rejects Gemini inline audio over 70 MiB before any request, leaving room for base64 and prompt overhead under Google's 100 MB request guidance. Google documents model-dependent rate limits and says active limits must be checked in AI Studio.

1. Put `GEMINI_API_KEY` in this project's `.env`. Never paste the key into chat or commit it.
2. Confirm the key's project is actually eligible for the Gemini Developer API free tier in Google AI Studio.
3. Only then set `GEMINI_FREE_TIER_CONFIRMED=true`.

The model allowlist and flag prevent accidental unsupported configuration, but cannot override Google account billing. There is no paid fallback. HTTP 429 and ambiguous timeouts are explicit failures, and ambiguous submissions are not retried automatically.

Official sources: [pricing](https://ai.google.dev/gemini-api/docs/pricing), [billing tiers](https://ai.google.dev/gemini-api/docs/billing), [audio input](https://ai.google.dev/gemini-api/docs/generate-content/audio), [structured output](https://ai.google.dev/gemini-api/docs/structured-output), [rate limits](https://ai.google.dev/gemini-api/docs/rate-limits).

## Manual transcript format

Upload the real audio and paste an array of reviewed segments. `start` and `end` may be `null`; when present they must be nonnegative and ordered.

```json
[
  {
    "id": "seg-1",
    "speaker": "customer",
    "start": 0.0,
    "end": 3.2,
    "text": "I need a cleaning appointment next Tuesday.",
    "precision": "manual"
  }
]
```

Model timestamps and speaker boundaries are always stored as `model_estimated` and require human review. A spoken booking or “saved feedback” claim is never proof of a backend action.

## Development checks

```bash
.venv/bin/pytest -q
.venv/bin/ruff check .
.venv/bin/mypy voice_eval
```

See the interactive [architecture diagram](docs/architecture.html) and its [source specification](docs/architecture.json), plus [requirements](docs/requirements.md), [technical specification](docs/technical-spec.md), [rubric](docs/eval-rubric.md), [API and profile examples](docs/api-and-profiles.md), and [validation evidence](docs/validation.md).

## Privacy and limits

The server only permits loopback hosts and same-origin mutations. Original media is stored under random local IDs outside static files and expires after 24 hours by default. Local deletion cannot retract data already sent to an external provider. WER/CER requires a trusted, audio-matched human reference; the current UI reports that absence as UNKNOWN rather than comparing one ASR to another.
