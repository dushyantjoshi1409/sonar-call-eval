# Bounded research and recommended approach

Version 1.0 | Access date for every source: **2026-10-01** | Codex

> Historical provider research: the implementation uses the Gemini Developer API under the free-only constraints documented in the root README. Sarvam/OpenAI comparisons below are preserved only as provenance and are not configured application services.

One bounded research pass used the originals and official product/API documentation. A Codex research subagent collected STT references; the author independently opened and checked those sources, read all original supplied files and inspected the public website. No provider request, audio test, benchmark, production inspection, or sales contact occurred.

## Company context and visual provenance

Persistence publicly presents a business voice-agent platform with agent building/testing, deployment, integrations, call monitoring and analytics/transcripts, and lists Restaurants & Food Delivery among its industries. This supports the relevance of post-call evaluation, not a claim about its private system. Public marketing latency/accuracy/availability figures have no reviewed benchmark methodology here and are not assignment targets. No inference is made about Persistence's internal use of LiveKit, Pipecat or any model vendor. [S01](https://persistence.dev/)

The visual spec follows design source 2, Persistence's observed public style: pale blue-white page background `rgb(241,243,252)`, charcoal text `rgb(27,28,37)`, Helvetica/Arial, generous whitespace and rounded/pill controls. These were read with Chrome computed styles on 2026-10-01; [the screenshot](../references/persistence-home.png) records the rotating photographic hero. The overview adapts those surfaces to an engineering document, uses a restrained purple accent, and invents no company logo or private dashboard. It embeds no remote assets. Dark colors are an accessibility adaptation, not claimed company tokens.

## Batch STT choice

