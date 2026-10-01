from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

MetricId = Literal["semantic_uptake", "unnecessary_repetition", "scenario_flow", "response_length"]


class Verdict(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    UNKNOWN = "UNKNOWN"


class ScenarioProfile(BaseModel):
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
    hash: str = Field(pattern=r"^[a-f0-9]{64}$")


class Segment(BaseModel):
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
    model_config = ConfigDict(extra="forbid")

    metric_id: MetricId
    verdict: Verdict
    rationale: str = Field(min_length=1, max_length=2_000)
    evidence: list[Evidence] = Field(default_factory=list, max_length=20)
    value: dict[str, float | int | str | bool | None] = Field(default_factory=dict)

    @model_validator(mode="after")
    def determinate_findings_require_evidence(self) -> Finding:
        if self.verdict in {Verdict.PASS, Verdict.FAIL} and not self.evidence:
            raise ValueError("PASS and FAIL findings require source evidence")
        return self


class Coverage(BaseModel):
    transcript_segments: int
    timed_segments: int
    mapped_speakers: bool
    policy_supplied: bool
    trusted_reference_supplied: bool
    backend_trace_supplied: bool = False


class WordErrorRate(BaseModel):
    value: float
    substitutions: int
    deletions: int
    insertions: int
    reference_units: int
    normalization_version: Literal["unicode-nfc-lower-whitespace-v1"]


class CharacterErrorRate(BaseModel):
    value: float
    substitutions: int
    deletions: int
    insertions: int
    reference_units: int
    normalization_version: Literal["unicode-nfc-lower-whitespace-v1"]


class EvaluationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
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
    model_config = ConfigDict(extra="forbid")

    segments: list[Segment] = Field(min_length=1, max_length=1_000)
    language_notes: str = ""
    timestamp_warning: str = Field(min_length=1)
    model: str


class JudgeResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    findings: list[Finding] = Field(min_length=3, max_length=3)

    @model_validator(mode="after")
    def require_each_semantic_metric_once(self) -> JudgeResult:
        expected = {"semantic_uptake", "unnecessary_repetition", "scenario_flow"}
        actual = {finding.metric_id for finding in self.findings}
        if actual != expected:
            raise ValueError("judge must return each semantic metric exactly once")
        return self
