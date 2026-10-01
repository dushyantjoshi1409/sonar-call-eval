# Requirements

Version 1.1 | Codex | 2026-10-01 | Implemented local MVP

> Implementation update: this application evaluates multiple call scenarios through a validated, versioned scenario profile. Restaurant-specific wording below is historical research context only. Dental appointment, food-delivery, generic conversation, and custom profiles use the same core engine. Gemini replaces the earlier paid-provider proposal, and remains optional and free-tier gated.

## Purpose, actors and success

Enable an engineer/reviewer to upload a voice-call recording, configure the scenario outcome, inspect the evidence behind separate findings, correct speaker data and identify the next agent improvement. The assignment owner reviews the result; external STT/judge providers are optional processing actors. Success means a reproducible upload-to-evidence workflow that honestly reports missing evidence. This document owns scope, terms and acceptance criteria; [technical-spec.md](technical-spec.md) owns implementation and [eval-rubric.md](eval-rubric.md) owns metric definitions.

| Term | Canonical meaning |
|---|---|
| Recording | Original uploaded audio plus detected channel/codec metadata |
| Transcript | Versioned text segments with provenance; not automatically ground truth |
| Trusted reference | Human-reviewed transcript of the same audio with reviewer and normalization metadata |
| Live-agent transcript | What the running agent's STT produced, imported separately |
| Segment / turn | Provider timestamped span / grouped continuous contribution by a mapped speaker |
| Speaker map | Versioned assignment of voice/channel IDs to agent, customer, other or unknown |
| Evaluation run | Immutable configuration, input versions and findings for one recording |
| Finding | One metric verdict with typed value, evidence, uncertainty and rationale |
| Gate | Separate critical behavior rule; cannot be averaged away |
| WER / CER | Word / character error rate against a trusted reference |

## Scope and origin

**P0:** local upload, durable jobs, one STT integration, speaker review, four separate checks, optional policy/live transcript/reference import, WER/CER when eligible, evidence playback, review corrections, JSON export and deletion. Supplied needs are mapped in [assignment-notes.md](assignment-notes.md). Robustness and security controls below are task-brief requirements or proposed implementation safeguards.

**P1:** comparison across providers/runs, richer per-language analysis, trace import with runtime latency/tool evidence, improved alignment, charts across a larger labelled corpus. **Excluded from P0:** building the voice agent, telephony, TTS, streaming, simulated callers, enterprise auth, multitenancy, deployment or automatic edits to live prompts.

All numerical limits, targets, counts and time budgets in this document are **proposed engineering defaults**, unless explicitly called supplied or source-backed. Identifiers, dates, formulas and schema versions are not performance thresholds. No production service-level objective or accuracy promise is made.

## Assumptions and open inputs

| ID | Missing evidence / assumption | Safe build default | Consequence and owner |
|---|---|---|---|
| A-01 | Supplied call has no reviewed transcript | Validate the real media honestly through the no-key path and use visibly labelled authored fixtures for report behavior | Project owner supplies a reviewed transcript or eligible Gemini key; no call-content claim is made meanwhile |
| A-02 | Live transcript absent | `live_stt_error=UNKNOWN` | Project owner collects export; post-hoc ASR must not be called the agent's internal STT |
| A-03 | Agent prompt/business policy absent | Evaluate only the selected scenario profile; actual-policy compliance stays UNKNOWN | Project owner supplies policy; no booking, refund, redelivery, escalation, or persistence claim is inferred |
| A-04 | Channel format/roles unknown | Inspect channels; preserve original; suggest roles but require correction/confirmation | Reviewer maps speakers; otherwise role-dependent checks UNKNOWN |
| A-05 | Keys, permitted external processing and judge access absent | Providers disabled; fixture mode explicitly labelled | Project owner collects inputs; no paid calls in this stage |
| A-06 | Trusted reference/labels absent | WER/CER and calibration unavailable | Reviewer supplies audio-grounded references and labels |
| A-07 | Exact deadline absent | Finish build Thursday 2026-10-01 IST; submission Friday 2026-10-02 (dates inferred from today and supplied Friday deadline) | Project owner collects time; do not assume midnight |
| A-08 | Last handwritten requirement says “should be un-naturally long” | Interpret as should not, mark proposed correction | Retain literal original until confirmed; configurable rubric |

These are evidence requests already being collected in chat, not new human product-choice gates. No open captain decision is introduced by this specification.

## Functional requirements and acceptance