| Candidate | Supported evidence from official docs | Decision and remaining uncertainty |
|---|---|---|
| **Sarvam Saaras v4 batch** | Hindi-English `codemix`, diarization and chunk start/end timestamps; `verbatim` is a separate mode | Proposed first adapter for domain fit and direct file-job workflow. Chunk precision limits timing; codemix filler/repetition fidelity and restaurant-call accuracy need a real fixture. Keep raw output; do not translate before grading. [S02](https://docs.sarvam.ai/api/api-guides-tutorials/speech-to-text/batch-api) |
| **Google Cloud Speech V2 Chirp 3** | Hindi `hi-IN` and English India `en-IN`; batch diarization is documented; batch uses Cloud Storage | Credible alternative with extra cloud setup. Language availability alone does not prove within-turn Hinglish fidelity. Current page inconsistently places optional word timestamps under an unsupported-features heading and differs on diarization methods. Verify region, batch method and combined features before selecting. Confidence is explicitly not a true word-confidence score. [S04](https://docs.cloud.google.com/speech-to-text/docs/models/chirp-3) |
| **Deepgram Nova-3 multilingual** | Prerecorded `language=multi`; Hindi and English included; Nova batch diarization provides word start/end and speaker fields | Preferred timing-rich alternative if Sarvam evidence proves insufficient. Pin `diarize_model=v2` when testing batch; current docs deprecate `diarize=true`. No Hinglish accuracy ranking is established. [S06a](https://developers.deepgram.com/docs/multilingual-code-switching), [S06b](https://developers.deepgram.com/docs/models-languages-overview), [S07](https://developers.deepgram.com/docs/diarization) |

Diarization groups voices; it does not identify restaurant agent versus customer. Keep channel metadata, permit manual mapping and preserve uncertainty. Do not silently switch providers on failure: that changes the measurement instrument and can resend sensitive data.

## Current price and limit snapshots

These are **source-backed snapshots**, not quotes or spend authorization. Recheck account plan, taxes, model eligibility, channels and regional availability at integration. Costs exclude judge usage, storage and network. No free-credit assumption is needed.

| Provider | Published price checked | Published limits checked / unverified |
|---|---|---|
| Sarvam | INR 30/hour STT, INR 45/hour with diarization; billed per second. [S03a](https://docs.sarvam.ai/api/getting-started/pricing) | Batch up to 2 hours/file, 20 files/job; timestamps chunk-only. [S02](https://docs.sarvam.ai/api/api-guides-tutorials/speech-to-text/batch-api) Starter batch 20 requests/minute, account-wide; actual account tier unknown. [S03b](https://docs.sarvam.ai/api/getting-started/ratelimits) |
| Google | V2 standard first tier USD 0.016/minute; dynamic batch USD 0.003/minute. [S05](https://cloud.google.com/speech-to-text/pricing) | Exact Chirp 3 SKU eligibility/turnaround and region configuration unverified. Do not use generic batch limits to override the model-specific documentation conflicts. |
| Deepgram | Nova-3 prerecorded multilingual PAYG USD 0.0052/minute; prerecorded diarization included on the pricing page. [S08](https://deepgram.com/pricing) | Account rate/concurrency and maximum file limits not established in this pass. Do not copy streaming promotional rates into a batch estimate. |

## Evaluation method and evidence boundaries

Use deterministic reference alignment for WER/CER and deterministic counting for length, alongside separately calibrated semantic judges. JiWER supports reference/hypothesis edit-distance metrics and alignments. Normalization must be fixed and versioned; Hinglish spelling/script variants require a declared convention. Two ASRs can share mistakes and are never each other's ground truth. [S09](https://jitsi.github.io/jiwer/usage/)

Use narrow pass/fail or anchored ordinal prompts with evidence validation and human review. OpenAI's evaluation guidance recommends task-specific evaluation, calibration against human feedback, and warns of judge position/verbosity bias. This informs the method, not a production accuracy claim. Use an ordinary judge request through a configured provider adapter; no hosted evaluation platform is needed. [S10](https://developers.openai.com/api/docs/guides/evaluation-best-practices)

Proposed evidence discipline: keep entities (dish, quantity, temperature, delivery status), scoped negation, caller corrections and original wording. “Khana garam nahi tha” and “khana garam tha” are operationally different despite a small edit count. A mismatch between caller and reply is an observable listening proxy; attributing its cause to the agent's STT requires the actual live-agent STT transcript aligned to trusted audio. A post-hoc transcript only measures the evaluator's ASR. Verbal acknowledgement is not proof that feedback was stored.

Timestamp gaps are observed intervals between estimated speech segments, with overlap and alignment uncertainty. They cannot isolate runtime STT, LLM or TTS latency. Later, import correlated traces: LiveKit currently exposes per-plugin metrics, per-turn `ChatMessage.metrics` and session reports; a session-level metrics event is deprecated. Null fields remain unavailable. [S11](https://docs.livekit.io/testing/observability/data/)

Pipecat documents service timing metrics and OpenTelemetry tracing/turn tracking. Exported spans need session/turn IDs, event definitions, clock basis and SDK versions; not every service reports every metric. Do not sum overlapping streaming spans to manufacture end-to-end latency. [S12a](https://docs.pipecat.ai/pipecat/fundamentals/metrics), [S12b](https://docs.pipecat.ai/api-reference/server/utilities/opentelemetry)

## Recommendation and alternatives

Build a local Python application with a durable SQLite queue and a simple browser review page. Sarvam is the first real STT adapter; a fixture adapter makes development possible without keys. Use a configured OpenAI judge with schema-constrained output, while deterministic code computes alignment and counts. Record requested and returned model identifiers; the exact accessible judge snapshot must be selected and recorded when credentials are provided. No model-quality claim is made by choosing this integration.

Reject distributed queues, a separate frontend build, object storage and live telephony for P0 because they do not resolve a current requirement. Deepgram is a later evidence-driven alternative for word timing; Google is reasonable when an existing GCP project and feature verification remove setup uncertainty. A fully local ASR/judge avoids data transfer but adds model-download/hardware and Hinglish validation work; do not pretend that fallback is ready today.

## Source register

The twelve source groups above cite 15 official pages, including narrow companion pricing/feature pages. The extra companion pages verify rate limits, language inclusion and tracing details; this remains a bounded comparison of three STT options. S01 company; S02 batch contract; S03 pricing/rate limits; S04 Google capabilities; S05 Google pricing; S06 Deepgram languages/codeswitching; S07 speaker output; S08 Deepgram pricing; S09 alignment; S10 judge method; S11 LiveKit evidence; S12 Pipecat evidence. Every URL was opened on the access date. Dynamic documentation may change after this snapshot. Original assignment and guide sources are indexed separately in [references](../references/README.md).

Unverified: real Hinglish accuracy, diarization/turn-boundary accuracy, consent and provider retention terms for actual calls, actual account quotas, judge model access/calibration, business policy, recording format, internal agent transcript/traces and exact deadline. These are bounded limitations with defaults in [requirements.md](requirements.md), not blockers to writing the plan.
