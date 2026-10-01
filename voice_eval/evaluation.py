from __future__ import annotations

import re
from collections import Counter

from voice_eval.domain import (
    Coverage,
    EvaluationReport,
    Evidence,
    Finding,
    MetricId,
    ProfileSnapshot,
    ScenarioProfile,
    Segment,
    Verdict,
)
from voice_eval.metrics import character_error_rate, word_error_rate

_NEGATIONS = {"not", "no", "never", "nahi", "nahin", "नहीं", "मत"}
_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "can",
    "for",
    "i",
    "is",
    "it",
    "the",
    "to",
    "you",
    "your",
    "with",
}


def _words(text: str) -> set[str]:
    return {word for word in re.findall(r"\w+", text.lower()) if word not in _STOPWORDS}


def _evidence(segment: Segment, quote: str | None = None) -> Evidence:
    selected = quote or segment.text
    start = segment.text.find(selected)
    if start < 0:
        raise ValueError("evidence quote was not found in segment")
    return Evidence(
        segment_id=segment.id,
        quote=selected,
        start_char=start,
        end_char=start + len(selected),
    )


def validate_finding_evidence(finding: Finding, segments: list[Segment]) -> None:
    by_id = {segment.id: segment for segment in segments}
    for evidence in finding.evidence:
        segment = by_id.get(evidence.segment_id)
        if segment is None:
            raise ValueError(f"unknown evidence segment {evidence.segment_id}")
        if evidence.end_char > len(segment.text):
            raise ValueError("evidence offsets exceed source segment")
        if segment.text[evidence.start_char : evidence.end_char] != evidence.quote:
            raise ValueError("evidence quote does not match source segment offsets")


def validate_transcript_segments(
    segments: list[Segment], duration_seconds: float | None = None
) -> None:
    segment_ids = [segment.id for segment in segments]
    if len(set(segment_ids)) != len(segment_ids):
        raise ValueError("transcript segment IDs must be unique")
    if duration_seconds is not None and any(
        segment.end is not None and segment.end > duration_seconds + 0.5
        for segment in segments
    ):
        raise ValueError("transcript timestamps exceed the recording duration")


def _unknown_findings(reason: str) -> list[Finding]:
    metric_ids: tuple[MetricId, ...] = (
        "semantic_uptake",
        "unnecessary_repetition",
        "scenario_flow",
        "response_length",
    )
    return [
        Finding(metric_id=metric_id, verdict=Verdict.UNKNOWN, rationale=reason)
        for metric_id in metric_ids
    ]


def _semantic_uptake(segments: list[Segment]) -> Finding:
    pairs: list[tuple[Segment, Segment]] = []
    for index, segment in enumerate(segments[:-1]):
        if segment.speaker == "customer":
            following = next(
                (item for item in segments[index + 1 :] if item.speaker == "agent"), None
            )
            if following is not None:
                pairs.append((segment, following))
    if not pairs:
        return Finding(
            metric_id="semantic_uptake",
            verdict=Verdict.UNKNOWN,
            rationale="No customer-to-agent response pair was available.",
        )
    for customer, agent in pairs:
        caller_negation = bool(_words(customer.text) & _NEGATIONS)
        agent_negation = bool(_words(agent.text) & _NEGATIONS)
        shared = _words(customer.text) & _words(agent.text)
        if caller_negation != agent_negation and len(shared) >= 1:
            return Finding(
                metric_id="semantic_uptake",
                verdict=Verdict.FAIL,
                rationale="The response appears to reverse or omit the caller's negation.",
                evidence=[_evidence(customer), _evidence(agent)],
            )
        if len(shared) >= 2:
            return Finding(
                metric_id="semantic_uptake",
                verdict=Verdict.PASS,
                rationale="The response acknowledges multiple meaningful terms from the caller.",
                evidence=[_evidence(customer), _evidence(agent)],
                value={"shared_meaning_terms": len(shared)},
            )
    return Finding(
        metric_id="semantic_uptake",
        verdict=Verdict.UNKNOWN,
        rationale="Semantic uptake needs human or configured model review for this wording.",
        evidence=[_evidence(pairs[0][0]), _evidence(pairs[0][1])],
    )


def _repetition(segments: list[Segment]) -> Finding:
    agent_segments = [segment for segment in segments if segment.speaker == "agent"]
    normalized = [" ".join(re.findall(r"\w+", item.text.lower())) for item in agent_segments]
    repeated = next(
        (text for text, count in Counter(normalized).items() if text and count > 1), None
    )
    if repeated is None:
        return Finding(
            metric_id="unnecessary_repetition",
            verdict=Verdict.PASS,
            rationale="No identical agent turn was repeated.",
            evidence=[_evidence(agent_segments[0])] if agent_segments else [],
            value={"exact_repeated_turns": 0},
        )
    matches = [
        segment
        for segment, text in zip(agent_segments, normalized, strict=True)
        if text == repeated
    ]
    return Finding(
        metric_id="unnecessary_repetition",
        verdict=Verdict.FAIL,
        rationale="An identical agent turn appears more than once and requires reviewer context.",
        evidence=[_evidence(item) for item in matches],
        value={"exact_repeated_turns": len(matches)},
    )