| ID | Priority / origin | Requirement | Acceptance criterion |
|---|---|---|---|
| FR-01 | P0 supplied + proposed limits | Accept a local WAV, MP3 or M4A recording with visible validation | Valid fixture creates durable recording/job IDs; malformed/oversized/unsupported input is rejected before provider submission; client filename never controls storage path |
| FR-02 | P0 supplied + brief | Import optional live transcript, trusted reference, policy and speaker/channel metadata as distinct versioned artifacts | Missing artifact remains absent, never fabricated; schema errors name field; importing a plain transcript does not grant trusted-reference status |
| FR-03 | P0 supplied | Transcribe Hinglish with speaker/timestamp provenance | Store original script, raw response and model/mode; display chunk/word/manual precision; absent timestamps remain null |
| FR-04 | P0 brief | Show queued/running/review/failed/completed processing state and stage errors | Reload preserves state; restart resumes safely; provider failure is never a successful empty evaluation |
| FR-05 | P0 brief | Allow reviewer to correct roles and transcript/reference segments | Save new revision with author/source; preserve original; new run uses revised inputs; ambiguous role yields UNKNOWN |
| FR-06 | P0 supplied | Produce C1 listening, C2 repetition, C3 flow/capture and C4 length as separate checks | Each has state, applicable typed value, evidence and limits per rubric; no aggregate score; unknown/null not coerced to pass/zero |
| FR-07 | P0 supplied | Compute WER/CER only against eligible reference and compare semantic entity/negation errors separately | Show edit counts, denominator, normalization version and target transcript; no reference produces UNKNOWN; ASR-to-ASR disagreement labelled proxy |
| FR-08 | P0 supplied + latest generic scope | Evaluate workflow and information capture against the immutable selected profile | Dental, food-delivery, generic, and custom profiles use the same engine; missing policy means compliance UNKNOWN; no backend action is claimed without a trace |
| FR-09 | P0 supplied + brief | Review audio-linked findings and export results | Evidence IDs and exact snippets resolve to segment/time spans; click seeks when timing exists; export includes gaps, provenance and recommendations labelled hypotheses |
| FR-10 | P0 brief | Support idempotent submission, correction and rerun history | Same key and payload returns original job; changed payload conflicts; rerun creates new run without overwriting original |
| FR-11 | P0 brief | Delete sensitive local artifacts and stop new processing | Deletion prevents new reads/late writes; all dependent audio/text/results and temp files removed; deletion status reports external-retention limits |
| FR-12 | P0 brief | Treat transcripts and provider output as untrusted data | Injection fixture cannot change rubric, enable tools, leak environment or introduce arbitrary HTML; invalid judge evidence rejected |
| FR-13 | P1 brief | Import correlated LiveKit/Pipecat traces | Runtime metrics only populated where trace identity, definitions, clocks and spans support them; no inferred tool success |

## Nonfunctional targets

| ID | Priority | Proposed measurable target | Verification |
|---|---|---|---|
| NFR-01 | P0 | Maximum upload 100 MiB, 20 minutes, 1 or 2 channels; bounded decode 60 seconds | Boundary fixtures, misleading extensions and damaged media; these are application limits, not provider limits |
| NFR-02 | P0 | One active processing job; bounded queue 20 pending; local accepted-upload acknowledgement within 2 seconds after transfer in fixture tests | Timed local checks; reject queue overflow with retryable error; no end-to-end provider speed guarantee |
| NFR-03 | P0 | Proposed 15-minute external stage deadline; maximum 3 attempts for retry-safe transient operations; worker restart recovery within 60 seconds | Fault-injection test; duplicate submission ambiguity requires review, not blind retry |
| NFR-04 | P0 | No secret or raw audio/transcript in ordinary logs; loopback-only server; no arbitrary URL ingestion or remote publish | Inspect logs/network/config with injection fixtures; local browser origin checks |
| NFR-05 | P0 | Every timestamp has origin/precision; every determinate semantic finding has valid evidence; no loss of original script | Schema and evidence validator; Hindi-English mixed-text and entity/negation fixtures |
| NFR-06 | P0 | Retain sensitive artifacts at most 24 hours locally by default; deletion completes within 60 seconds while app is running, overdue cleanup on restart | Verify audio, derived files, DB rows, exports managed by app and temp directories; external/user-made copies excluded and disclosed |
| NFR-07 | P0 | Every run records input/config hashes, artifact revisions, code/dependency/model/prompt/rubric/normalization versions | Export contract tests; deterministic calculations repeat exactly for fixed inputs; stochastic provider output need not |
| NFR-08 | P0 | Keyboard-operable upload, speaker editing, evidence playback and export; legible at 390px and 1280px widths | Browser end-to-end and visual inspection; no color-only statuses |
| NFR-09 | P0 | Zero unreviewed critical-gate false passes on the small labelled acceptance fixtures | Human comparison with disagreements documented; this is a fixture release gate, not estimated production reliability |
| NFR-10 | P0 | Fixture-mode demo runs without credentials or network; external calls explicitly enabled only after inputs arrive | Offline end-to-end run; fixture output permanently marked synthetic/demo |

## Acceptance, risk and readiness

AC-01: FR-01 through FR-12 and NFR P0 targets pass relevant [build-plan fixtures](build-plan.md), with recorded results and any exceptions. AC-02: display the four checks and uncertainties for positive, negative and not-delivered calls. AC-03: no unsupported STT attribution, stored-feedback assertion or latency claim. AC-04: document remaining real-provider and human-calibration gaps explicitly in the submission.

Highest risks are missing real inputs, diarization/role mistakes and evaluator hallucinations. Mitigate with fixture-first development, role confirmation, validated evidence and reviewer calibration. Provider timing/cost and local file retention are integration risks managed by bounded execution and cleanup. Finish P0 before any P1 work. The report is complete when specifications and references are validated; the product is complete only after the build and checks actually run.
