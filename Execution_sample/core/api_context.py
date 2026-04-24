"""
Shared SmartAPI session context.
"""

from __future__ import annotations

import threading
from typing import Any, Optional

_lock = threading.RLock()
_api = None


def set_trading_api(api: Any) -> None:
    global _api
    with _lock:
        _api = api


def get_trading_api() -> Optional[Any]:
    with _lock:
        return _api
