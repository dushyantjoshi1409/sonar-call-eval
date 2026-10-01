"""JSON and media routes for the complete evaluation job lifecycle."""

from typing import Annotated

from fastapi import APIRouter, File, Form, Header, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from pydantic import Field

from voice_eval.api.dependencies import JobServiceDependency
from voice_eval.api.schemas import DeleteResponse, ExportResponse, PublicJob
from voice_eval.domain import Segment
from voice_eval.services import CreateJobCommand

router = APIRouter(prefix="/api/jobs", tags=["jobs"])
TranscriptBody = Annotated[list[Segment], Field(min_length=1, max_length=1_000)]


@router.post("", response_model=PublicJob, status_code=201)
async def create_job(
    response: Response,
    jobs: JobServiceDependency,
    audio: Annotated[UploadFile, File()],
    profile_json: Annotated[str | None, Form()] = None,
    profile_id: Annotated[str | None, Form()] = None,
    transcript_json: Annotated[str | None, Form()] = None,
    trusted_reference: Annotated[str | None, Form()] = None,
    reference_attested: Annotated[bool, Form()] = False,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> PublicJob:
    """Create a validated local job or replay an identical idempotent request."""
    result = await jobs.create_job(
        CreateJobCommand(
            audio=audio,
            original_name=audio.filename or "recording",
            profile_json=profile_json,
            profile_id=profile_id,
            transcript_json=transcript_json,
            trusted_reference=trusted_reference,
            reference_attested=reference_attested,
            idempotency_key=idempotency_key,
        )
    )
    response.status_code = 201 if result.created else 200
    return PublicJob.from_record(result.job)


@router.get("/{job_id}", response_model=PublicJob)
async def get_job(job_id: str, jobs: JobServiceDependency) -> PublicJob:
    """Return current persisted state for one active job."""
    return PublicJob.from_record(jobs.get_job(job_id))


@router.get("/{job_id}/audio", response_class=FileResponse)
async def audio(job_id: str, jobs: JobServiceDependency) -> FileResponse:
    """Stream the preserved source recording with range request support."""
    path, mime, original_name = jobs.get_audio(job_id)
    return FileResponse(path, media_type=mime, filename=original_name)


@router.put("/{job_id}/transcript", response_model=PublicJob)
async def update_transcript(
    job_id: str, segments: TranscriptBody, jobs: JobServiceDependency
) -> PublicJob:
    """Persist reviewed speakers and words as a new transcript revision."""
    return PublicJob.from_record(jobs.save_transcript(job_id, segments))


@router.post("/{job_id}/evaluate", response_model=PublicJob)
async def evaluate(job_id: str, jobs: JobServiceDependency) -> PublicJob:
    """Create a new immutable evidence-linked report version."""
    return PublicJob.from_record(jobs.evaluate(job_id))


@router.get("/{job_id}/export", response_model=ExportResponse)
async def export(job_id: str, jobs: JobServiceDependency) -> JSONResponse:
    """Download a validated report with transcript and run history."""
    payload = jobs.export(job_id)
    payload["job"] = PublicJob.from_record(payload["job"]).model_dump(mode="json")
    validated = ExportResponse.model_validate(payload)
    return JSONResponse(
        validated.model_dump(mode="json"),
        headers={"Content-Disposition": f'attachment; filename="voice-eval-{job_id}.json"'},
    )


@router.delete("/{job_id}", response_model=DeleteResponse)
async def delete(job_id: str, jobs: JobServiceDependency) -> DeleteResponse:
    """Delete local recording, transcript revisions, and reports."""
    return DeleteResponse.model_validate(jobs.delete(job_id))
