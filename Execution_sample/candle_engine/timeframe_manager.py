"""
Timeframe bucket helpers for live candle aggregation.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Dict, Iterable, Tuple


class TimeframeManager:
    """Calculate candle buckets for arbitrary second-based timeframes."""

    @staticmethod
    def get_bucket(ts: datetime, tf_seconds: int) -> Tuple[datetime, int]:
        total_secs = ts.hour * 3600 + ts.minute * 60 + ts.second
        bucket_idx = total_secs // tf_seconds
        start_secs = bucket_idx * tf_seconds

        candle_start = ts.replace(
            hour=start_secs // 3600,
            minute=(start_secs % 3600) // 60,
            second=start_secs % 60,
            microsecond=0,
        )
        return candle_start, bucket_idx

    @staticmethod
    def get_candle_end_time(candle_start: datetime, tf_seconds: int) -> datetime:
        return candle_start + timedelta(seconds=tf_seconds)

    @staticmethod
    def get_all_open_buckets(
        ts: datetime,
        timeframes: Iterable[int],
    ) -> Dict[int, Tuple[datetime, int]]:
        return {
            int(tf): TimeframeManager.get_bucket(ts, int(tf))
            for tf in sorted(set(int(tf) for tf in timeframes))
        }
