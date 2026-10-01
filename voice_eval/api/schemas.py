"""Validated request and response models exposed by the HTTP API."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from voice_eval.domain import (
    CharacterErrorRate,
    EvaluationReport,
    ScenarioProfile,
    Segment,
    WordErrorRate,
)
from voice_eval.media import MediaMetadata

MetricsReason = Literal[
    "THRESHOLD_NOT_DEFINED",
    "MISSING_REFERENCE",
    "MISSING_HYPOTHESIS",
    "EMPTY_REFERENCE",
]


class MetricsRequest(BaseModel):
    """Text inputs for WER/CER calculation against a trusted reference."""

    model_config = ConfigDict(extra="forbid")

    trusted_reference: str | None = Field(default=None, max_length=1_000_000)
    hypothesis: str | None = Field(default=None, max_length=1_000_000)


class MetricsResponse(BaseModel):
    """Observed error metrics, or an explicit reason they are unavailable."""

    status: Literal["OBSERVED", "UNKNOWN"]
    reason: MetricsReason
    wer: WordErrorRate | None
    cer: CharacterErrorRate | None


class PublicJob(BaseModel):
    """Job state safe to expose without local paths or payload hashes."""

    model_config = ConfigDict(extra="forbid")

    id: str
    idempotency_key: str | None
    status: str
    status_detail: str
    original_name: str
    media: MediaMetadata
    profile: ScenarioProfile
    profile_hash: str
    transcript: list[Segment] | None
    transcript_revision: int
    trusted_reference_text: str | None
    reference_attested: bool
    report: EvaluationReport | None
    run_version: int
    fixture: bool
    provider_model: str | None
    provider_handle: str | None
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None

    @classmethod
    def from_record(cls, record: dict[str, object]) -> PublicJob:
        """Validate a decoded store record while excluding private persistence fields."""
        public = {
            key: value
            for key, value in record.items()
            if key not in {"media_path", "payload_hash"}
        }
        return cls.model_validate(public)


class TranscriptRevision(BaseModel):
    """One immutable reviewed transcript revision in an export."""

    revision: int
    transcript: list[Segment]
    created_at: datetime


class EvaluationRun(BaseModel):
    """One immutable versioned evaluation report in an export."""

    version: int
    report: EvaluationReport
    created_at: datetime


class JobHistory(BaseModel):
    """Version history included with a completed report export."""

    transcript_revisions: list[TranscriptRevision]
    runs: list[EvaluationRun]


class ExportResponse(BaseModel):
    """Self-contained evidence report and its local revision history."""

    schema_version: Literal["1.0"]
    job: PublicJob
    report: EvaluationReport
    history: JobHistory
    external_provider_deletion: str


class DeleteResponse(BaseModel):
    """Confirmation that local content was deleted."""

    id: str
    status: Literal["deleted"]
    deleted_at: datetime
    external_provider_limit: str
