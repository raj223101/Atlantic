"""
India cash-session time controls.
"""

from __future__ import annotations

from datetime import datetime, time as dtime

from config import (
    ENTRY_CUTOFF_TIME,
    ENTRY_START,
    FORCE_EXIT_TIME,
    MARKET_END,
    MARKET_START,
)


def _parse(value: str) -> dtime:
    hour, minute = map(int, value.split(":"))
    return dtime(hour, minute)


class TimeManager:
    _MARKET_START = _parse(MARKET_START)
    _ENTRY_START = _parse(ENTRY_START)
    _ENTRY_CUTOFF = _parse(ENTRY_CUTOFF_TIME)
    _FORCE_EXIT_AT = _parse(FORCE_EXIT_TIME)
    _MARKET_END = _parse(MARKET_END)

    @classmethod
    def _as_time(cls, ts: datetime | None = None) -> dtime:
        return (ts or datetime.now()).time()

    @classmethod
    def is_market_open(cls, ts: datetime | None = None) -> bool:
        current = cls._as_time(ts)
        return cls._MARKET_START <= current <= cls._MARKET_END

    @classmethod
    def can_enter_new_trade(cls, ts: datetime | None = None) -> bool:
        current = cls._as_time(ts)
        return cls._ENTRY_START <= current <= cls._ENTRY_CUTOFF

    @classmethod
    def is_post_entry_cutoff(cls, ts: datetime | None = None) -> bool:
        return cls._as_time(ts) > cls._ENTRY_CUTOFF

    @classmethod
    def check_force_exit(cls, ts: datetime | None = None) -> bool:
        return cls._as_time(ts) >= cls._FORCE_EXIT_AT
