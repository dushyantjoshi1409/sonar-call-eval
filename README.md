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
- Session-scoped Gemini, OpenAI, Groq, and custom OpenAI-compatible judging, with reviewed audio contracts only where supported
- Fixed synthetic regression suite with per-metric expectation outcomes and compatible baseline comparison
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

## Provider sessions

The upload page accepts a Gemini, OpenAI, Groq, or custom OpenAI-compatible key. The key is held only in process memory behind an opaque HttpOnly SameSite cookie, expires after one hour by default, and is removed by Clear or server restart. It is never written to SQLite, `.env`, exports, URLs, browser storage, or provider error messages. Saving a key means configured, not remotely verified.

- Gemini converts uploads to metadata-free 16 kHz mono PCM WAV before its inline-audio request. The adapter caps normalized audio at 14 MiB so base64 audio, prompts, and schemas remain below Gemini's documented 20 MB total inline-request limit.
- OpenAI uses Chat Completions structured output and multipart `/audio/transcriptions`; the reviewed default transcription contract is `whisper-1`, `verbose_json`, and a 25 MiB file limit.
- Groq uses its OpenAI-compatible Chat Completions endpoint plus its documented multipart transcription endpoint; the default transcription model is `whisper-large-v3-turbo` with a 25 MiB free-tier file limit.
- Custom endpoints must be public HTTPS OpenAI-compatible base URLs with no embedded auth, query, or fragment. They are deliberately chat-only, so audio requires a reviewed transcript import.

Gemini and Groq require an explicit free-tier eligibility attestation. OpenAI and custom services have unknown cost and require a separate session-only paid-use opt-in, off by default. There is no implicit provider or paid fallback. HTTP 400/422 invalid media or model settings, 401/403 authentication, 429 rate limits, redirects, timeouts, malformed output, and unsupported transcription remain distinct safe failures; upstream bodies are not exposed and ambiguous submissions are not retried.

The `.env` Gemini settings remain as a backward-compatible fallback when no browser session is selected. A selected session never borrows the environment key.

Choose the transcript source explicitly for each upload. `Import reviewed JSON` never queues automatic transcription, even when a provider session exists. `Use connected provider if audio-capable` requires a saved audio-capable session before the upload is accepted; disconnected and chat-only selections are blocked with setup guidance instead of silently creating a manual-transcript job.

Official contracts: [Gemini audio](https://ai.google.dev/gemini-api/docs/audio), [Gemini structured output](https://ai.google.dev/gemini-api/docs/structured-output), [OpenAI file transcription](https://developers.openai.com/api/docs/guides/speech-to-text), [OpenAI structured output](https://developers.openai.com/api/docs/guides/structured-outputs), [Groq OpenAI compatibility](https://console.groq.com/docs/openai), [Groq speech to text](https://console.groq.com/docs/speech-to-text), and [Groq structured output](https://console.groq.com/docs/structured-outputs).

## Synthetic regression checks

`/regression` runs six fixed authored transcript cases across dental, delivery, negation, justified and unnecessary repetition, and flow. It evaluates the selected provider/model with the same prompt, schema, and evidence validator as uploaded calls, then compares whether each explicit expectation was met. A correctly judged FAIL on a deliberately bad transcript is a met expectation; UNKNOWN and errors remain unresolved. Results persist without credentials and can be compared only against the same suite, prompt, and rubric versions.

This checks evaluator/provider/model behavior, not live voice-agent accuracy. Measuring a voice-agent prompt change requires new recordings or regenerated conversations, which is outside this feature. The fixed-suite and baseline idea was inspired by [AutoVoiceEvals](https://github.com/ArchishmanSengupta/autovoiceevals); this implementation is original and does not mutate agent prompts or call voice-platform APIs.

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

Model timestamps and speaker boundaries are always stored as `model_estimated` and require human review. Whisper-style output uses `unknown` speakers until the reviewer corrects roles and boundaries. A spoken booking or “saved feedback” claim is never proof of a backend action.

## Development checks

```bash
.venv/bin/pytest -q
.venv/bin/ruff check .
.venv/bin/mypy voice_eval
```

See the interactive [architecture diagram](docs/architecture.html) and its [source specification](docs/architecture.json), plus [requirements](docs/requirements.md), [technical specification](docs/technical-spec.md), [rubric](docs/eval-rubric.md), [API and profile examples](docs/api-and-profiles.md), and [validation evidence](docs/validation.md).

## Privacy and limits

The server only permits loopback hosts and same-origin mutations. Original media is stored under random local IDs outside static files and expires after 24 hours by default. Local deletion cannot retract data already sent to an external provider. WER/CER requires a trusted, audio-matched human reference; the current UI reports that absence as UNKNOWN rather than comparing one ASR to another.
