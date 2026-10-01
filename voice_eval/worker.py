from __future__ import annotations

import asyncio
import json
from contextlib import suppress
from pathlib import Path
from typing import Any

from voice_eval.config import Settings
from voice_eval.evaluation import validate_transcript_segments
from voice_eval.providers import GeminiAdapter, ProviderError
from voice_eval.store import Store


class Worker:
    def __init__(self, store: Store, settings: Settings) -> None:
        self.store = store
        self.settings = settings
        self._stopping = asyncio.Event()

    async def run(self) -> None:
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
                with suppress(PermissionError):
                    self.store.update(
                        str(job["id"]),
                        status="failed",
                        status_detail=f"internal_worker_error: {type(error).__name__}",
                    )

    def stop(self) -> None:
        self._stopping.set()

    def _transcribe(self, job: dict[str, Any]) -> None:
        if not self.settings.gemini_api_key or not self.settings.gemini_free_tier_confirmed:
            self.store.update(
                str(job["id"]),
                status="needs_transcript",
                status_detail="Gemini free-tier configuration is incomplete",
            )
            return
        adapter = GeminiAdapter(self.settings.gemini_api_key, self.settings.gemini_model)
        suffix = Path(str(job["media_path"])).suffix.lower()
        mime = {".wav": "audio/wav", ".mp3": "audio/mpeg", ".m4a": "audio/mp4"}[suffix]
        try:
            result = adapter.transcribe(Path(str(job["media_path"])), mime)
            duration = float(job["media"]["duration_seconds"])
            try:
                validate_transcript_segments(result.segments, duration)
            except ValueError as error:
                message = f"Gemini returned invalid transcript segments: {error}"
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
                    provider_model=self.settings.gemini_model,
                )
        except ProviderError as error:
            with suppress(PermissionError):
                self.store.update(
                    str(job["id"]),
                    status="failed",
                    status_detail=f"{error.code}: {error}",
                )
