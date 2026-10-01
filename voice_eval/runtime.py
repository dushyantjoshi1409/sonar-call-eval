"""Construction of process-owned runtime resources for FastAPI lifespan."""

from dataclasses import dataclass
from pathlib import Path

from voice_eval.config import Settings
from voice_eval.media import MediaValidator
from voice_eval.services import JobService
from voice_eval.store import Store
from voice_eval.worker import Worker


@dataclass(frozen=True, slots=True)
class Runtime:
    """Resources shared by requests and owned by one application lifespan."""

    settings: Settings
    store: Store
    jobs: JobService
    worker: Worker
    media_root: Path
    temp_root: Path


def build_runtime(settings: Settings) -> Runtime:
    """Create private directories, storage, media validation, and the local worker."""
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.data_dir.chmod(0o700)
    media_root = settings.data_dir / "media"
    temp_root = settings.data_dir / "tmp"
    media_root.mkdir(parents=True, exist_ok=True)
    temp_root.mkdir(parents=True, exist_ok=True)
    media_root.chmod(0o700)
    temp_root.chmod(0o700)
    store = Store(settings.database_path or settings.data_dir / "voice_eval.sqlite3")
    validator = MediaValidator(
        ffprobe_path=settings.ffprobe_path,
        ffmpeg_path=settings.ffmpeg_path,
        max_bytes=settings.max_upload_bytes,
        max_duration_seconds=settings.max_duration_seconds,
    )
    worker = Worker(store, settings)
    jobs = JobService(settings, store, validator, media_root, temp_root)
    return Runtime(settings, store, jobs, worker, media_root, temp_root)
