"""Narrow, non-executing import status registry.

The actual import log lives in each tenant MariaDB database.  This registry is
only a demo control-plane surface: it tracks jobs started by future import
workers and persists metadata to JSON, never imported rows or credentials.
"""

from __future__ import annotations

import json
import os
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from jarvis import config


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class ImportJob:
    id: str
    tenant_id: int
    import_type: str
    filename: Optional[str] = None
    status: str = "queued"
    rows_imported: int = 0
    rows_skipped: int = 0
    error_code: Optional[str] = None
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)


class ImportJobService:
    """Small JSON-backed registry; safe to replace with a durable store later."""

    def __init__(self, path: Optional[str] = None):
        self.path = path or config.IMPORT_JOBS_PATH
        self._jobs: dict[str, ImportJob] = {}
        self._lock = threading.RLock()
        self._load()

    def _load(self) -> None:
        try:
            with open(self.path, encoding="utf-8") as handle:
                entries = json.load(handle)
            if isinstance(entries, list):
                for entry in entries:
                    job = ImportJob(**entry)
                    self._jobs[job.id] = job
        except (FileNotFoundError, json.JSONDecodeError, TypeError, ValueError):
            return

    def _save(self) -> None:
        directory = os.path.dirname(self.path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        temporary = self.path + ".tmp"
        with open(temporary, "w", encoding="utf-8") as handle:
            json.dump([asdict(job) for job in self._jobs.values()], handle, indent=2)
        os.replace(temporary, self.path)
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass

    def create(self, tenant_id: int, import_type: str, filename: Optional[str] = None) -> ImportJob:
        if import_type not in {"sales", "purchases"}:
            raise ValueError("import_type must be sales or purchases")
        with self._lock:
            job = ImportJob(id=str(uuid.uuid4()), tenant_id=tenant_id,
                            import_type=import_type, filename=filename)
            self._jobs[job.id] = job
            self._save()
            return job

    def update(self, job_id: str, **changes) -> Optional[ImportJob]:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            allowed = {"status", "rows_imported", "rows_skipped", "error_code"}
            for key, value in changes.items():
                if key in allowed:
                    setattr(job, key, value)
            job.updated_at = _now()
            self._save()
            return job

    def get(self, job_id: str, tenant_id: Optional[int] = None) -> Optional[ImportJob]:
        job = self._jobs.get(job_id)
        return job if job and (tenant_id is None or job.tenant_id == tenant_id) else None

    def list(self, tenant_id: Optional[int] = None, limit: int = 50) -> list[ImportJob]:
        jobs = [j for j in self._jobs.values() if tenant_id is None or j.tenant_id == tenant_id]
        return sorted(jobs, key=lambda item: item.created_at, reverse=True)[:limit]


_service: Optional[ImportJobService] = None


def get_import_job_service() -> ImportJobService:
    global _service
    if _service is None:
        _service = ImportJobService()
    return _service
