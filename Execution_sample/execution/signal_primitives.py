"""
Shared signal primitives.

This module contains only neutral execution state helpers. Strategy logic lives
in the per-family signal engines.
"""

from __future__ import annotations

import math
import time as _time
from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from typing import Any, Dict, Optional, Tuple


class HTFState(Enum):
    NEUTRAL = "NEUTRAL"
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"


class PositionState(Enum):
    FLAT = "FLAT"
    LONG = "LONG"
    SHORT = "SHORT"


class Signal(Enum):
    NONE = "NONE"
    OPEN_LONG = "OPEN_LONG"
    OPEN_SHORT = "OPEN_SHORT"
    CLOSE_LONG = "CLOSE_LONG"
    CLOSE_SHORT = "CLOSE_SHORT"


def value_of(snapshot: Dict[str, Any], key: str, default: float = 0.0) -> float:
    value = snapshot.get(key, default)
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return default
    if math.isnan(numeric) or math.isinf(numeric):
        return default
    return numeric


def text_of(snapshot: Dict[str, Any], key: str, default: str = "") -> str:
    value = snapshot.get(key, default)
    return str(value) if value is not None else default


def bucket_for_tf(ts: datetime, tf_seconds: int) -> int:
    return (ts.hour * 3600 + ts.minute * 60 + ts.second) // int(tf_seconds)


def bucket_key_for_tf(ts: datetime, tf_seconds: int) -> Tuple[date, int]:
    return ts.date(), bucket_for_tf(ts, tf_seconds)


@dataclass
class NextBucketGuard:
    reference_tf: int
    _exit_bucket: Optional[int] = None
    _exit_date: Optional[date] = None

    def record_exit(self, ts: datetime) -> None:
        self._exit_bucket = bucket_for_tf(ts, self.reference_tf)
        self._exit_date = ts.date()

    def can_enter(self, ts: datetime) -> bool:
        if self._exit_bucket is None:
            return True
        if self._exit_date is not None and ts.date() > self._exit_date:
            return True
        return bucket_for_tf(ts, self.reference_tf) > self._exit_bucket

    def reset(self) -> None:
        self._exit_bucket = None
        self._exit_date = None


class SignalStabilizer:
    def __init__(self, *, stability_ms: int, bucket_tf: int) -> None:
        self._stability_s = max(int(stability_ms), 0) / 1000.0
        self._bucket_tf = int(bucket_tf)
        self._pending = Signal.NONE
        self._first_seen: Optional[float] = None
        self._last_entry_bucket: Optional[Tuple[date, int]] = None

    def update(self, candidate: Signal, ts: datetime) -> Signal:
        if candidate in (Signal.CLOSE_LONG, Signal.CLOSE_SHORT):
            self._reset_pending()
            return candidate

        if candidate == Signal.NONE:
            self._reset_pending()
            return Signal.NONE

        if candidate != self._pending:
            self._pending = candidate
            self._first_seen = _time.perf_counter()
            if self._stability_s > 0:
                return Signal.NONE

        if self._first_seen is None:
            self._first_seen = _time.perf_counter()

        elapsed = _time.perf_counter() - self._first_seen
        if elapsed < self._stability_s:
            return Signal.NONE

        bucket_key = bucket_key_for_tf(ts, self._bucket_tf)
        if self._last_entry_bucket == bucket_key:
            return Signal.NONE

        self._last_entry_bucket = bucket_key
        fired = self._pending
        self._reset_pending()
        return fired

    def reset(self) -> None:
        self._reset_pending()
        self._last_entry_bucket = None

    def _reset_pending(self) -> None:
        self._pending = Signal.NONE
        self._first_seen = None
