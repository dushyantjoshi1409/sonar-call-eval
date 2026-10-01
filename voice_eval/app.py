from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
import uuid
import wave
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Annotated, Any

from fastapi import FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import TypeAdapter, ValidationError

from voice_eval.config import Settings
from voice_eval.domain import ScenarioProfile, Segment
from voice_eval.evaluation import (
    evaluate_transcript,
    validate_finding_evidence,
    validate_transcript_segments,
)
from voice_eval.media import MediaError, MediaValidator
from voice_eval.metrics import character_error_rate, word_error_rate
from voice_eval.profiles import get_preset, list_presets, profile_hash, validate_profile
from voice_eval.providers import GeminiAdapter, ProviderError
from voice_eval.store import Store, job_values
from voice_eval.worker import Worker

ROOT = Path(__file__).parent
MAX_PROFILE_JSON_CHARS = 100_000
MAX_TRANSCRIPT_JSON_CHARS = 1_000_000
MAX_TRANSCRIPT_SEGMENTS = 1_000
MAX_REFERENCE_CHARS = 1_000_000


def _public_job(job: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in job.items() if key not in {"media_path", "payload_hash"}}


def _load_segments(raw: str | list[dict[str, Any]]) -> list[Segment]:
    if isinstance(raw, str) and len(raw) > MAX_TRANSCRIPT_JSON_CHARS:
        raise ValueError("transcript JSON exceeds the 1,000,000 character limit")
    value = json.loads(raw) if isinstance(raw, str) else raw
    segments = TypeAdapter(list[Segment]).validate_python(value)
    if not segments:
        raise ValueError("transcript must contain at least one segment")
    if len(segments) > MAX_TRANSCRIPT_SEGMENTS:
        raise ValueError("transcript exceeds the 1,000 segment limit")
    return segments


def _profile_from_form(profile_json: str | None, profile_id: str | None) -> ScenarioProfile:
    if profile_json:
        if len(profile_json) > MAX_PROFILE_JSON_CHARS:
            raise ValueError("profile JSON exceeds the 100,000 character limit")
        value = json.loads(profile_json)
        if not isinstance(value, dict):
            raise ValueError("profile_json must be an object")
        return validate_profile(value)
    return get_preset(profile_id or "generic-conversation")


async def _save_upload(upload: UploadFile, destination: Path, max_bytes: int) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    with destination.open("wb") as output:
        while chunk := await upload.read(1024 * 1024):
            size += len(chunk)
            if size > max_bytes:
                raise MediaError(f"audio size exceeds {max_bytes} bytes")
            digest.update(chunk)
            output.write(chunk)
    return size, digest.hexdigest()


