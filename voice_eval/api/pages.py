"""Server-rendered browser pages for upload and evidence review."""

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from voice_eval.api.dependencies import JobServiceDependency, RuntimeDependency
from voice_eval.api.schemas import PublicJob
from voice_eval.profiles import list_presets
from voice_eval.provider_sessions import SESSION_COOKIE_NAME, environment_provider_config
from voice_eval.regression import regression_cases

ROOT = Path(__file__).resolve().parents[1]
templates = Jinja2Templates(directory=ROOT / "templates")
router = APIRouter(tags=["pages"])


@router.get("/", response_class=HTMLResponse)
async def index(request: Request, runtime: RuntimeDependency) -> HTMLResponse:
    """Render the upload form and scenario presets."""
    environment_provider = environment_provider_config(runtime.settings)
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "presets": [item.model_dump(mode="json") for item in list_presets()],
            "provider_session": runtime.sessions.public_metadata(
                request.cookies.get(SESSION_COOKIE_NAME)
            ),
            "environment_provider": (
                environment_provider.public_metadata() if environment_provider else None
            ),
        },
    )


@router.get("/jobs/{job_id}", response_class=HTMLResponse)
async def job_page(request: Request, job_id: str, jobs: JobServiceDependency) -> HTMLResponse:
    """Render transcript review, typed findings, evidence, and export controls."""
    job = PublicJob.from_record(jobs.get_job(job_id)).model_dump(mode="json")
    return templates.TemplateResponse(request, "job.html", {"job": job})


@router.get("/regression", response_class=HTMLResponse)
async def regression_page(request: Request, runtime: RuntimeDependency) -> HTMLResponse:
    """Render authored synthetic cases and recent baseline-compatible results."""
    cases = [
        {
            "id": case.id,
            "name": case.name,
            "category": case.category,
            "purpose": case.purpose,
            "expectations": {
                metric: {"verdict": verdict, "note": case.expectation_notes[metric]}
                for metric, verdict in case.expectations.items()
            },
        }
        for case in regression_cases()
    ]
    return templates.TemplateResponse(
        request,
        "regression.html",
        {"cases": cases, "runs": runtime.regressions.list_runs()},
    )
