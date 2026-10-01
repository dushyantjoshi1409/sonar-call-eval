"""FastAPI composition root for the local voice evaluation application."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from voice_eval.api.errors import install_exception_handlers
from voice_eval.api.jobs import router as jobs_router
from voice_eval.api.metrics import router as metrics_router
from voice_eval.api.pages import router as pages_router
from voice_eval.api.profiles import router as profiles_router
from voice_eval.config import Settings
from voice_eval.runtime import build_runtime

ROOT = Path(__file__).parent
logger = logging.getLogger(__name__)
RequestHandler = Callable[[Request], Awaitable[Response]]


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the ASGI app without opening storage or starting background work.

    Process-owned resources are created and cleaned inside FastAPI's lifespan,
    which keeps imports side-effect free and gives tests an isolated runtime.
    """
    configured = settings or Settings()

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        runtime = build_runtime(configured)
        application.state.runtime = runtime
        for stale_upload in runtime.temp_root.glob("upload-*"):
            if not stale_upload.is_file():
                continue
            try:
                stale_upload.unlink()
            except OSError:
                logger.warning("Could not remove stale upload %s", stale_upload.name)
        worker_task: asyncio.Task[None] | None = None
        if configured.start_worker:
            worker_task = asyncio.create_task(runtime.worker.run(), name="voice-eval-worker")
        try:
            yield
        finally:
            if worker_task is not None:
                runtime.worker.stop()
                await worker_task

    application = FastAPI(
        title="Persistence Voice Eval",
        version="0.2.0",
        lifespan=lifespan,
    )

    @application.middleware("http")
    async def same_origin(request: Request, call_next: RequestHandler) -> Response:
        """Reject non-loopback hosts and cross-origin state-changing requests."""
        host = request.url.hostname or ""
        if host not in configured.allowed_hosts:
            return JSONResponse({"detail": "Host is not allowed"}, status_code=400)
        origin = request.headers.get("origin")
        if origin and request.method not in {"GET", "HEAD", "OPTIONS"}:
            expected = f"{request.url.scheme}://{request.headers.get('host', '')}".rstrip("/")
            if origin.rstrip("/") != expected:
                return JSONResponse(
                    {"detail": "Cross-origin mutation is not allowed"}, status_code=403
                )
        return await call_next(request)

    install_exception_handlers(application)
    application.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
    application.include_router(pages_router)
    application.include_router(profiles_router)
    application.include_router(jobs_router)
    application.include_router(metrics_router)
    return application


app = create_app()
