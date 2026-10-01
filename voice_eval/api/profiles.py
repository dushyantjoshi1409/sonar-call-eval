"""Scenario profile and synthetic demonstration routes."""

from fastapi import APIRouter

from voice_eval.api.dependencies import JobServiceDependency
from voice_eval.api.schemas import PublicJob
from voice_eval.domain import ScenarioProfile
from voice_eval.profiles import list_presets

router = APIRouter(prefix="/api", tags=["profiles"])


@router.get("/profiles")
async def profiles() -> list[ScenarioProfile]:
    """List versioned built-in scenario presets."""
    return list_presets()


@router.post("/demo", response_model=PublicJob, status_code=201)
async def create_demo(jobs: JobServiceDependency) -> PublicJob:
    """Create a visibly labelled synthetic fixture without a provider call."""
    return PublicJob.from_record(jobs.create_demo())
