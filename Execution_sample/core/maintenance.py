"""Shared helpers for transparent maintenance-mode behavior."""

from __future__ import annotations

import threading
from typing import Any, Iterable

from config import MAINTENANCE_CONTACT_MESSAGE, MAINTENANCE_MODE
from core.logger import log

_MAINTENANCE_LOG_LOCK = threading.Lock()
_MAINTENANCE_LOGGED_LABELS: set[str] = set()


def maintenance_payload(source: str, *, fields: Iterable[str] = ()) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "maintenance_mode": True,
        "output_message": MAINTENANCE_CONTACT_MESSAGE,
        "source": source,
    }
    for field in fields:
        payload.setdefault(str(field), None)
    return payload


def log_maintenance_once(label: str) -> None:
    if not MAINTENANCE_MODE:
        return
    with _MAINTENANCE_LOG_LOCK:
        if label in _MAINTENANCE_LOGGED_LABELS:
            return
        _MAINTENANCE_LOGGED_LABELS.add(label)
    log.warning("[MaintenanceMode] %s | %s", label, MAINTENANCE_CONTACT_MESSAGE)
