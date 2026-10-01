# Validation evidence

Version 1.1 | 2026-10-01 IST

## Automated checks

Run from the repository root:

```bash
.venv/bin/pytest -q
.venv/bin/ruff check .
.venv/bin/mypy voice_eval
```

The 39-test suite covers the HTTP upload-review-evaluate-export-delete path, generic/dental/food/custom profiles, strict Boolean/grade/numeric output validation, missing policy and speaker mapping, exact evidence rejection, prompt-injection shaped input, WER boundaries, provider rate limits and ambiguous timeouts, restart recovery, idempotency conflicts, deletion rollback, failed-create cleanup, late-write prevention after deletion, and core media limits. A long-call regression verifies that evidence is capped at 20 excerpts while counts still cover all 25 matching turns.

Final exact command results are recorded in the completion report generated for this task. A passing mock/fixture test is not a live Gemini execution.

## Supplied MP3

The private sample at `/Users/dushyantjoshi/Downloads/Retell AI - Hyper Realistic AI Voice Agent - (320 Kbps).mp3` is never copied into Git. FFprobe 9.0.2 found one MP3 audio stream at 44.1 kHz stereo, one embedded PNG stream, 38.823764 seconds, and 2,483,123 total bytes. The bounded full decode passed with no FFmpeg errors.

Without a reviewed transcript or an eligible Gemini key, uploading this real recording must end in `needs_transcript`. This is expected and honest. No transcript facts, dental content, live model judgment, WER, booking success, or feedback persistence are claimed from that state.

## Browser acceptance

Chrome accepted the supplied MP3 through the actual file input with the dental preset and no transcript. The resulting persisted job displayed `needs_transcript`, the exact missing-key reason, 38.8 seconds, two channels, and no evaluation action. Native playback changed from play to pause and the media request returned HTTP 206.

The separate synthetic demo was visibly marked before and after evaluation. It produced four independent findings, strict Yes/No values, proposed grades/classifications, numeric measurements, explicit missing-context statements, versioned export/rerun controls, and evidence links that focused the matching turn and sought the player to 3.0 seconds. Export returned report schema `1.1`, four findings, and `aggregate_score=null`. At 1280px and an emulated 390x844 mobile viewport, document width equalled viewport width and the console had no errors.

## Architecture artifact

`docs/architecture.json` is the authored Archify source and `docs/architecture.html` is the generated standalone viewer. Final showcase validation passed 9/9 with zero composition errors or warnings. Automated browser evidence passed at 1440x900, 1600x1000, 1920x1080, and 2048x1320 with no overflow. Light and dark screenshots were inspected. The final diagram distinguishes background transcription, the human review gate, and the synchronous semantic judge call, while marking Gemini as remote and optional.

The artifact-bound receipts and screenshots are retained only in ignored local validation storage at `.artifacts/architecture-review/`; they are not application assets.

## Known limits

- Gemini execution is unverified until the user configures an eligible key and explicitly confirms free-tier posture.
- The deterministic evaluator is a conservative MVP aid, not a calibrated replacement for human review.
- In credential-free/manual mode, C1-C3 are UNKNOWN with labelled deterministic candidate signals. Only C4 and trusted-reference WER are asserted from deterministic measurements.
- Trusted-reference WER and Unicode-code-point CER are exposed in the upload UI, report, and public API; both remain UNKNOWN without reviewer attestation.
- In-process queue concurrency is one. This is intentional for a single-user local tool.
- Local deletion cannot control provider-side retention for content already submitted.
- Local/manual uploads allow 100 MiB; Gemini inline submission is rejected above 70 MiB before transport to stay below the documented 100 MB total-request boundary after encoding overhead.
