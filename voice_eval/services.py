"""Application services that coordinate jobs across media, storage, and providers."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import sqlite3
import tempfile
import uuid
import wave
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from pydantic import TypeAdapter, ValidationError

from voice_eval.config import Settings
from voice_eval.domain import ScenarioProfile, Segment
from voice_eval.evaluation import (
    evaluate_transcript,
    validate_finding_evidence,
    validate_transcript_segments,
)
from voice_eval.media import MediaError, MediaValidator
from voice_eval.profiles import get_preset, profile_hash, validate_profile
from voice_eval.providers import GeminiAdapter, ProviderError
from voice_eval.store import Store, job_values

logger = logging.getLogger(__name__)
MAX_PROFILE_JSON_CHARS = 100_000
MAX_TRANSCRIPT_JSON_CHARS = 1_000_000
MAX_TRANSCRIPT_SEGMENTS = 1_000
MAX_REFERENCE_CHARS = 1_000_000


def _cleanup_staged_media(path: Path, *, remove_parent: bool = False) -> None:
    """Best-effort cleanup that never masks the operation's original failure."""
    try:
        path.unlink(missing_ok=True)
    except OSError:
        logger.warning("Could not remove staged media %s", path.name, exc_info=True)
        return
    if remove_parent:
        with suppress(OSError):
            path.parent.rmdir()


class AsyncReadable(Protocol):
    """Minimal async upload contract consumed by the job service."""

    async def read(self, size: int = -1) -> bytes: ...


class JobServiceError(RuntimeError):
    """Base class for expected job failures translated by the HTTP adapter."""


class InvalidJobInput(JobServiceError):
    """The caller supplied invalid media, transcript, profile, or metadata."""


class JobNotFound(JobServiceError):
    """No persisted job exists for the requested identifier."""


class JobGone(JobServiceError):
    """The requested job was already deleted."""


class JobConflict(JobServiceError):
    """The request conflicts with an existing idempotent operation."""


class QueueFull(JobServiceError):
    """The bounded local worker queue cannot accept another job."""


class ProviderUnavailable(JobServiceError):
    """A configured provider failed without a safe automatic fallback."""


class MediaUnavailable(JobServiceError):
    """A job exists but its local recording is no longer readable."""


@dataclass(frozen=True, slots=True)
class CreateJobCommand:
    """Validated HTTP form values and upload stream needed to create one job."""

    audio: AsyncReadable
    original_name: str
    profile_json: str | None = None
    profile_id: str | None = None
    transcript_json: str | None = None
    trusted_reference: str | None = None
    reference_attested: bool = False
    idempotency_key: str | None = None


@dataclass(frozen=True, slots=True)
class CreateJobResult:
    """A persisted job and whether this request created it or replayed it."""

    job: dict[str, Any]
    created: bool


def load_segments(raw: str | list[dict[str, Any]]) -> list[Segment]:
    """Parse and bound transcript segments before they cross into evaluation."""
    if isinstance(raw, str) and len(raw) > MAX_TRANSCRIPT_JSON_CHARS:
        raise InvalidJobInput("transcript JSON exceeds the 1,000,000 character limit")
    try:
        value = json.loads(raw) if isinstance(raw, str) else raw
        segments = TypeAdapter(list[Segment]).validate_python(value)
    except (json.JSONDecodeError, ValidationError, TypeError) as error:
        raise InvalidJobInput(f"Invalid transcript: {error}") from error
    if not segments:
        raise InvalidJobInput("transcript must contain at least one segment")
    if len(segments) > MAX_TRANSCRIPT_SEGMENTS:
        raise InvalidJobInput("transcript exceeds the 1,000 segment limit")
    return segments


def load_profile(profile_json: str | None, profile_id: str | None) -> ScenarioProfile:
    """Resolve either a bounded custom profile or a built-in preset."""
    try:
        if profile_json:
            if len(profile_json) > MAX_PROFILE_JSON_CHARS:
                raise InvalidJobInput("profile JSON exceeds the 100,000 character limit")
            value = json.loads(profile_json)
            if not isinstance(value, dict):
                raise InvalidJobInput("profile_json must be an object")
            return validate_profile(value)
        return get_preset(profile_id or "generic-conversation")
    except InvalidJobInput:
        raise
    except (json.JSONDecodeError, ValidationError, ValueError) as error:
        raise InvalidJobInput(f"Invalid scenario: {error}") from error


