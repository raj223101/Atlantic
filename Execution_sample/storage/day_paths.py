"""
Daily storage path helpers.

New runtime data is grouped as:
data/<day month>/<category>/...
Example: data/16 april/5 sec candel/NIFTY_5s.csv
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any

from config import DATA_DIR


_MONTHS = (
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
)


def coerce_datetime(value: Any = None) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            try:
                return datetime.strptime(value.split(".")[0], "%Y-%m-%d %H:%M:%S")
            except ValueError:
                pass
    return datetime.now()


def day_folder(value: Any = None) -> str:
    dt = coerce_datetime(value)
    month = _MONTHS[max(min(dt.month, 12), 1) - 1]
    path = os.path.join(DATA_DIR, f"{dt.day} {month}")
    os.makedirs(path, exist_ok=True)
    return path


def candle_dir(tf_seconds: int, value: Any = None) -> str:
    path = os.path.join(day_folder(value), f"{int(tf_seconds)} sec candel")
    os.makedirs(path, exist_ok=True)
    return path


def ticks_dir(value: Any = None) -> str:
    path = os.path.join(day_folder(value), "ticks")
    os.makedirs(path, exist_ok=True)
    return path


def option_quotes_dir(value: Any = None) -> str:
    path = os.path.join(day_folder(value), "option quotes")
    os.makedirs(path, exist_ok=True)
    return path


def trades_dir(value: Any = None) -> str:
    path = os.path.join(day_folder(value), "trades")
    os.makedirs(path, exist_ok=True)
    return path