def create_app(settings: Settings | None = None) -> FastAPI:
    configured = settings or Settings()
    configured.data_dir.mkdir(parents=True, exist_ok=True)
    configured.data_dir.chmod(0o700)
    media_root = configured.data_dir / "media"
    temp_root = configured.data_dir / "tmp"
    media_root.mkdir(parents=True, exist_ok=True)
    temp_root.mkdir(parents=True, exist_ok=True)
    media_root.chmod(0o700)
    temp_root.chmod(0o700)
    store = Store(configured.database_path or configured.data_dir / "voice_eval.sqlite3")
    validator = MediaValidator(
        ffprobe_path=configured.ffprobe_path,
        ffmpeg_path=configured.ffmpeg_path,
        max_bytes=configured.max_upload_bytes,
        max_duration_seconds=configured.max_duration_seconds,
    )
    worker = Worker(store, configured)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        task: asyncio.Task[None] | None = None
        for stale_upload in temp_root.glob("upload-*"):
            if stale_upload.is_file():
                stale_upload.unlink(missing_ok=True)
        if configured.start_worker:
            task = asyncio.create_task(worker.run())
        try:
            yield
        finally:
            if task is not None:
                worker.stop()
                await task

    app = FastAPI(title="Persistence Voice Eval", version="0.1.0", lifespan=lifespan)
    app.state.settings = configured
    app.state.store = store
    app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
    templates = Jinja2Templates(directory=ROOT / "templates")

    @app.middleware("http")
    async def same_origin(request: Request, call_next: Any) -> Any:
        host = request.url.hostname or ""
        if host not in configured.allowed_hosts:
            return JSONResponse({"detail": "Host is not allowed"}, status_code=400)
        origin = request.headers.get("origin")
        if origin and request.method not in {"GET", "HEAD", "OPTIONS"}:
            expected_origins = {
                f"{request.url.scheme}://{request.headers.get('host', '')}".rstrip("/")
            }
            if origin.rstrip("/") not in expected_origins:
                return JSONResponse(
                    {"detail": "Cross-origin mutation is not allowed"}, status_code=403
                )
        return await call_next(request)

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(
            request,
            "index.html",
            {
                "presets": [item.model_dump(mode="json") for item in list_presets()],
                "gemini_ready": bool(
                    configured.gemini_api_key and configured.gemini_free_tier_confirmed
                ),
            },
        )

    @app.get("/jobs/{job_id}", response_class=HTMLResponse)
    async def job_page(request: Request, job_id: str) -> HTMLResponse:
        try:
            job = store.get_job(job_id)
        except KeyError as error:
            raise HTTPException(404, "Job not found") from error
        except PermissionError as error:
            raise HTTPException(410, "Job was deleted") from error
        return templates.TemplateResponse(request, "job.html", {"job": _public_job(job)})

    @app.get("/api/profiles")
    async def profiles() -> list[dict[str, Any]]:
        return [item.model_dump(mode="json") for item in list_presets()]

    @app.post("/api/jobs", status_code=201)
    async def create_job(
        audio: Annotated[UploadFile, File()],
        profile_json: Annotated[str | None, Form()] = None,
        profile_id: Annotated[str | None, Form()] = None,
        transcript_json: Annotated[str | None, Form()] = None,
        trusted_reference: Annotated[str | None, Form()] = None,
        reference_attested: Annotated[bool, Form()] = False,
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    ) -> JSONResponse:
        if idempotency_key and len(idempotency_key) > 128:
            raise HTTPException(422, "Idempotency-Key must not exceed 128 characters")
        if trusted_reference and len(trusted_reference) > MAX_REFERENCE_CHARS:
            raise HTTPException(422, "trusted_reference exceeds the 1,000,000 character limit")
        try:
            profile = _profile_from_form(profile_json, profile_id)
            segments = _load_segments(transcript_json) if transcript_json else None
        except (ValueError, json.JSONDecodeError, ValidationError) as error:
            raise HTTPException(422, f"Invalid scenario or transcript: {error}") from error
        suffix = Path(audio.filename or "recording").suffix.lower()
        job_id = str(uuid.uuid4())
        descriptor, temporary_name = tempfile.mkstemp(prefix="upload-", dir=temp_root)
        os.close(descriptor)
        temporary = Path(temporary_name)
        final_path: Path | None = None
        committed = False
        try:
            _, media_hash = await _save_upload(audio, temporary, configured.max_upload_bytes)
            profile_digest = profile_hash(profile)
            transcript_canonical = json.dumps(
                [item.model_dump(mode="json") for item in segments] if segments else None,
                sort_keys=True,
                ensure_ascii=False,
            )
            payload_hash = hashlib.sha256(
                (
                    f"{media_hash}:{profile_digest}:{transcript_canonical}:"
                    f"{trusted_reference or ''}:{reference_attested}"
                ).encode()
            ).hexdigest()
            if idempotency_key:
                existing = store.find_by_idempotency_key(idempotency_key)
                if existing is not None:
                    temporary.unlink(missing_ok=True)
                    if existing["deleted_at"]:
                        raise HTTPException(410, "Idempotency key refers to a deleted job")
                    if existing["payload_hash"] != payload_hash:
                        raise HTTPException(
                            409, "Idempotency key was already used with other inputs"
                        )
                    return JSONResponse(_public_job(existing), status_code=200)
            metadata = validator.validate(temporary, audio.filename or f"recording{suffix}")
            if segments:
                validate_transcript_segments(segments, metadata.duration_seconds)
            final_dir = media_root / job_id
            final_dir.mkdir(mode=0o700)
            final_path = final_dir / f"original{suffix}"
            shutil.move(str(temporary), final_path)
            if segments:
                status = "review_ready"
                detail = "Manual transcript imported; review roles and evidence before evaluation"
            elif not configured.gemini_api_key:
                status = "needs_transcript"
                detail = "GEMINI_API_KEY is not configured"
            elif not configured.gemini_free_tier_confirmed:
                status = "needs_configuration"
                detail = (
                    "Confirm GEMINI_FREE_TIER_CONFIRMED only after verifying "
                    "the project billing tier"
                )
            else:
                if store.pending_count() >= configured.max_pending_jobs:
                    raise HTTPException(429, "Local processing queue is full; retry later")
                status = "queued"
                detail = "Waiting for the single local transcription worker"
            values = job_values(
                job_id=job_id,
                idempotency_key=idempotency_key,
                payload_hash=payload_hash,
                status=status,
                status_detail=detail,
                original_name=Path(audio.filename or "recording").name,
                media_path=final_path,
                media=metadata.model_dump(mode="json"),
                profile=profile.model_dump(mode="json"),
                profile_hash=profile_digest,
                transcript=(
                    [item.model_dump(mode="json") for item in segments] if segments else None
                ),
                trusted_reference=trusted_reference.strip() if trusted_reference else None,
                reference_attested=reference_attested,
            )
            try:
                job = store.create_job(values)
            except sqlite3.IntegrityError as error:
                existing = (
                    store.find_by_idempotency_key(idempotency_key) if idempotency_key else None
                )
                if existing is None:
                    raise HTTPException(409, "Concurrent job creation conflict") from error
                if existing["deleted_at"]:
                    raise HTTPException(
                        410, "Idempotency key refers to a deleted job"
                    ) from error
                if existing["payload_hash"] != payload_hash:
                    raise HTTPException(
                        409, "Idempotency key was already used with other inputs"
                    ) from error
                return JSONResponse(_public_job(existing), status_code=200)
            committed = True
            return JSONResponse(_public_job(job), status_code=201)
        except HTTPException:
            raise
        except MediaError as error:
            raise HTTPException(422, str(error)) from error
        except ValueError as error:
            raise HTTPException(422, f"Invalid transcript: {error}") from error
        finally:
            temporary.unlink(missing_ok=True)
            if final_path is not None and not committed:
                final_path.unlink(missing_ok=True)
                with suppress(OSError):
                    final_path.parent.rmdir()

    @app.post("/api/demo", status_code=201)
    async def create_demo() -> JSONResponse:
        job_id = str(uuid.uuid4())
        final_dir = media_root / job_id
        final_dir.mkdir(mode=0o700)
        final_path = final_dir / "synthetic-demo.wav"
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
        job = store.create_job(
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
        return JSONResponse(_public_job(job), status_code=201)

    @app.get("/api/jobs/{job_id}")
    async def get_job(job_id: str) -> dict[str, Any]:
        try:
            return _public_job(store.get_job(job_id))
        except KeyError as error:
            raise HTTPException(404, "Job not found") from error
        except PermissionError as error:
            raise HTTPException(410, "Job was deleted") from error

    @app.get("/api/jobs/{job_id}/audio")
    async def audio(job_id: str) -> FileResponse:
        try:
            job = store.get_job(job_id)
        except KeyError as error:
            raise HTTPException(404, "Job not found") from error
        except PermissionError as error:
            raise HTTPException(410, "Job was deleted") from error
        path = Path(job["media_path"])
        mime = {".wav": "audio/wav", ".mp3": "audio/mpeg", ".m4a": "audio/mp4"}[path.suffix]
        return FileResponse(path, media_type=mime, filename=job["original_name"])

    @app.put("/api/jobs/{job_id}/transcript")
    async def update_transcript(job_id: str, request: Request) -> dict[str, Any]:
        try:
            segments = _load_segments(await request.json())
            job = store.get_job(job_id)
            validate_transcript_segments(segments, float(job["media"]["duration_seconds"]))
            updated = store.save_transcript(
                job_id,
                json.dumps([item.model_dump(mode="json") for item in segments], ensure_ascii=False),
            )
            return _public_job(updated)
        except (ValidationError, ValueError, json.JSONDecodeError) as error:
            raise HTTPException(422, f"Invalid transcript: {error}") from error
        except KeyError as error:
            raise HTTPException(404, "Job not found") from error
        except PermissionError as error:
            raise HTTPException(410, "Job was deleted") from error

    @app.post("/api/jobs/{job_id}/evaluate")
    async def evaluate(job_id: str) -> dict[str, Any]:
        try:
            job = store.get_job(job_id)
            if not job["transcript"]:
                raise HTTPException(409, "A reviewed transcript is required before evaluation")
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
            if configured.gemini_api_key and configured.gemini_free_tier_confirmed:
                try:
                    judged = GeminiAdapter(
                        configured.gemini_api_key, configured.gemini_model
                    ).judge(segments, profile)
                    deterministic_length = next(
                        item for item in report.findings if item.metric_id == "response_length"
                    )
                    for finding in judged.findings:
                        validate_finding_evidence(finding, segments)
                    report.findings = [*judged.findings, deterministic_length]
                    report.evaluator = f"gemini-schema+deterministic-v1:{configured.gemini_model}"
                except (ProviderError, ValidationError, ValueError) as error:
                    store.update(
                        job_id,
                        status="failed",
                        status_detail=f"Schema-constrained judge failed: {error}",
                    )
                    raise HTTPException(503, f"Schema-constrained judge failed: {error}") from error
            updated = store.save_report(job_id, report.model_dump_json(), report.run_version)
            return _public_job(updated)
        except KeyError as error:
            raise HTTPException(404, "Job not found") from error
        except PermissionError as error:
            raise HTTPException(410, "Job was deleted") from error

    @app.get("/api/jobs/{job_id}/export")
    async def export(job_id: str) -> JSONResponse:
        try:
            job = store.get_job(job_id)
        except KeyError as error:
            raise HTTPException(404, "Job not found") from error
        except PermissionError as error:
            raise HTTPException(410, "Job was deleted") from error
        if not job["report"]:
            raise HTTPException(409, "No completed report is available")
        body = {
            "schema_version": "1.0",
            "job": _public_job(job),
            "report": job["report"],
            "history": store.get_history(job_id),
            "external_provider_deletion": (
                "Gemini inline requests are not managed by local deletion; "
                "consult the provider data policy."
                if job["provider_model"]
                else "No external provider was used for this run."
            ),
        }
        return JSONResponse(
            body,
            headers={"Content-Disposition": f'attachment; filename="voice-eval-{job_id}.json"'},
        )

    @app.post("/api/metrics/wer")
    async def calculate_wer(request: Request) -> dict[str, Any]:
        body = await request.json()
        if not isinstance(body, dict):
            raise HTTPException(422, "Body must be an object")
        reference = body.get("trusted_reference")
        hypothesis = body.get("hypothesis")
        if reference is not None and not isinstance(reference, str):
            raise HTTPException(422, "trusted_reference must be a string or null")
        if hypothesis is not None and not isinstance(hypothesis, str):
            raise HTTPException(422, "hypothesis must be a string or null")
        result = word_error_rate(reference, hypothesis)
        character_result = character_error_rate(reference, hypothesis)
        if result is None or character_result is None:
            if reference is None:
                reason = "MISSING_REFERENCE"
            elif hypothesis is None:
                reason = "MISSING_HYPOTHESIS"
            else:
                reason = "EMPTY_REFERENCE"
            return {"status": "UNKNOWN", "reason": reason, "wer": None, "cer": None}
        return {
            "status": "OBSERVED",
            "reason": "THRESHOLD_NOT_DEFINED",
            "wer": result,
            "cer": character_result,
        }

    @app.delete("/api/jobs/{job_id}")
    async def delete(job_id: str) -> dict[str, Any]:
        try:
            result = store.delete_job(job_id)
            result["external_provider_limit"] = (
                "Local deletion cannot delete content retained by an external provider."
            )
            return result
        except KeyError as error:
            raise HTTPException(404, "Job not found") from error
        except PermissionError as error:
            raise HTTPException(410, "Job was already deleted") from error

    return app


app = create_app()