def _scenario_flow(segments: list[Segment], profile: ScenarioProfile) -> Finding:
    joined = " ".join(segment.text.lower() for segment in segments)
    required_matches = 0
    for requirement in profile.required_information:
        terms = _words(requirement)
        if terms and terms & _words(joined):
            required_matches += 1
    if profile.required_information and required_matches == len(profile.required_information):
        verdict = Verdict.PASS
        rationale = (
            "The transcript contains terms related to every configured information requirement."
        )
    else:
        verdict = Verdict.UNKNOWN
        rationale = "Configured information coverage needs reviewer confirmation."
    return Finding(
        metric_id="scenario_flow",
        verdict=verdict,
        rationale=rationale,
        evidence=[_evidence(segment) for segment in segments[: min(3, len(segments))]],
        value={
            "configured_requirements": len(profile.required_information),
            "candidate_requirements_observed": required_matches,
        },
    )


def _response_length(segments: list[Segment]) -> Finding:
    agents = [segment for segment in segments if segment.speaker == "agent"]
    if not agents:
        return Finding(
            metric_id="response_length",
            verdict=Verdict.UNKNOWN,
            rationale="No confirmed agent turns were available.",
        )
    observations: list[tuple[Segment, int, float | None]] = []
    for segment in agents:
        duration = (
            segment.end - segment.start
            if segment.precision == "manual"
            and segment.start is not None
            and segment.end is not None
            else None
        )
        observations.append((segment, len(segment.text.split()), duration))
    exceeded = [
        item for item in observations if item[1] > 60 or (item[2] is not None and item[2] > 20)
    ]
    return Finding(
        metric_id="response_length",
        verdict=Verdict.FAIL if exceeded else Verdict.PASS,
        rationale=(
            "At least one reviewed complete agent turn exceeded a configured limit."
            if exceeded
            else (
                "No agent turn exceeded 60 words; reviewed timing did not exceed 20 seconds."
                if any(item[2] is not None for item in observations)
                else (
                    "No agent turn exceeded 60 words; reliable complete-turn timing "
                    "was unavailable."
                )
            )
        ),
        evidence=[_evidence(item[0]) for item in (exceeded or observations)],
        value={
            "max_words": max(item[1] for item in observations),
            "max_duration_seconds": max(
                (item[2] for item in observations if item[2] is not None), default=None
            ),
            "word_limit": 60,
            "duration_limit_seconds": 20,
            "duration_precision": (
                "reviewed_manual"
                if any(item[2] is not None for item in observations)
                else "unknown"
            ),
        },
    )


def evaluate_transcript(
    segments: list[Segment],
    profile: ScenarioProfile,
    snapshot_hash: str,
    *,
    run_version: int = 1,
    transcript_revision: int = 1,
    fixture: bool = False,
    trusted_reference: str | None = None,
    reference_attested: bool = False,
) -> EvaluationReport:
    validate_transcript_segments(segments)
    speakers = {segment.speaker for segment in segments}
    mapped = {"agent", "customer"}.issubset(speakers)
    if not mapped:
        findings = _unknown_findings("Confirmed agent and customer speaker roles are required.")
    else:
        findings = [
            _semantic_uptake(segments),
            _repetition(segments),
            _scenario_flow(segments, profile),
            _response_length(segments),
        ]
        if not fixture:
            for finding in findings[:3]:
                candidate = finding.verdict.value
                finding.value = {**finding.value, "deterministic_candidate": candidate}
                finding.verdict = Verdict.UNKNOWN
                finding.rationale = (
                    "Deterministic text checks produced a candidate signal, but semantic "
                    "judgment requires a validated judge or explicit human assessment."
                )
    for finding in findings:
        validate_finding_evidence(finding, segments)
    hypothesis = " ".join(segment.text for segment in segments)
    wer = word_error_rate(trusted_reference, hypothesis) if reference_attested else None
    cer = character_error_rate(trusted_reference, hypothesis) if reference_attested else None
    unknowns: list[str] = []
    if trusted_reference is None:
        unknowns.append("Trusted human reference was not supplied; WER/CER are unavailable.")
    elif not reference_attested:
        unknowns.append("Reference was not attested as audio-matched; WER/CER are unavailable.")
    elif wer is None:
        unknowns.append("Trusted reference was empty; WER/CER are unavailable.")
    if not profile.policies:
        unknowns.append("Business policy was not supplied; policy compliance is UNKNOWN.")
    unknowns.extend(
        [
            "Backend action trace was not supplied; a conversational confirmation "
            "is not proof that an action completed.",
            "Tool and storage traces were not supplied; successful actions and "
            "persistence are UNKNOWN.",
        ]
    )
    return EvaluationReport(
        run_version=run_version,
        evaluator=("synthetic-fixture-rubric-v1" if fixture else "deterministic-candidates-v1"),
        profile_snapshot=ProfileSnapshot(**profile.model_dump(), hash=snapshot_hash),
        transcript_revision=transcript_revision,
        findings=findings,
        coverage=Coverage(
            transcript_segments=len(segments),
            timed_segments=sum(item.start is not None for item in segments),
            mapped_speakers=mapped,
            policy_supplied=bool(profile.policies),
            trusted_reference_supplied=trusted_reference is not None and reference_attested,
        ),
        wer=wer,
        cer=cer,
        unknowns=unknowns,
        fixture=fixture,
    )
