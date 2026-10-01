# Validation evidence

Version 1.2 | 2026-10-01 IST

## Automated checks

Run from the repository root:

```bash
.venv/bin/pytest -q
.venv/bin/ruff check .
.venv/bin/mypy voice_eval
```

The 62-test suite covers the existing upload-review-evaluate-export-delete path plus the provider and regression seams added in version 1.2. New contract tests use mock HTTP transports only. They verify Gemini media normalization, OpenAI-compatible chat and multipart transcription payloads, unknown speaker output, strict evidence validation, unsupported custom transcription, typed 400/401/429/timeout handling, secret-safe errors, custom endpoint rejection, credential isolation/expiry/clear/restart behavior, free-tier and paid-use gates, captured job credentials, no-key regression behavior, immutable scenario snapshots, persistence, compatible or rejected-incompatible baseline comparison, and distinct missing-transcript versus failed-transcription UI states.

Automated validation made no provider request. Passing mock tests are not evidence that a live Gemini, OpenAI, Groq, or custom account is configured or remotely verified.

## Browser acceptance

The preview ran at `http://127.0.0.1:8011` with ignored SQLite/media storage and no environment provider credential. Chrome verified:

- Provider switches for Gemini, OpenAI, Groq, and custom-compatible configuration.
- Session-only connect/clear behavior using a dummy Groq key. The UI labelled the session configured but not remotely verified, cleared the password field, and never exposed the key in a snapshot or screenshot.
- Cost controls: Gemini/Groq free-tier attestation is explicit; OpenAI/custom require session-only paid-use opt-in.
- A manual transcript workflow created through the local upload API with synthetic audio, then reviewed in Chrome. The reviewer changed a turn boundary from 3.0 to 2.8 seconds, saved revision 2, and ran the offline evaluator. C1-C3 remained UNKNOWN; deterministic response length passed. The browser automation upload helper was not used because it rejected its documented file-list argument.
- After the reported Gemini 400, the fixed preview restarted on port 8011 with the same ignored data paths and no environment credential. HTTP checks returned 200 for the root and a preserved failed job; session metadata returned disconnected. The failed job now renders `Automatic transcription failed` with reconnect/retry/import guidance. Chrome verified the state at desktop and 390 px with no horizontal overflow.
- Two user-initiated six-case regression runs. The first persisted as an offline baseline; the second selected that compatible baseline and showed semantic checks as unresolved and deterministic checks as unchanged.
- Desktop at 1280x900 and mobile at an emulated 390x844 viewport. Document width equalled viewport width with no horizontal overflow, and the console had no errors.

Browser checks did not submit content to any external provider.

The declared setuptools build backend produced `persistence_voice_eval-0.1.0-py3-none-any.whl`. Archive inspection confirmed the new provider/session/regression modules plus `templates/regression.html` and `static/app.css` are packaged.

## Architecture artifact

`docs/architecture.json` is the authored Archify source and `docs/architecture.html` is the generated standalone viewer. Final showcase validation passed 9/9 with zero errors or warnings. Automated visual checks passed at 1440x900, 1600x1000, 1920x1080, and 2048x1320 with no overflow. Light and dark renders were inspected after one text-density correction round.

Receipts:

- Specification SHA-256: `3d0211206dc32fb942db471b3b77a6fab4917d3a1352cf6a85b4e076ed037598`
- Artifact SHA-256: `ae1a3c3e5edcfc2ed38740184bc298b82e1f5e57bf507718d49356ac101b3185`
- Source/artifact sizes: 5,409 / 815,777 bytes

The diagram distinguishes the in-memory credential boundary, provider-specific transcription capabilities, shared judge contract, human review gate, and fixed regression suite. Visual-check sidecars are local receipts and are not application assets.

## Compatibility and known limits

- Live-key validation remains outstanding for every provider. A saved browser credential means configured, not remotely verified.
- Gemini audio is locally normalized to metadata-free 16 kHz mono PCM WAV and capped at 14 MiB before base64 encoding, leaving room under Gemini's documented 20 MB total inline-request limit. OpenAI and Groq transcription uses their multipart endpoint with a 25 MiB payload limit. Custom endpoints are intentionally chat-only.
- A user-initiated Gemini request returned HTTP 400 for an MP3 containing an attached image stream. Without a controlled provider replay of original and normalized bytes under the same session, causality remains unconfirmed. Normalization is a robustness improvement, and mock-contract tests verify the exact outbound WAV MIME and bytes. Safe diagnostics classify only allowlisted structured upstream status/reason codes; arbitrary messages and metadata stay hidden. The implementation worker did not access a key or initiate a live request, so a user-authorized retry remains outstanding.
- Transcription segments from OpenAI-compatible providers use unknown speakers and require review; the app does not claim diarization.
- Gemini/Groq free-tier eligibility is never inferred from key presence. OpenAI/custom services are not labelled free and require explicit paid-use opt-in.
- Session credentials live only in process memory, expire after one hour by default, and disappear on clear or restart. A provider request already in flight may finish after clear.
- Custom endpoints must be explicit HTTPS URLs without embedded authorization, query, or fragment and must resolve to public addresses. The destination is revalidated before requests, but this is still a local single-user safety boundary rather than a general-purpose outbound proxy.
- The regression suite evaluates provider/model/prompt/rubric behavior over fixed synthetic transcripts. It does not measure live-agent accuracy, mutate connected agents, or prove voice-agent changes.
- In credential-free/manual mode, semantic C1-C3 and semantic regression checks remain UNKNOWN. Only deterministic C4 and trusted-reference WER/CER are asserted when their inputs are available.
- In-process queue concurrency remains one. Local deletion cannot control provider-side retention for content already submitted.
