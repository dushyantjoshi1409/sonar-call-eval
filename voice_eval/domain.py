"""Validated domain contracts for profiles, transcripts, evidence, and reports."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictFloat,
    StrictInt,
    field_validator,
    model_validator,
)

MetricId = Literal["semantic_uptake", "unnecessary_repetition", "scenario_flow", "response_length"]
MeasurementKind = Literal["deterministic", "schema_judge", "synthetic_fixture"]
MAX_FINDING_EVIDENCE = 20


class Verdict(StrEnum):
    """Evidence status, kept separate from any typed evaluation value."""

    PASS = "PASS"
    FAIL = "FAIL"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    UNKNOWN = "UNKNOWN"


class GradeClass(StrEnum):
    """Proposed uncalibrated three-level quality classification."""

    NEEDS_IMPROVEMENT = "NEEDS_IMPROVEMENT"
    PARTIAL = "PARTIAL"
    MEETS_EXPECTATIONS = "MEETS_EXPECTATIONS"


class BooleanResult(BaseModel):
    """Explicit nullable Yes/No output with declared pass polarity."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    value: StrictBool | None
    pass_when: StrictBool
    measurement_kind: MeasurementKind


class GradeResult(BaseModel):
    """Nullable proposed 0-2 grade and its fixed classification label.

    The source photographs name grading/classification but provide no scale. This
    default is deliberately uncalibrated and independent of aggregate scoring.
    """

    model_config = ConfigDict(extra="forbid")

    scale: Literal["proposed-quality-v1"] = "proposed-quality-v1"
    value: Annotated[StrictInt, Field(ge=0, le=2)] | None = None
    classification: GradeClass | None = None
    measurement_kind: MeasurementKind

    @model_validator(mode="after")
    def validate_classification(self) -> GradeResult:
        expected = {
            0: GradeClass.NEEDS_IMPROVEMENT,
            1: GradeClass.PARTIAL,
            2: GradeClass.MEETS_EXPECTATIONS,
        }
        if (self.value is None) != (self.classification is None):
            raise ValueError("grade value and classification must both be null or present")
        if self.value is not None and self.classification != expected[self.value]:
            raise ValueError("grade classification does not match the proposed 0-2 scale")
        return self


class NumericMeasurement(BaseModel):
    """A named numeric observation with units and provenance."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(pattern=r"^[a-z][a-z0-9_]{1,79}$")
    value: StrictInt | Annotated[StrictFloat, Field(allow_inf_nan=False)]
    unit: Literal["count", "words", "seconds"]
    measurement_kind: MeasurementKind


class ScenarioProfile(BaseModel):
    """Versioned scenario instructions snapshotted for each evaluation run."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,63}$")
    name: str = Field(min_length=2, max_length=80)
    task_description: str = Field(min_length=3, max_length=2_000)
    expected_outcome: str = Field(min_length=1, max_length=2_000)
    required_information: list[str] = Field(max_length=20)
    policies: list[str] = Field(max_length=20)
    custom_criteria: list[str] = Field(max_length=20)

    @field_validator("required_information", "policies", "custom_criteria")
    @classmethod
    def validate_items(cls, value: list[str]) -> list[str]:
        if any(not item.strip() or len(item) > 500 for item in value):
            raise ValueError("profile list items must contain 1 to 500 characters")
        return value


class ProfileSnapshot(ScenarioProfile):
    """Immutable profile contents and canonical hash used for one run."""

    hash: str = Field(pattern=r"^[a-f0-9]{64}$")


