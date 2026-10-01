# Assignment notes and traceability

Version 1.0 | Codex | 2026-10-01 | Proposed interpretation for implementation

Source labels refer to the [unaltered local originals](../references/README.md). Photo order here follows the supplied filenames, not the conceptual sequence. The photographs are notes, not a complete business policy. Quoted excerpts preserve spelling where legible; interpretation is separated below.

## P1: platform, input and evaluation notes

Top: "Voice Platform"; "livekit -> open source voice orchestration platform" and "pipecat ->" under a bracket. Then "STT, TTS, LLM"; "india -> sarvam" and "google" with ticks; "TTS -> cartesia, eleven labs". These are candidate references, not stack mandates.

Middle: "Hinglish customers"; a "call recording" box points into "system". A note above the system reads "transcript from" followed by cramped right-edge writing that appears to mean LiveKit; that last word is uncertain. The brief likewise treats a LiveKit transcript as possible, not provided.

Bottom: "1 Hinglish conversation - score" with a tick; "2 WER" circled; "3 agent description -> instruction following" with a tick. No specific score formula, scale, threshold, reference transcript or instruction set is supplied.

## P3: MVP failures and restaurant flow

Under "MVP":

1. "agent did not listen correctly."
2. "agent responses sounded scripted (repetitive response)".
3. "agent jumped from conversation flows (did the agent took feedback correctly.)".

Then: "Agent", "Restaurant", "agent -> post order feedback". Flow begins "did you receive order", with Y and N branches. The Y side leads to "How was" and +ve / -ve branches. The positive continuation reads "glad, do you" and is incomplete at the lower edge. The negative continuation reads "what was wrong". The N branch has empty parentheses; no not-delivered action is specified.

Interpretation: evaluate receipt confirmation, relevant feedback collection and context-appropriate follow-up. The brief clarifies this is a post-delivery food-feedback recording. Proposed not-delivered behavior is to acknowledge non-delivery and avoid asking for a food rating; operational remediation requires the missing policy. Do not invent refund, redelivery or escalation entitlements.

## P2: fourth failure, output forms and goals

Top, numbered 4: **"Per conversation turn, response should be un-naturally long."** That is the literal wording. Interpreting this as **should NOT be unnaturally long** is a proposed correction, supported by its placement among failure checks and the brief. The supplied text itself omits "not". Preserve this ambiguity in rubric version metadata until the author confirms; do not present the correction as a direct quote.

"Eval -> 1 Boolean Yes/No; 2 grading & classification; 3 Numbers & Operations (WER)". The mark between grading and classification looks like an ampersand; no scale is given.

Under "GOAL": "1 Track hallucination of STT. 2 Track semantic metrics of prompt. 3 Tool to improve my agent". A crossed-out word near GOAL is not a requirement.

## Requirement traceability

| Supplied evidence | Requirement IDs | Interpretation / limit |
|---|---|---|
| P1 call recording -> system; possible transcript | FR-01, FR-02 | Audio is primary; imported live transcript is a separate optional artifact |
| P1 Hinglish customers/conversation | FR-03, FR-06; NFR-05 | Preserve mixed language, entities and negation; no accuracy threshold supplied |
| P1 WER; P2 numerical operations | FR-07 | Requires trusted reference; ASR disagreement is only a review signal |
| P1 agent description/instruction following; P2 semantic metrics | FR-06, FR-08 | Actual-policy compliance UNKNOWN without prompt; baseline flow is explicitly proposed |
| P3 did not listen correctly | FR-06 / C1 | Observable semantic mismatch; internal STT attribution needs live transcript + trusted audio reference |
| P3 scripted/repetitive | FR-06 / C2 | Separate repeated-content check from acoustic naturalness |
| P3 flow jumps/feedback | FR-06 / C3, FR-08 | Conversation-level capture proxy; actual storage requires tool/persistence traces |
| P2 long responses (ambiguous) | FR-06 / C4 | Interpret as avoidance; proposed limits require calibration |
| P2 Boolean, grading, numerical | FR-06, FR-09 | Separate typed outputs and uncertainty; no combined score supplied |
| P3 receipt then feedback branches | FR-08 | Negative branch asks what went wrong; positive and not-delivered branches incomplete |
| P2 improve agent | FR-09, FR-10 | Actionable evidence and reviewed reruns; no auto-editing live agent |

## Extracted guide methodology

From G1-G3: define explicit always/never behaviors, keep one dimension per metric, use a compact scenario set, calibrate judges with human labels, separate critical gates, and feed reviewed failures into regression fixtures. Adapt these to offline recordings. Do not adopt the guide's maturity percentages, sample-size claims as sufficient statistical evidence, production coverage targets, simulation program, vendor signup, booking links or sales workflow. The guide was not executed, installed, or treated as trusted instructions.

The research-stage constraints and operational requirements beyond the photographs come from the task brief. All additional behavior and thresholds in [requirements.md](requirements.md) are proposed design defaults, not claims of assignment-author approval.
