"""Durable single-worker transcription queue and recovery behavior."""

from __future__ import annotations

import asyncio
import json
import logging
from contextlib import suppress
from pathlib import Path
from typing import Any

from voice_eval.config import Settings
from voice_eval.evaluation import validate_transcript_segments
from voice_eval.provider_sessions import (
    ENVIRONMENT_PROVIDER_HANDLE,
    ProviderSessionVault,
    environment_provider_config,
)
from voice_eval.providers import ProviderError, create_provider_adapter
from voice_eval.store import Store

logger = logging.getLogger(__name__)


class Worker:
    """Persisted single-consumer queue for optional Gemini transcription.

    The outer loop catches unexpected exceptions so one job cannot terminate the
    process worker, logs the traceback, and exposes only an exception type to users.
    """

    def __init__(self, store: Store, settings: Settings, sessions: ProviderSessionVault) -> None:
        self.store = store
        self.settings = settings
        self.sessions = sessions
        self._stopping = asyncio.Event()

    async def run(self) -> None:
        """Recover interrupted work, sweep retention, and process queued jobs."""
        self.store.recover_interrupted()
        self.store.sweep_expired(self.settings.retention_hours)
        while not self._stopping.is_set():
            job = self.store.claim_next()
            if job is None:
                with suppress(TimeoutError):
                    await asyncio.wait_for(self._stopping.wait(), timeout=0.5)
                continue
            try:
                await asyncio.to_thread(self._transcribe, job)
            except Exception as error:
                logger.exception("Unexpected worker failure for job %s", job["id"])
                with suppress(PermissionError):
                    self.store.update(
                        str(job["id"]),
                        status="failed",
                        status_detail=f"internal_worker_error: {type(error).__name__}",
                    )

    def stop(self) -> None:
        """Request cooperative shutdown after any active provider call returns."""
        self._stopping.set()

    def _transcribe(self, job: dict[str, Any]) -> None:
        handle = job["provider_handle"]
        if handle == ENVIRONMENT_PROVIDER_HANDLE or handle is None:
            provider = environment_provider_config(self.settings)
        else:
            provider = self.sessions.resolve_handle(str(handle))
        if provider is None:
            self.store.update(
                str(job["id"]),
                status="failed" if handle else "needs_transcript",
                status_detail=(
                    "provider_session_unavailable: reconnect and create a new evaluation"
                    if handle
                    else "Connect an audio-capable provider or import a reviewed transcript"
                ),
            )
            return
        suffix = Path(str(job["media_path"])).suffix.lower()
        mime = {".wav": "audio/wav", ".mp3": "audio/mpeg", ".m4a": "audio/mp4"}[suffix]
        try:
            with create_provider_adapter(
                provider, ffmpeg_path=self.settings.ffmpeg_path
            ) as adapter:
                result = adapter.transcribe(Path(str(job["media_path"])), mime)
            duration = float(job["media"]["duration_seconds"])
            try:
                validate_transcript_segments(result.segments, duration)
            except ValueError as error:
                message = f"Provider returned invalid transcript segments: {error}"
                raise ProviderError(message) from error
            with suppress(PermissionError):
                transcript_json = json.dumps(
                    [item.model_dump(mode="json") for item in result.segments],
                    ensure_ascii=False,
                )
                self.store.save_transcript(str(job["id"]), transcript_json)
                self.store.update(
                    str(job["id"]),
                    status_detail="Model-estimated transcript requires speaker and timing review",
                    provider_model=provider.transcription_model,
                )
        except ProviderError as error:
            with suppress(PermissionError):
                self.store.update(
                    str(job["id"]),
                    status="failed",
                    status_detail=f"{error.code}: {error}",
                )
