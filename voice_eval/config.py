from __future__ import annotations

from pathlib import Path

from pydantic import AliasChoices, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_prefix="VOICE_EVAL_", extra="ignore", case_sensitive=False
    )

    data_dir: Path = Path("data")
    database_path: Path | None = None
    host: str = "127.0.0.1"
    port: int = 8000
    max_upload_bytes: int = 100 * 1024 * 1024
    max_duration_seconds: float = 20 * 60
    max_pending_jobs: int = 20
    retention_hours: int = 24
    ffprobe_path: str = "ffprobe"
    ffmpeg_path: str = "ffmpeg"
    start_worker: bool = True
    gemini_api_key: str | None = Field(default=None, validation_alias="GEMINI_API_KEY")
    gemini_model: str = Field(default="gemini-3.5-flash-lite", validation_alias="GEMINI_MODEL")
    gemini_free_tier_confirmed: bool = Field(
        default=False,
        validation_alias=AliasChoices(
            "GEMINI_FREE_TIER_CONFIRMED", "VOICE_EVAL_GEMINI_FREE_TIER_CONFIRMED"
        ),
    )
    free_only: bool = True
    allowed_hosts: set[str] = {"127.0.0.1", "localhost", "testserver"}

    @model_validator(mode="after")
    def finalize_paths_and_provider_policy(self) -> Settings:
        self.data_dir = self.data_dir.resolve()
        if self.database_path is None:
            self.database_path = self.data_dir / "voice_eval.sqlite3"
        else:
            self.database_path = self.database_path.resolve()
        if self.host not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("VOICE_EVAL_HOST must be loopback-only")
        if self.free_only and self.gemini_model not in {
            "gemini-3.5-flash-lite",
            "gemini-3.5-flash",
        }:
            raise ValueError("GEMINI_MODEL is not in the reviewed free-tier allowlist")
        return self
