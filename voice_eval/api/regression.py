"""User-initiated fixed-suite regression run endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from voice_eval.api.dependencies import RegressionServiceDependency, RuntimeDependency
from voice_eval.provider_sessions import SESSION_COOKIE_NAME

router = APIRouter(prefix="/api/regression-runs", tags=["regression"])


class RegressionRunRequest(BaseModel):
    """Optional compatible baseline selection for one bounded suite run."""

    model_config = ConfigDict(extra="forbid")
    baseline_id: str | None = Field(default=None, max_length=80)


@router.get("")
def list_regression_runs(regressions: RegressionServiceDependency) -> list[dict[str, object]]:
    """List recent persisted synthetic regression runs."""
    return regressions.list_runs()


@router.post("", status_code=201)
def create_regression_run(
    body: RegressionRunRequest,
    request: Request,
    runtime: RuntimeDependency,
    regressions: RegressionServiceDependency,
) -> dict[str, object]:
    """Run the small suite using only the current session's captured provider."""
    cookie_token = request.cookies.get(SESSION_COOKIE_NAME)
    session = runtime.sessions.session_for_cookie(cookie_token)
    if cookie_token and session is None:
        raise HTTPException(401, "Provider session expired or was cleared; reconnect")
    return regressions.run(
        baseline_id=body.baseline_id,
        provider_handle=session.credential_handle if session else None,
    )