class Segment(BaseModel):
    """One speaker-labelled transcript span with explicit timing precision."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=80)
    speaker: Literal["agent", "customer", "other", "unknown"]
    start: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    end: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    text: str = Field(min_length=1, max_length=20_000)
    precision: Literal["manual", "model_estimated", "chunk", "unknown"] = "unknown"

    @model_validator(mode="after")
    def validate_time_range(self) -> Segment:
        if (self.start is None) != (self.end is None):
            raise ValueError("start and end must both be present or absent")
        if self.start is not None and self.end is not None and self.end < self.start:
            raise ValueError("segment end must not precede start")
        return self


class Evidence(BaseModel):
    """Exact quote offsets into one stored transcript segment."""

    model_config = ConfigDict(extra="forbid")

    segment_id: str
    quote: str = Field(min_length=1)
    start_char: int = Field(ge=0)
    end_char: int = Field(gt=0)

    @model_validator(mode="after")
    def validate_offsets(self) -> Evidence:
        if self.end_char <= self.start_char:
            raise ValueError("evidence end_char must exceed start_char")
        return self


class Finding(BaseModel):
    """One independent verdict with typed values and source evidence."""

    model_config = ConfigDict(extra="forbid")

    metric_id: MetricId
    verdict: Verdict
    rationale: str = Field(min_length=1, max_length=2_000)
    evidence: list[Evidence] = Field(default_factory=list, max_length=MAX_FINDING_EVIDENCE)
    boolean_result: BooleanResult | None = None
    grade_result: GradeResult | None = None
    measurements: list[NumericMeasurement] = Field(default_factory=list, max_length=20)
    candidate_verdict: Verdict | None = None
    # Retained only so stored schema 1.0 reports remain readable.
    value: dict[str, float | int | str | bool | None] = Field(default_factory=dict)

    @model_validator(mode="after")
    def determinate_findings_require_evidence(self) -> Finding:
        if self.verdict in {Verdict.PASS, Verdict.FAIL} and not self.evidence:
            raise ValueError("PASS and FAIL findings require source evidence")
        if self.verdict in {Verdict.UNKNOWN, Verdict.NOT_APPLICABLE}:
            if self.boolean_result is not None and self.boolean_result.value is not None:
                raise ValueError("Boolean value must be null for UNKNOWN or NOT_APPLICABLE")
            if self.grade_result is not None and self.grade_result.value is not None:
                raise ValueError("Grade value must be null for UNKNOWN or NOT_APPLICABLE")
        if self.boolean_result is not None and self.boolean_result.value is not None:
            expected = (
                Verdict.PASS
                if self.boolean_result.value == self.boolean_result.pass_when
                else Verdict.FAIL
            )
            if self.verdict != expected:
                raise ValueError("Boolean polarity contradicts the finding verdict")
        if self.grade_result is not None and self.grade_result.value is not None:
            if self.verdict == Verdict.PASS and self.grade_result.value != 2:
                raise ValueError("PASS requires a Meets Expectations grade")
            if self.verdict == Verdict.FAIL and self.grade_result.value == 2:
                raise ValueError("FAIL cannot carry a Meets Expectations grade")
        return self


class Coverage(BaseModel):
    """Observed evaluation coverage, not a quality score."""

    transcript_segments: int
    timed_segments: int
    mapped_speakers: bool
    policy_supplied: bool
    trusted_reference_supplied: bool
    backend_trace_supplied: bool = False


class WordErrorRate(BaseModel):
    """WER operation result with edit counts and denominator."""

    value: float
    substitutions: int
    deletions: int
    insertions: int
    reference_units: int
    normalization_version: Literal["unicode-nfc-lower-whitespace-v1"]


class CharacterErrorRate(BaseModel):
    """CER operation result over normalized Unicode code points."""

    value: float
    substitutions: int
    deletions: int
    insertions: int
    reference_units: int
    normalization_version: Literal["unicode-nfc-lower-whitespace-v1"]


class EvaluationReport(BaseModel):
    """Versioned report containing independent findings and explicit unknowns."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0", "1.1"] = "1.1"
    run_version: int = Field(ge=1)
    evaluator: str
    profile_snapshot: ProfileSnapshot
    transcript_revision: int = Field(ge=1)
    findings: list[Finding]
    coverage: Coverage
    wer: WordErrorRate | None = None
    cer: CharacterErrorRate | None = None
    unknowns: list[str]
    aggregate_score: None = None
    fixture: bool = False


class TranscriptionResult(BaseModel):
    """Untrusted provider transcript requiring speaker and timing review."""

    model_config = ConfigDict(extra="forbid")

    segments: list[Segment] = Field(min_length=1, max_length=1_000)
    language_notes: str = ""
    timestamp_warning: str = Field(min_length=1)
    model: str


class JudgeResult(BaseModel):
    """Schema-constrained provider output for the three semantic metrics."""

    model_config = ConfigDict(extra="forbid")

    findings: list[Finding] = Field(min_length=3, max_length=3)

    @model_validator(mode="after")
    def require_each_semantic_metric_once(self) -> JudgeResult:
        expected = {"semantic_uptake", "unnecessary_repetition", "scenario_flow"}
        actual = {finding.metric_id for finding in self.findings}
        if actual != expected:
            raise ValueError("judge must return each semantic metric exactly once")
        for finding in self.findings:
            if finding.boolean_result is None or finding.grade_result is None:
                raise ValueError("judge findings require Boolean and grade result objects")
            if finding.verdict in {Verdict.PASS, Verdict.FAIL} and (
                finding.boolean_result.value is None or finding.grade_result.value is None
            ):
                raise ValueError("determinate judge findings require Boolean and grade values")
            if finding.boolean_result.measurement_kind != "schema_judge":
                raise ValueError("judge Boolean values require schema_judge provenance")
            if finding.grade_result.measurement_kind != "schema_judge":
                raise ValueError("judge grades require schema_judge provenance")
        expected_boolean = {
            "semantic_uptake": ("meaning_respected", True),
            "unnecessary_repetition": ("unnecessary_repetition", False),
            "scenario_flow": ("flow_followed", True),
        }
        for finding in self.findings:
            assert finding.boolean_result is not None
            name, pass_when = expected_boolean[finding.metric_id]
            if (
                finding.boolean_result.name != name
                or finding.boolean_result.pass_when is not pass_when
            ):
                raise ValueError("judge Boolean name or polarity does not match the metric")
        return self
