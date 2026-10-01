"""Fixed synthetic regression suite and expectation-aware baseline comparisons."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Any

from pydantic import ValidationError

from voice_eval.config import Settings
from voice_eval.domain import MetricId, ScenarioProfile, Segment, Verdict
from voice_eval.evaluation import evaluate_transcript, validate_finding_evidence
from voice_eval.profiles import get_preset, profile_hash
from voice_eval.provider_sessions import ProviderSessionVault, environment_provider_config
from voice_eval.providers import (
    JUDGE_PROMPT_VERSION,
    ProviderConfig,
    ProviderError,
    create_provider_adapter,
)
from voice_eval.services import InvalidJobInput, ProviderUnavailable
from voice_eval.store import Store

REGRESSION_SUITE_VERSION = "voice-eval-regression-v1"
REGRESSION_RUBRIC_VERSION = "independent-metrics-evidence-v1"


@dataclass(frozen=True, slots=True)
class RegressionCase:
    """One authored synthetic transcript with independent expected verdicts."""

    id: str
    name: str
    category: str
    purpose: str
    profile: ScenarioProfile
    transcript: tuple[Segment, ...]
    expectations: Mapping[MetricId, Verdict]
    expectation_notes: Mapping[MetricId, str]
    synthetic: bool = True

    @property
    def profile_hash(self) -> str:
        return profile_hash(self.profile)


def _expectations(**values: str) -> Mapping[MetricId, Verdict]:
    return MappingProxyType(
        {metric: Verdict(value) for metric, value in values.items()}  # type: ignore[misc]
    )


def _notes(**values: str) -> Mapping[MetricId, str]:
    return MappingProxyType(values)  # type: ignore[arg-type]


def regression_cases() -> tuple[RegressionCase, ...]:
    """Return the small versioned suite; all content is synthetic and immutable."""
    generic = get_preset("generic-conversation")
    dental = get_preset("dental-appointment")
    delivery = get_preset("food-delivery")
    common_pass = {
        "unnecessary_repetition": "PASS",
        "response_length": "PASS",
    }
    common_notes = {
        "unnecessary_repetition": "Should not flag repetition when no avoidable repeat occurs.",
        "response_length": "Should keep short complete agent turns within the limit.",
    }
    return (
        RegressionCase(
            id="dental-complete",
            name="Dental request with a clear next step",
            category="dental",
            purpose="Should preserve the visit need and collect timing before an honest next step.",
            profile=dental,
            transcript=(
                Segment(
                    id="d1", speaker="customer", text="I need a cleaning appointment next Tuesday."
                ),
                Segment(
                    id="d2",
                    speaker="agent",
                    text=(
                        "You need a cleaning next Tuesday. I can check available appointment "
                        "times next."
                    ),
                ),
            ),
            expectations=_expectations(semantic_uptake="PASS", scenario_flow="PASS", **common_pass),
            expectation_notes=_notes(
                semantic_uptake="Should respect cleaning and Tuesday.",
                scenario_flow="Should recognize reason, timing, and a non-fabricated next step.",
                **common_notes,
            ),
        ),
        RegressionCase(
            id="delivery-not-received",
            name="Undelivered order is not treated as food feedback",
            category="delivery",
            purpose="Should preserve the negative delivery state and avoid assuming food arrived.",
            profile=delivery,
            transcript=(
                Segment(id="f1", speaker="customer", text="My order was not delivered."),
                Segment(
                    id="f2",
                    speaker="agent",
                    text=(
                        "I understand the order was not delivered. I will record delivery "
                        "feedback and explain the next support step."
                    ),
                ),
            ),
            expectations=_expectations(semantic_uptake="PASS", scenario_flow="PASS", **common_pass),
            expectation_notes=_notes(
                semantic_uptake="Should preserve the caller's negation.",
                scenario_flow=(
                    "Should cover delivery state and relevant feedback without food questions."
                ),
                **common_notes,
            ),
        ),
        RegressionCase(
            id="negation-reversed",
            name="Cancellation negation is reversed",
            category="meaning-negation",
            purpose="Should fail meaning when the agent reverses an explicit negative instruction.",
            profile=generic,
            transcript=(
                Segment(id="n1", speaker="customer", text="Do not cancel my service."),
                Segment(id="n2", speaker="agent", text="I will cancel your service now."),
            ),
            expectations=_expectations(semantic_uptake="FAIL", scenario_flow="FAIL", **common_pass),
            expectation_notes=_notes(
                semantic_uptake="Should flag the reversed negation.",
                scenario_flow="Should not pass a flow that takes the opposite next step.",
                **common_notes,
            ),
        ),
        RegressionCase(
            id="repetition-justified",
            name="Caller asks for one repetition",
            category="repetition",
            purpose="Should not penalize a repeated answer when the caller explicitly requests it.",
            profile=generic,
            transcript=(
                Segment(id="j1", speaker="customer", text="What is the next step?"),
                Segment(id="j2", speaker="agent", text="Please send the requested form."),
                Segment(id="j3", speaker="customer", text="Please repeat that."),
                Segment(id="j4", speaker="agent", text="Please send the requested form."),
            ),
            expectations=_expectations(
                semantic_uptake="PASS",
                unnecessary_repetition="PASS",
                scenario_flow="PASS",
                response_length="PASS",
            ),
            expectation_notes=_notes(
                semantic_uptake="Should respond to both the task and repeat request.",
                unnecessary_repetition="Should treat caller-requested repetition as justified.",
                scenario_flow="Should retain a clear requested next step.",
                response_length="Should keep repeated turns concise.",
            ),
        ),
        RegressionCase(
            id="repetition-unnecessary",
            name="Unprompted identical response",
            category="repetition",
            purpose="Should flag an identical agent turn repeated without a caller request.",
            profile=generic,
            transcript=(
                Segment(id="r1", speaker="customer", text="What happens next?"),
                Segment(id="r2", speaker="agent", text="Please send the requested form."),
                Segment(id="r3", speaker="customer", text="I already sent it."),
                Segment(id="r4", speaker="agent", text="Please send the requested form."),
            ),
            expectations=_expectations(
                semantic_uptake="FAIL",
                unnecessary_repetition="FAIL",
                scenario_flow="FAIL",
                response_length="PASS",
            ),
            expectation_notes=_notes(
                semantic_uptake="Should notice the reply ignores already-sent state.",
                unnecessary_repetition="Should flag the unprompted identical response.",
                scenario_flow="Should not pass a stalled next step.",
                response_length="Should keep individual turns concise.",
            ),
        ),
        RegressionCase(
            id="flow-missing-next-step",
            name="Acknowledgement without a next step",
            category="flow",
            purpose="Should distinguish polite acknowledgement from a complete scenario flow.",
            profile=generic,
            transcript=(
                Segment(id="w1", speaker="customer", text="I need help updating my address."),
                Segment(
                    id="w2",
                    speaker="agent",
                    text="I understand you need help updating your address.",
                ),
            ),
            expectations=_expectations(semantic_uptake="PASS", scenario_flow="FAIL", **common_pass),
            expectation_notes=_notes(
                semantic_uptake="Should recognize the address-update request.",
                scenario_flow="Should fail because no requested next step is stated.",
                **common_notes,
            ),
        ),
    )


class RegressionService:
    """Run bounded authored cases through the same evaluator and provider judge."""

    def __init__(self, settings: Settings, store: Store, sessions: ProviderSessionVault) -> None:
        self.settings = settings
        self.store = store
        self.sessions = sessions

    def run(self, *, baseline_id: str | None, provider_handle: str | None) -> dict[str, Any]:
        """Execute the fixed suite once and persist nonsecret result metadata."""
        provider = self._provider(provider_handle)
        baseline = self._baseline(baseline_id)
        run_id = str(uuid.uuid4())
        case_results = [self._run_case(case, provider) for case in regression_cases()]
        if baseline is not None:
            previous = {
                (case["case_id"], check["metric_id"]): check["outcome"]
                for case in baseline["cases"]
                for check in case["checks"]
            }
            for case in case_results:
                for check in case["checks"]:
                    prior = previous[(case["case_id"], check["metric_id"])]
                    check["comparison"] = _compare_outcomes(prior, check["outcome"])
        run = {
            "id": run_id,
            "suite_version": REGRESSION_SUITE_VERSION,
            "provider": provider.provider if provider else "offline",
            "model": provider.judge_model if provider else None,
            "prompt_version": JUDGE_PROMPT_VERSION,
            "rubric_version": REGRESSION_RUBRIC_VERSION,
            "baseline_id": baseline_id,
            "synthetic": True,
            "created_at": datetime.now(UTC).isoformat(),
            "cases": case_results,
        }
        return self.store.save_regression_run(run)

    def list_runs(self) -> list[dict[str, Any]]:
        """Return recent runs for the baseline selector and review page."""
        return self.store.list_regression_runs()

    def _provider(self, provider_handle: str | None) -> ProviderConfig | None:
        if provider_handle:
            provider = self.sessions.resolve_handle(provider_handle)
            if provider is None:
                raise ProviderUnavailable(
                    "Provider session expired or was cleared; reconnect before running checks"
                )
            return provider
        return environment_provider_config(self.settings)

    def _baseline(self, baseline_id: str | None) -> dict[str, Any] | None:
        if baseline_id is None:
            return None
        try:
            baseline = self.store.get_regression_run(baseline_id)
        except KeyError as error:
            raise InvalidJobInput("Baseline regression run was not found") from error
        compatible = (
            baseline["suite_version"] == REGRESSION_SUITE_VERSION
            and baseline["prompt_version"] == JUDGE_PROMPT_VERSION
            and baseline["rubric_version"] == REGRESSION_RUBRIC_VERSION
        )
        if not compatible:
            raise InvalidJobInput("Baseline suite, prompt, or rubric version is incompatible")
        return baseline

    def _run_case(self, case: RegressionCase, provider: ProviderConfig | None) -> dict[str, Any]:
        segments = list(case.transcript)
        report = evaluate_transcript(
            segments,
            case.profile,
            case.profile_hash,
            fixture=False,
        )
        provider_error: str | None = None
        if provider is not None:
            try:
                with create_provider_adapter(provider) as adapter:
                    judged = adapter.judge(segments, case.profile)
                for finding in judged.findings:
                    validate_finding_evidence(finding, segments)
                deterministic_length = next(
                    finding for finding in report.findings if finding.metric_id == "response_length"
                )
                report.findings = [*judged.findings, deterministic_length]
            except (ProviderError, ValidationError, ValueError) as error:
                provider_error = str(error)
        findings = {finding.metric_id: finding for finding in report.findings}
        checks: list[dict[str, object]] = []
        for metric_id, expected in case.expectations.items():
            finding = findings[metric_id]
            if provider_error and metric_id != "response_length":
                actual = Verdict.UNKNOWN
                outcome = "error"
            else:
                actual = finding.verdict
                outcome = (
                    "unresolved"
                    if actual in {Verdict.UNKNOWN, Verdict.NOT_APPLICABLE}
                    else "met"
                    if actual == expected
                    else "mismatched"
                )
            checks.append(
                {
                    "metric_id": metric_id,
                    "expectation": case.expectation_notes[metric_id],
                    "expected": expected,
                    "actual": actual,
                    "outcome": outcome,
                    "comparison": "unresolved"
                    if outcome in {"unresolved", "error"}
                    else "unchanged",
                    "rationale": finding.rationale,
                    "evidence": [item.model_dump(mode="json") for item in finding.evidence],
                    "error": provider_error if outcome == "error" else None,
                }
            )
        return {
            "case_id": case.id,
            "name": case.name,
            "category": case.category,
            "purpose": case.purpose,
            "synthetic": True,
            "profile_hash": case.profile_hash,
            "profile": case.profile.model_dump(mode="json"),
            "transcript": [segment.model_dump(mode="json") for segment in segments],
            "checks": checks,
        }


def _compare_outcomes(previous: str, current: str) -> str:
    """Compare expectation outcomes without treating UNKNOWN or errors as success."""
    if previous in {"unresolved", "error"} or current in {"unresolved", "error"}:
        return "unresolved"
    if previous == current:
        return "unchanged"
    if previous == "mismatched" and current == "met":
        return "improved"
    return "newly_failing"