async def save_upload(upload: AsyncReadable, destination: Path, max_bytes: int) -> str:
    """Stream an upload to a private file while enforcing size and hashing bytes."""
    digest = hashlib.sha256()
    size = 0
    with destination.open("wb") as output:
        while chunk := await upload.read(1024 * 1024):
            size += len(chunk)
            if size > max_bytes:
                raise InvalidJobInput(f"audio size exceeds {max_bytes} bytes")
            digest.update(chunk)
            output.write(chunk)
    return digest.hexdigest()


class JobService:
    """Coordinate one local evaluation job without depending on FastAPI types.

    Files are staged before database insertion and removed on every failed create.
    Expected caller and provider failures use typed exceptions; SQLite and filesystem
    failures retain their original types for centralized logging and 503 translation.
    """

    def __init__(
        self,
        settings: Settings,
        store: Store,
        validator: MediaValidator,
        media_root: Path,
        temp_root: Path,
    ) -> None:
        self.settings = settings
        self.store = store
        self.validator = validator
        self.media_root = media_root
        self.temp_root = temp_root

    async def create_job(self, command: CreateJobCommand) -> CreateJobResult:
        """Validate and persist an upload, cleaning staged media on any failure."""
        if command.idempotency_key and len(command.idempotency_key) > 128:
            raise InvalidJobInput("Idempotency-Key must not exceed 128 characters")
        if command.trusted_reference and len(command.trusted_reference) > MAX_REFERENCE_CHARS:
            raise InvalidJobInput("trusted_reference exceeds the 1,000,000 character limit")
        profile = load_profile(command.profile_json, command.profile_id)
        segments = load_segments(command.transcript_json) if command.transcript_json else None
        suffix = Path(command.original_name).suffix.lower()
        job_id = str(uuid.uuid4())
        descriptor, temporary_name = tempfile.mkstemp(prefix="upload-", dir=self.temp_root)
        os.close(descriptor)
        temporary = Path(temporary_name)
        final_path: Path | None = None
        committed = False
        try:
            media_hash = await save_upload(
                command.audio, temporary, self.settings.max_upload_bytes
            )
            profile_digest = profile_hash(profile)
            transcript_canonical = json.dumps(
                [item.model_dump(mode="json") for item in segments] if segments else None,
                sort_keys=True,
                ensure_ascii=False,
            )
            payload_hash = hashlib.sha256(
                (
                    f"{media_hash}:{profile_digest}:{transcript_canonical}:"
                    f"{command.trusted_reference or ''}:{command.reference_attested}"
                ).encode()
            ).hexdigest()
            if command.idempotency_key:
                existing = self.store.find_by_idempotency_key(command.idempotency_key)
                if existing is not None:
                    if existing["deleted_at"]:
                        raise JobGone("Idempotency key refers to a deleted job")
                    if existing["payload_hash"] != payload_hash:
                        raise JobConflict("Idempotency key was already used with other inputs")
                    return CreateJobResult(existing, created=False)
            try:
                metadata = self.validator.validate(temporary, command.original_name)
                if segments:
                    validate_transcript_segments(segments, metadata.duration_seconds)
            except (MediaError, ValueError) as error:
                raise InvalidJobInput(str(error)) from error
            final_dir = self.media_root / job_id
            final_dir.mkdir(mode=0o700)
            final_path = final_dir / f"original{suffix}"
            shutil.move(str(temporary), final_path)
            status, detail = self._initial_status(bool(segments))
            values = job_values(
                job_id=job_id,
                idempotency_key=command.idempotency_key,
                payload_hash=payload_hash,
                status=status,
                status_detail=detail,
                original_name=Path(command.original_name).name,
                media_path=final_path,
                media=metadata.model_dump(mode="json"),
                profile=profile.model_dump(mode="json"),
                profile_hash=profile_digest,
                transcript=(
                    [item.model_dump(mode="json") for item in segments] if segments else None
                ),
                trusted_reference=(
                    command.trusted_reference.strip() if command.trusted_reference else None
                ),
                reference_attested=command.reference_attested,
            )
            try:
                job = self.store.create_job(values)
            except sqlite3.IntegrityError as error:
                job = self._resolve_create_conflict(command.idempotency_key, payload_hash, error)
                return CreateJobResult(job, created=False)
            committed = True
            return CreateJobResult(job, created=True)
        finally:
            _cleanup_staged_media(temporary)
            if final_path is not None and not committed:
                _cleanup_staged_media(final_path, remove_parent=True)

    def create_demo(self) -> dict[str, Any]:
        """Create a labelled synthetic job and remove its WAV if persistence fails."""
        job_id = str(uuid.uuid4())
        final_dir = self.media_root / job_id
        final_dir.mkdir(mode=0o700)
        final_path = final_dir / "synthetic-demo.wav"
        committed = False
        try:
            with wave.open(str(final_path), "wb") as audio:
                audio.setnchannels(1)
                audio.setsampwidth(2)
                audio.setframerate(8_000)
                audio.writeframes(b"\x00\x00" * 8_000 * 8)
            profile = get_preset("dental-appointment")
            segments = [
                Segment(
                    id="demo-1",
                    speaker="customer",
                    start=0,
                    end=3,
                    text="I need a cleaning appointment next Tuesday.",
                    precision="manual",
                ),
                Segment(
                    id="demo-2",
                    speaker="agent",
                    start=3,
                    end=7,
                    text="I can help with a cleaning appointment next Tuesday.",
                    precision="manual",
                ),
            ]
            digest = profile_hash(profile)
            job = self.store.create_job(
                job_values(
                    job_id=job_id,
                    idempotency_key=None,
                    payload_hash=hashlib.sha256(job_id.encode()).hexdigest(),
                    status="review_ready",
                    status_detail="Synthetic demo transcript and silent audio",
                    original_name="synthetic-demo.wav",
                    media_path=final_path,
                    media={
                        "duration_seconds": 8,
                        "channels": 1,
                        "sample_rate": 8_000,
                        "codec": "pcm",
                        "size_bytes": final_path.stat().st_size,
                        "format_name": "wav",
                    },
                    profile=profile.model_dump(mode="json"),
                    profile_hash=digest,
                    transcript=[item.model_dump(mode="json") for item in segments],
                    fixture=True,
                )
            )
            committed = True
            return job
        finally:
            if not committed:
                _cleanup_staged_media(final_path, remove_parent=True)

    def get_job(self, job_id: str) -> dict[str, Any]:
        """Return an active job or raise a typed not-found/deleted error."""
        try:
            return self.store.get_job(job_id)
        except KeyError as error:
            raise JobNotFound("Job not found") from error
        except PermissionError as error:
            raise JobGone("Job was deleted") from error

    def get_audio(self, job_id: str) -> tuple[Path, str, str]:
        """Resolve readable local media and its safe response metadata."""
        job = self.get_job(job_id)
        path = Path(str(job["media_path"]))
        mime = {".wav": "audio/wav", ".mp3": "audio/mpeg", ".m4a": "audio/mp4"}.get(
            path.suffix.lower()
        )
        if mime is None or not path.is_file():
            raise MediaUnavailable("Local recording is unavailable")
        return path, mime, str(job["original_name"])

    def save_transcript(self, job_id: str, segments: list[Segment]) -> dict[str, Any]:
        """Validate and persist a new immutable transcript revision."""
        if not segments:
            raise InvalidJobInput("transcript must contain at least one segment")
        if len(segments) > MAX_TRANSCRIPT_SEGMENTS:
            raise InvalidJobInput("transcript exceeds the 1,000 segment limit")
        job = self.get_job(job_id)
        try:
            validate_transcript_segments(segments, float(job["media"]["duration_seconds"]))
            return self.store.save_transcript(
                job_id,
                json.dumps(
                    [item.model_dump(mode="json") for item in segments], ensure_ascii=False
                ),
            )
        except ValueError as error:
            raise InvalidJobInput(f"Invalid transcript: {error}") from error
        except PermissionError as error:
            raise JobGone("Job was deleted") from error

    def evaluate(self, job_id: str) -> dict[str, Any]:
        """Create a versioned evidence report, optionally using the gated provider."""
        job = self.get_job(job_id)
        if not job["transcript"]:
            raise JobConflict("A reviewed transcript is required before evaluation")
        profile = ScenarioProfile.model_validate(job["profile"])
        segments = TypeAdapter(list[Segment]).validate_python(job["transcript"])
        report = evaluate_transcript(
            segments,
            profile,
            str(job["profile_hash"]),
            run_version=int(job["run_version"]) + 1,
            transcript_revision=int(job["transcript_revision"]),
            fixture=bool(job["fixture"]),
            trusted_reference=job["trusted_reference_text"],
            reference_attested=bool(job["reference_attested"]),
        )
        if self.settings.gemini_api_key and self.settings.gemini_free_tier_confirmed:
            try:
                with GeminiAdapter(
                    self.settings.gemini_api_key, self.settings.gemini_model
                ) as adapter:
                    judged = adapter.judge(segments, profile)
                deterministic_length = next(
                    item for item in report.findings if item.metric_id == "response_length"
                )
                for finding in judged.findings:
                    validate_finding_evidence(finding, segments)
                report.findings = [*judged.findings, deterministic_length]
                report.evaluator = f"gemini-schema+deterministic-v1:{self.settings.gemini_model}"
            except (ProviderError, ValidationError, ValueError) as error:
                try:
                    self.store.update(
                        job_id,
                        status="failed",
                        status_detail=f"Schema-constrained judge failed: {error}",
                    )
                except PermissionError as deleted_error:
                    raise JobGone("Job was deleted") from deleted_error
                raise ProviderUnavailable(f"Schema-constrained judge failed: {error}") from error
        try:
            return self.store.save_report(job_id, report.model_dump_json(), report.run_version)
        except PermissionError as error:
            raise JobGone("Job was deleted") from error

    def export(self, job_id: str) -> dict[str, Any]:
        """Build a self-contained export from a completed job and its history."""
        job = self.get_job(job_id)
        if not job["report"]:
            raise JobConflict("No completed report is available")
        return {
            "schema_version": "1.0",
            "job": job,
            "report": job["report"],
            "history": self.store.get_history(job_id),
            "external_provider_deletion": (
                "Gemini inline requests are not managed by local deletion; "
                "consult the provider data policy."
                if job["provider_model"]
                else "No external provider was used for this run."
            ),
        }

    def delete(self, job_id: str) -> dict[str, Any]:
        """Delete local job content and block late worker writes."""
        try:
            result = self.store.delete_job(job_id)
        except KeyError as error:
            raise JobNotFound("Job not found") from error
        except PermissionError as error:
            raise JobGone("Job was already deleted") from error
        result["external_provider_limit"] = (
            "Local deletion cannot delete content retained by an external provider."
        )
        return result

    def _initial_status(self, has_segments: bool) -> tuple[str, str]:
        if has_segments:
            return (
                "review_ready",
                "Manual transcript imported; review roles and evidence before evaluation",
            )
        if not self.settings.gemini_api_key:
            return "needs_transcript", "GEMINI_API_KEY is not configured"
        if not self.settings.gemini_free_tier_confirmed:
            return (
                "needs_configuration",
                "Confirm GEMINI_FREE_TIER_CONFIRMED only after verifying the project billing tier",
            )
        if self.store.pending_count() >= self.settings.max_pending_jobs:
            raise QueueFull("Local processing queue is full; retry later")
        return "queued", "Waiting for the single local transcription worker"

    def _resolve_create_conflict(
        self, idempotency_key: str | None, payload_hash: str, error: sqlite3.IntegrityError
    ) -> dict[str, Any]:
        existing = (
            self.store.find_by_idempotency_key(idempotency_key) if idempotency_key else None
        )
        if existing is None:
            raise JobConflict("Concurrent job creation conflict") from error
        if existing["deleted_at"]:
            raise JobGone("Idempotency key refers to a deleted job") from error
        if existing["payload_hash"] != payload_hash:
            raise JobConflict("Idempotency key was already used with other inputs") from error
        return existing
