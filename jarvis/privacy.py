"""JSON-backed GDPR request register (request-only; no automatic deletion)."""

from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import datetime, timezone
from typing import Optional

from jarvis import config


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class PrivacyRequestService:
    def __init__(self, path: Optional[str] = None):
        self.path = path or config.PRIVACY_REQUESTS_PATH
        self._requests: list[dict] = []
        self._lock = threading.RLock()
        self._load()

    def _load(self):
        try:
            with open(self.path, encoding="utf-8") as handle:
                data = json.load(handle)
            if isinstance(data, list):
                self._requests = data
        except (FileNotFoundError, json.JSONDecodeError):
            pass

    def _save(self):
        directory = os.path.dirname(self.path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(self._requests, handle, indent=2)
        os.replace(tmp, self.path)
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass

    def create(self, tenant_id: int, request_type: str, requested_by: int) -> dict:
        if request_type not in {"export", "deletion"}:
            raise ValueError("request_type must be export or deletion")
        with self._lock:
            request = {
                "id": str(uuid.uuid4()), "tenant_id": tenant_id,
                "type": request_type, "status": "requested",
                "requested_by": requested_by, "created_at": _now(),
                "updated_at": _now(),
            }
            self._requests.append(request)
            self._save()
            return request.copy()

    def list(self, tenant_id: Optional[int] = None) -> list[dict]:
        return [r.copy() for r in self._requests
                if tenant_id is None or r["tenant_id"] == tenant_id]


_service: Optional[PrivacyRequestService] = None


def get_privacy_request_service() -> PrivacyRequestService:
    global _service
    if _service is None:
        _service = PrivacyRequestService()
    return _service
