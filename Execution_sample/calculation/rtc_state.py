"""Real-time RTC calculations layered on top of existing snapshot values."""

from __future__ import annotations

import math
from typing import Any, Dict, Iterable, Optional, Tuple

from calculation.calc_lib import SMA, is_na
from config import MAINTENANCE_MODE
from core.maintenance import maintenance_payload


class _RTCSeries:
    """Tracks the angular change of a single series with optional smoothing."""

    def __init__(self, smooth_len: int = 5, use_smoothing: bool = True):
        self.smooth_len = max(1, int(smooth_len))
        self.use_smoothing = bool(use_smoothing)
        self.prev_value: Optional[float] = None
        self.sma = SMA(self.smooth_len)

    def update(self, value: Any, is_close: bool = True) -> Optional[float]:
        if is_na(value):
            return None

        value = float(value)
        if self.prev_value is None:
            if is_close:
                self.prev_value = value
            return None

        raw_angle = math.degrees(math.atan(value - self.prev_value))
        if is_close:
            self.prev_value = value

        if not self.use_smoothing:
            return raw_angle
        return self.sma.update(raw_angle, is_close)

    def reset(self) -> None:
        self.prev_value = None
        self.sma.reset()


class RTCStateBlock:
    """Calculates live RTC views for the current snapshot."""

    def __init__(
        self,
        series_windows: Iterable[int],
        rtc_parameter_grid: Iterable[Tuple[float, int]],
        smoothing_window: int = 5,
        use_smoothing: bool = True,
    ) -> None:
        self.series_windows = [int(length) for length in series_windows]
        self.rtc_parameter_grid = [(float(kv), int(ap)) for kv, ap in rtc_parameter_grid]

        self.x_c_2 = _RTCSeries(smoothing_window, use_smoothing)
        self.x_c_3 = _RTCSeries(smoothing_window, use_smoothing)
        self.series_blocks = {
            length: _RTCSeries(smoothing_window, use_smoothing)
            for length in self.series_windows
        }
        self.rtc_blocks = {
            self._rtc_key(kv, ap): _RTCSeries(smoothing_window, use_smoothing)
            for kv, ap in self.rtc_parameter_grid
        }

    @staticmethod
    def _rtc_key(kv: float, ap: int) -> str:
        return f"{kv}_{ap}"

    def update(self, snapshot: Dict[str, Any], is_close: bool = True) -> Dict[str, Optional[float]]:
        if MAINTENANCE_MODE:
            return maintenance_payload(
                "calculation.rtc_state",
                fields=("x_c_2_angle", "x_c_3_angle", "rtc_spread"),
            )

        x_c_2_angle = self.x_c_2.update(snapshot.get("x_c_2"), is_close)
        x_c_3_angle = self.x_c_3.update(snapshot.get("x_c_3"), is_close)

        result: Dict[str, Optional[float]] = {
            "x_c_2_angle": x_c_2_angle,
            "x_c_3_angle": x_c_3_angle,
            "rtc_spread": (
                x_c_2_angle - x_c_3_angle
                if x_c_2_angle is not None and x_c_3_angle is not None
                else None
            ),
        }

        for length, tracker in self.series_blocks.items():
            result[f"x_c_series_{length}_angle"] = tracker.update(
                snapshot.get(f"x_c_series_{length}_value"),
                is_close,
            )

        for key, tracker in self.rtc_blocks.items():
            result[f"rtc_{key}_angle"] = tracker.update(
                snapshot.get(f"rtc_{key}_value"),
                is_close,
            )

        return result

    def reset(self) -> None:
        self.x_c_2.reset()
        self.x_c_3.reset()
        for tracker in self.series_blocks.values():
            tracker.reset()
        for tracker in self.rtc_blocks.values():
            tracker.reset()
