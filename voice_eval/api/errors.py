"""Central translation of typed application and local resource failures to HTTP."""

import logging
import sqlite3

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from voice_eval.services import (
    InvalidJobInput,
    JobConflict,
    JobGone,
    JobNotFound,
    JobServiceError,
    MediaUnavailable,
    ProviderUnavailable,
    QueueFull,
)

logger = logging.getLogger(__name__)


def install_exception_handlers(app: FastAPI) -> None:
    """Install safe HTTP mappings while retaining server-side exception causes."""

    @app.exception_handler(JobServiceError)
    async def handle_job_error(_: Request, error: JobServiceError) -> JSONResponse:
        status = 500
        if isinstance(error, InvalidJobInput):
            status = 422
        elif isinstance(error, JobNotFound):
            status = 404
        elif isinstance(error, (JobGone, MediaUnavailable)):
            status = 410
        elif isinstance(error, JobConflict):
            status = 409
        elif isinstance(error, QueueFull):
            status = 429
        elif isinstance(error, ProviderUnavailable):
            status = 503
        return JSONResponse({"detail": str(error)}, status_code=status)

    @app.exception_handler(sqlite3.Error)
    @app.exception_handler(OSError)
    async def handle_local_resource_error(_: Request, error: Exception) -> JSONResponse:
        logger.exception("Local storage operation failed", exc_info=error)
        return JSONResponse({"detail": "Local storage operation failed"}, status_code=503)
