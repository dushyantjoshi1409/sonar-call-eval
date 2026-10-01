"""FastAPI dependency adapters for lifespan-owned runtime resources."""

from typing import Annotated

from fastapi import Depends, Request

from voice_eval.regression import RegressionService
from voice_eval.runtime import Runtime
from voice_eval.services import JobService


def get_runtime(request: Request) -> Runtime:
    """Return the runtime initialized by the active application lifespan."""
    return request.app.state.runtime  # type: ignore[no-any-return]


def get_job_service(runtime: Annotated[Runtime, Depends(get_runtime)]) -> JobService:
    """Expose job orchestration without route modules reaching into app state."""
    return runtime.jobs


def get_regression_service(
    runtime: Annotated[Runtime, Depends(get_runtime)],
) -> RegressionService:
    """Expose fixed-suite orchestration without route access to storage internals."""
    return runtime.regressions


RuntimeDependency = Annotated[Runtime, Depends(get_runtime)]
JobServiceDependency = Annotated[JobService, Depends(get_job_service)]
RegressionServiceDependency = Annotated[RegressionService, Depends(get_regression_service)]
