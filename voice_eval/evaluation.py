"""Evidence validation and scenario-independent evaluation rules."""

from __future__ import annotations

import re
from collections import Counter

from voice_eval.domain import (
    MAX_FINDING_EVIDENCE,
    BooleanResult,
    Coverage,
    EvaluationReport,
    Evidence,
    Finding,
    GradeClass,
    GradeResult,
    MeasurementKind,
    MetricId,
    NumericMeasurement,
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

_BOOLEAN_SPECS: dict[MetricId, tuple[str, bool]] = {
    "semantic_uptake": ("meaning_respected", True),
    "unnecessary_repetition": ("unnecessary_repetition", False),
    "scenario_flow": ("flow_followed", True),
    "response_length": ("excessive_length", False),
}


def _boolean_result(
    metric_id: MetricId, value: bool | None, kind: MeasurementKind
) -> BooleanResult:
    name, pass_when = _BOOLEAN_SPECS[metric_id]
    return BooleanResult(
        name=name,
        value=value,
        pass_when=pass_when,
        measurement_kind=kind,
    )


def _grade_result(value: int | None, kind: MeasurementKind) -> GradeResult:
    classes = {
        0: GradeClass.NEEDS_IMPROVEMENT,
        1: GradeClass.PARTIAL,
        2: GradeClass.MEETS_EXPECTATIONS,
    }
    return GradeResult(
        value=value,
        classification=classes[value] if value is not None else None,
        measurement_kind=kind,
    )


def _measurement(
    name: str, value: int | float, unit: str, kind: MeasurementKind
) -> NumericMeasurement:
    return NumericMeasurement.model_validate(
        {"name": name, "value": value, "unit": unit, "measurement_kind": kind}
    )


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


def _sample_evidence(segments: list[Segment]) -> list[Evidence]:
    """Return the earliest bounded evidence sample without changing source counts."""
    return [_evidence(segment) for segment in segments[:MAX_FINDING_EVIDENCE]]


def validate_finding_evidence(finding: Finding, segments: list[Segment]) -> None:
    """Reject unknown segment IDs, out-of-range offsets, or inexact quotes."""
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
    """Reject duplicate IDs and timestamps outside the source recording."""
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
        Finding(
            metric_id=metric_id,
            verdict=Verdict.UNKNOWN,
            rationale=reason,
            boolean_result=_boolean_result(metric_id, None, "deterministic"),
            grade_result=_grade_result(None, "deterministic"),
        )
        for metric_id in metric_ids
    ]


def _semantic_uptake(segments: list[Segment], kind: MeasurementKind) -> Finding:
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
            boolean_result=_boolean_result("semantic_uptake", None, kind),
            grade_result=_grade_result(None, kind),
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
                boolean_result=_boolean_result("semantic_uptake", False, kind),
                grade_result=_grade_result(0, kind),
                measurements=[_measurement("shared_meaning_terms", len(shared), "count", kind)],
            )
        if len(shared) >= 2:
            return Finding(
                metric_id="semantic_uptake",
                verdict=Verdict.PASS,
                rationale="The response acknowledges multiple meaningful terms from the caller.",
                evidence=[_evidence(customer), _evidence(agent)],
                boolean_result=_boolean_result("semantic_uptake", True, kind),
                grade_result=_grade_result(2, kind),
                measurements=[_measurement("shared_meaning_terms", len(shared), "count", kind)],
            )
    return Finding(
        metric_id="semantic_uptake",
        verdict=Verdict.UNKNOWN,
        rationale="Semantic uptake needs human or configured model review for this wording.",
        evidence=[_evidence(pairs[0][0]), _evidence(pairs[0][1])],
        boolean_result=_boolean_result("semantic_uptake", None, kind),
        grade_result=_grade_result(None, kind),
    )


def _repetition(segments: list[Segment], kind: MeasurementKind) -> Finding:
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
            boolean_result=_boolean_result("unnecessary_repetition", False, kind),
            grade_result=_grade_result(2, kind),
            measurements=[_measurement("exact_repeated_turns", 0, "count", kind)],
        )
    matches = [
        segment
        for segment, text in zip(agent_segments, normalized, strict=True)
        if text == repeated
    ]
    return Finding(
        metric_id="unnecessary_repetition",
        verdict=Verdict.FAIL,
        rationale=(
            "An identical agent turn appears more than once and requires reviewer context. "
            "Evidence shows a bounded sample; the numeric count covers every matching turn."
            if len(matches) > MAX_FINDING_EVIDENCE
            else "An identical agent turn appears more than once and requires reviewer context."
        ),
        evidence=_sample_evidence(matches),
        boolean_result=_boolean_result("unnecessary_repetition", True, kind),
        grade_result=_grade_result(0, kind),
        measurements=[_measurement("exact_repeated_turns", len(matches), "count", kind)],
    )


