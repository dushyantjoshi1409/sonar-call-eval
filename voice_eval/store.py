"""SQLite persistence for jobs, evaluations, regression runs, and queue state."""

from __future__ import annotations

import json
import sqlite3
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

_UPDATABLE_JOB_COLUMNS = {
    "provider_handle",
    "provider_model",
    "report_json",
    "status",
    "status_detail",
}


def _now() -> str:
    return datetime.now(UTC).isoformat()


class Store:
    """Short-lived SQLite connections with transactional versioned writes."""

    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()
        self.database_path.chmod(0o600)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    idempotency_key TEXT UNIQUE,
                    payload_hash TEXT NOT NULL,
                    status TEXT NOT NULL,
                    status_detail TEXT NOT NULL,
                    original_name TEXT NOT NULL,
                    media_path TEXT NOT NULL,
                    media_json TEXT NOT NULL,
                    profile_json TEXT NOT NULL,
                    profile_hash TEXT NOT NULL,
                    transcript_json TEXT,
                    transcript_revision INTEGER NOT NULL DEFAULT 0,
                    trusted_reference_text TEXT,
                    reference_attested INTEGER NOT NULL DEFAULT 0,
                    report_json TEXT,
                    run_version INTEGER NOT NULL DEFAULT 0,
                    fixture INTEGER NOT NULL DEFAULT 0,
                    provider_model TEXT,
                    provider_handle TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    deleted_at TEXT
                );
                CREATE INDEX IF NOT EXISTS jobs_status_idx ON jobs(status, created_at);
                CREATE TABLE IF NOT EXISTS transcript_revisions (
                    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                    revision INTEGER NOT NULL,
                    transcript_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(job_id, revision)
                );
                CREATE TABLE IF NOT EXISTS runs (
                    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                    version INTEGER NOT NULL,
                    report_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(job_id, version)
                );
                CREATE TABLE IF NOT EXISTS regression_runs (
                    id TEXT PRIMARY KEY,
                    suite_version TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    model TEXT,
                    prompt_version TEXT NOT NULL,
                    rubric_version TEXT NOT NULL,
                    baseline_id TEXT,
                    results_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS regression_runs_created_idx
                ON regression_runs(created_at DESC);
                """
            )
            columns = {
                str(row["name"]) for row in connection.execute("PRAGMA table_info(jobs)").fetchall()
            }
            if "trusted_reference_text" not in columns:
                connection.execute("ALTER TABLE jobs ADD COLUMN trusted_reference_text TEXT")
            if "reference_attested" not in columns:
                connection.execute(
                    "ALTER TABLE jobs ADD COLUMN reference_attested INTEGER NOT NULL DEFAULT 0"
                )

    def create_job(self, values: dict[str, Any]) -> dict[str, Any]:
        """Insert an internally assembled job and its initial transcript revision."""
        columns = ", ".join(values)
        placeholders = ", ".join("?" for _ in values)
        with self._connect() as connection:
            connection.execute(
                f"INSERT INTO jobs ({columns}) VALUES ({placeholders})", tuple(values.values())
            )
            if values.get("transcript_json"):
                connection.execute(
                    "INSERT INTO transcript_revisions "
                    "(job_id, revision, transcript_json, created_at) VALUES (?, 1, ?, ?)",
                    (values["id"], values["transcript_json"], values["created_at"]),
                )
        return self.get_job(str(values["id"]), include_deleted=True)

    def find_by_idempotency_key(self, key: str) -> dict[str, Any] | None:
        """Find a job including deleted records for idempotency conflict handling."""
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM jobs WHERE idempotency_key = ?", (key,)
            ).fetchone()
        return self._decode(row) if row else None

    def get_job(self, job_id: str, *, include_deleted: bool = False) -> dict[str, Any]:
        """Return a decoded job, raising ``KeyError`` or ``PermissionError``."""
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if row is None:
            raise KeyError(job_id)
        job = self._decode(row)
        if job["deleted_at"] and not include_deleted:
            raise PermissionError(job_id)
        return job

    def update(self, job_id: str, **values: Any) -> dict[str, Any]:
        """Update an active job or raise ``PermissionError`` after deletion."""
        unexpected = values.keys() - _UPDATABLE_JOB_COLUMNS
        if not values or unexpected:
            raise ValueError(f"unsupported job update columns: {sorted(unexpected)}")
        values["updated_at"] = _now()
        assignments = ", ".join(f"{key} = ?" for key in values)
        with self._connect() as connection:
            cursor = connection.execute(
                f"UPDATE jobs SET {assignments} WHERE id = ? AND deleted_at IS NULL",
                (*values.values(), job_id),
            )
            if cursor.rowcount != 1:
                raise PermissionError(job_id)
        return self.get_job(job_id)

    def save_transcript(self, job_id: str, transcript_json: str) -> dict[str, Any]:
        """Atomically update the current transcript and append its revision."""
        job = self.get_job(job_id)
        revision = int(job["transcript_revision"]) + 1
        now = _now()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                "UPDATE jobs SET transcript_json = ?, transcript_revision = ?, status = ?, "
                "status_detail = ?, updated_at = ? WHERE id = ? AND deleted_at IS NULL",
                (
                    transcript_json,
                    revision,
                    "review_ready",
                    "Reviewed transcript saved as a new revision",
                    now,
                    job_id,
                ),
            )
            if cursor.rowcount != 1:
                raise PermissionError(job_id)
            connection.execute(
                "INSERT INTO transcript_revisions "
                "(job_id, revision, transcript_json, created_at) VALUES (?, ?, ?, ?)",
                (job_id, revision, transcript_json, now),
            )
        return self.get_job(job_id)

    def save_report(self, job_id: str, report_json: str, version: int) -> dict[str, Any]:
        """Atomically complete a job and append an immutable report version."""
        now = _now()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                "UPDATE jobs SET report_json = ?, run_version = ?, status = 'completed', "
                "status_detail = ?, updated_at = ? WHERE id = ? AND deleted_at IS NULL",
                (
                    report_json,
                    version,
                    "Evidence-linked evaluation completed",
                    now,
                    job_id,
                ),
            )
            if cursor.rowcount != 1:
                raise PermissionError(job_id)
            connection.execute(
                "INSERT INTO runs (job_id, version, report_json, created_at) VALUES (?, ?, ?, ?)",
                (job_id, version, report_json, now),
            )
        return self.get_job(job_id)

    def get_history(self, job_id: str) -> dict[str, list[dict[str, Any]]]:
        """Return decoded transcript and report history for export."""
        self.get_job(job_id)
        with self._connect() as connection:
            transcript_rows = connection.execute(
                "SELECT revision, transcript_json, created_at FROM transcript_revisions "
                "WHERE job_id = ? ORDER BY revision",
                (job_id,),
            ).fetchall()
            run_rows = connection.execute(
                "SELECT version, report_json, created_at FROM runs "
                "WHERE job_id = ? ORDER BY version",
                (job_id,),
            ).fetchall()
        return {
            "transcript_revisions": [
                {
                    "revision": row["revision"],
                    "transcript": json.loads(row["transcript_json"]),
                    "created_at": row["created_at"],
                }
                for row in transcript_rows
            ],
            "runs": [
                {
                    "version": row["version"],
                    "report": json.loads(row["report_json"]),
                    "created_at": row["created_at"],
                }
                for row in run_rows
            ],
        }

    def pending_count(self) -> int:
        """Count active queued or transcribing jobs for bounded admission."""
        with self._connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS count FROM jobs WHERE status IN ('queued', 'transcribing') "
                "AND deleted_at IS NULL"
            ).fetchone()
        return int(row["count"])

    def save_regression_run(self, run: dict[str, Any]) -> dict[str, Any]:
        """Persist nonsecret suite results and immutable comparison metadata."""
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO regression_runs "
                "(id, suite_version, provider, model, prompt_version, rubric_version, "
                "baseline_id, results_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    run["id"],
                    run["suite_version"],
                    run["provider"],
                    run["model"],
                    run["prompt_version"],
                    run["rubric_version"],
                    run["baseline_id"],
                    json.dumps(run, ensure_ascii=False),
                    run["created_at"],
                ),
            )
        return self.get_regression_run(str(run["id"]))

    def get_regression_run(self, run_id: str) -> dict[str, Any]:
        """Return one complete synthetic regression result."""
        with self._connect() as connection:
            row = connection.execute(
                "SELECT results_json FROM regression_runs WHERE id = ?", (run_id,)
            ).fetchone()
        if row is None:
            raise KeyError(run_id)
        value = json.loads(str(row["results_json"]))
        if not isinstance(value, dict):
            raise ValueError("stored regression run is not an object")
        return value

    def list_regression_runs(self, limit: int = 20) -> list[dict[str, Any]]:
        """Return recent complete synthetic runs for baseline selection."""
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT results_json FROM regression_runs ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [json.loads(str(row["results_json"])) for row in rows]

    def claim_next(self) -> dict[str, Any] | None:
        """Atomically claim the oldest queued job for the single worker."""
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT id FROM jobs WHERE status = 'queued' AND deleted_at IS NULL "
                "ORDER BY created_at LIMIT 1"
            ).fetchone()
            if row is None:
                return None
            updated = connection.execute(
                "UPDATE jobs SET status = 'transcribing', updated_at = ? "
                "WHERE id = ? AND status = 'queued' AND deleted_at IS NULL",
                (_now(), row["id"]),
            )
            if updated.rowcount != 1:
                return None
        return self.get_job(str(row["id"]))

    def recover_interrupted(self) -> int:
        """Fail ambiguous in-flight submissions instead of resubmitting them."""
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE jobs SET status = 'failed', status_detail = ?, updated_at = ? "
                "WHERE status = 'transcribing' AND deleted_at IS NULL",
                (
                    "ambiguous_submit: process stopped during synchronous provider request; "
                    "automatic resubmission is disabled",
                    _now(),
                ),
            )
            return cursor.rowcount

    def delete_job(self, job_id: str) -> dict[str, Any]:
        """Delete database content and media while holding an immediate transaction.

        A media unlink failure rolls back the database mutation, leaving the job
        retryable and preventing a false deleted state with retained recording bytes.
        """
        deleted_at = _now()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
            if row is None:
                raise KeyError(job_id)
            job = self._decode(row)
            if job["deleted_at"]:
                raise PermissionError(job_id)
            cursor = connection.execute(
                "UPDATE jobs SET status = 'deleted', status_detail = ?, deleted_at = ?, "
                "updated_at = ?, transcript_json = NULL, trusted_reference_text = NULL, "
                "report_json = NULL WHERE id = ? "
                "AND deleted_at IS NULL",
                ("Deleted locally", deleted_at, deleted_at, job_id),
            )
            if cursor.rowcount != 1:
                raise PermissionError(job_id)
            connection.execute("DELETE FROM runs WHERE job_id = ?", (job_id,))
            connection.execute("DELETE FROM transcript_revisions WHERE job_id = ?", (job_id,))
            media_path = Path(str(job["media_path"]))
            media_path.unlink(missing_ok=True)
            with suppress(OSError):
                media_path.parent.rmdir()
        return {"id": job_id, "status": "deleted", "deleted_at": deleted_at}

    def sweep_expired(self, retention_hours: int) -> int:
        """Delete active jobs older than the configured retention window."""
        cutoff = (datetime.now(UTC) - timedelta(hours=retention_hours)).isoformat()
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT id FROM jobs WHERE deleted_at IS NULL AND created_at < ?", (cutoff,)
            ).fetchall()
        for row in rows:
            self.delete_job(str(row["id"]))
        return len(rows)

    @staticmethod
    def _decode(row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row)
        for field in ("media_json", "profile_json", "transcript_json", "report_json"):
            if result[field] is not None:
                result[field.removesuffix("_json")] = json.loads(result[field])
            else:
                result[field.removesuffix("_json")] = None
            del result[field]
        result["fixture"] = bool(result["fixture"])
        result["reference_attested"] = bool(result["reference_attested"])
        return result


def job_values(
    *,
    job_id: str,
    idempotency_key: str | None,
    payload_hash: str,
    status: str,
    status_detail: str,
    original_name: str,
    media_path: Path,
    media: dict[str, Any],
    profile: dict[str, Any],
    profile_hash: str,
    transcript: list[dict[str, Any]] | None,
    trusted_reference: str | None = None,
    reference_attested: bool = False,
    fixture: bool = False,
    provider_model: str | None = None,
    provider_handle: str | None = None,
) -> dict[str, Any]:
    """Assemble the internal database record for a newly validated job."""
    now = _now()
    return {
        "id": job_id,
        "idempotency_key": idempotency_key,
        "payload_hash": payload_hash,
        "status": status,
        "status_detail": status_detail,
        "original_name": original_name,
        "media_path": str(media_path),
        "media_json": json.dumps(media, ensure_ascii=False),
        "profile_json": json.dumps(profile, ensure_ascii=False),
        "profile_hash": profile_hash,
        "transcript_json": json.dumps(transcript, ensure_ascii=False) if transcript else None,
        "transcript_revision": 1 if transcript else 0,
        "trusted_reference_text": trusted_reference,
        "reference_attested": int(reference_attested),
        "report_json": None,
        "run_version": 0,
        "fixture": int(fixture),
        "provider_model": provider_model,
        "provider_handle": provider_handle,
        "created_at": now,
        "updated_at": now,
        "deleted_at": None,
    }
