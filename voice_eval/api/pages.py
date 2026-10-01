"""Server-rendered browser pages for upload and evidence review."""

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from voice_eval.api.dependencies import JobServiceDependency, RuntimeDependency
from voice_eval.api.schemas import PublicJob
from voice_eval.profiles import list_presets

ROOT = Path(__file__).resolve().parents[1]
templates = Jinja2Templates(directory=ROOT / "templates")
router = APIRouter(tags=["pages"])


@router.get("/", response_class=HTMLResponse)
async def index(request: Request, runtime: RuntimeDependency) -> HTMLResponse:
    """Render the upload form and scenario presets."""
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "presets": [item.model_dump(mode="json") for item in list_presets()],
            "gemini_ready": bool(
                runtime.settings.gemini_api_key
                and runtime.settings.gemini_free_tier_confirmed
            ),
        },
    )


@router.get("/jobs/{job_id}", response_class=HTMLResponse)
async def job_page(
    request: Request, job_id: str, jobs: JobServiceDependency
) -> HTMLResponse:
    """Render transcript review, typed findings, evidence, and export controls."""
    job = PublicJob.from_record(jobs.get_job(job_id)).model_dump(mode="json")
    return templates.TemplateResponse(request, "job.html", {"job": job})