def _scenario_flow(
    segments: list[Segment], profile: ScenarioProfile, kind: MeasurementKind
) -> Finding:
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
        boolean_result=_boolean_result(
            "scenario_flow", True if verdict == Verdict.PASS else None, kind
        ),
        grade_result=_grade_result(2 if verdict == Verdict.PASS else None, kind),
        measurements=[
            _measurement(
                "configured_requirements", len(profile.required_information), "count", kind
            ),
            _measurement(
                "candidate_requirements_observed", required_matches, "count", kind
            ),
        ],
    )


def _response_length(
    segments: list[Segment], kind: MeasurementKind, *, grade_allowed: bool
) -> Finding:
    agents = [segment for segment in segments if segment.speaker == "agent"]
    if not agents:
        return Finding(
            metric_id="response_length",
            verdict=Verdict.UNKNOWN,
            rationale="No confirmed agent turns were available.",
            boolean_result=_boolean_result("response_length", None, kind),
            grade_result=_grade_result(None, kind),
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
    measurements = [
        _measurement("agent_turns_checked", len(observations), "count", kind),
        _measurement("turns_exceeding_limits", len(exceeded), "count", kind),
        _measurement("max_agent_turn_words", max(item[1] for item in observations), "words", kind),
        _measurement("agent_turn_word_limit", 60, "words", kind),
        _measurement("agent_turn_duration_limit", 20, "seconds", kind),
    ]
    maximum_duration = max(
        (item[2] for item in observations if item[2] is not None), default=None
    )
    if maximum_duration is not None:
        measurements.append(
            _measurement("max_agent_turn_duration", maximum_duration, "seconds", kind)
        )
    return Finding(
        metric_id="response_length",
        verdict=Verdict.FAIL if exceeded else Verdict.PASS,
        rationale=(
            (
                "At least one reviewed complete agent turn exceeded a configured limit. "
                "Evidence shows a bounded sample; numeric measurements cover every agent turn."
                if len(exceeded) > MAX_FINDING_EVIDENCE
                else "At least one reviewed complete agent turn exceeded a configured limit."
            )
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
        evidence=_sample_evidence([item[0] for item in (exceeded or observations)]),
        boolean_result=_boolean_result("response_length", bool(exceeded), kind),
        grade_result=_grade_result(
            (0 if exceeded else 2) if grade_allowed else None,
            kind,
        ),
        measurements=measurements,
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
    """Build a versioned report without fabricating unavailable semantic judgments."""
    validate_transcript_segments(segments)
    speakers = {segment.speaker for segment in segments}
    mapped = {"agent", "customer"}.issubset(speakers)
    if not mapped:
        findings = _unknown_findings("Confirmed agent and customer speaker roles are required.")
    else:
        kind: MeasurementKind = "synthetic_fixture" if fixture else "deterministic"
        findings = [
            _semantic_uptake(segments, kind),
            _repetition(segments, kind),
            _scenario_flow(segments, profile, kind),
            _response_length(segments, kind, grade_allowed=fixture),
        ]
        if not fixture:
            for index, finding in enumerate(findings[:3]):
                sampling_note = (
                    " Evidence is a bounded sample; numeric measurements cover all matching turns."
                    if "bounded sample" in finding.rationale
                    else ""
                )
                findings[index] = Finding.model_validate(
                    {
                        **finding.model_dump(mode="python"),
                        "verdict": Verdict.UNKNOWN,
                        "candidate_verdict": finding.verdict,
                        "boolean_result": finding.boolean_result.model_copy(
                            update={"value": None}
                        )
                        if finding.boolean_result
                        else None,
                        "grade_result": finding.grade_result.model_copy(
                            update={"value": None, "classification": None}
                        )
                        if finding.grade_result
                        else None,
                        "rationale": (
                            "Deterministic text checks produced a candidate signal, but semantic "
                            "judgment requires a validated judge or explicit human assessment."
                            f"{sampling_note}"
                        ),
                    }
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
