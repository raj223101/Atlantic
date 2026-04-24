"""Flow-oriented X_C calculation blocks."""

from __future__ import annotations

from collections import deque
from typing import Dict, Optional

from calculation.calc_lib import BBSlope, LinRegSlope
from config import MAINTENANCE_MODE
from core.maintenance import maintenance_payload


class XCFlowWindow:
    """Windowed flow block with two gradient views."""

    def __init__(self, length: int = 20, gradient_window: int = 14, gradient_smoothing: int = 3):
        self.length = max(1, length)
        self.gradient_window = gradient_window
        self.gradient_smoothing = gradient_smoothing

        self.hist_vol = deque(maxlen=self.length)
        self.hist_src_vol = deque(maxlen=self.length)
        self.bb = BBSlope(gradient_smoothing)
        self.lr = LinRegSlope(gradient_window)

    def update(self, close: float, volume: float, is_close: bool = True) -> Dict[str, Optional[float]]:
        if MAINTENANCE_MODE:
            return maintenance_payload(
                "calculation.x_c_rtc_flow_window",
                fields=("x_c_4", "x_c_4_bb", "x_c_4_lr"),
            )

        src_v = close * volume

        if len(self.hist_vol) < self.length - 1:
            if is_close:
                self.hist_vol.append(volume)
                self.hist_src_vol.append(src_v)
            return {"x_c_4": None, "x_c_4_bb": 0.0, "x_c_4_lr": None}

        if self.length > 1:
            w_v = list(self.hist_vol)[-(self.length - 1):] + [volume]
            w_sv = list(self.hist_src_vol)[-(self.length - 1):] + [src_v]
        else:
            w_v = [volume]
            w_sv = [src_v]

        sum_v = sum(w_v)
        flow_value = sum(w_sv) / sum_v if sum_v != 0 else 0.0
        result = {
            "x_c_4": flow_value,
            "x_c_4_bb": self.bb.update(flow_value, is_close),
            "x_c_4_lr": self.lr.update(flow_value, is_close),
        }

        if is_close:
            self.hist_vol.append(volume)
            self.hist_src_vol.append(src_v)

        return result

    def reset(self) -> None:
        self.__init__(
            length=self.length,
            gradient_window=self.gradient_window,
            gradient_smoothing=self.gradient_smoothing,
        )


class XCFlowAccumulator:
    """Accumulated flow block with two gradient views."""

    def __init__(self, gradient_window: int = 14, gradient_smoothing: int = 3):
        self.gradient_window = gradient_window
        self.gradient_smoothing = gradient_smoothing

        self.value: float = 0.0
        self.bb = BBSlope(gradient_smoothing)
        self.lr = LinRegSlope(gradient_window)

    def update(self, open_: float, close: float, volume: float, is_close: bool = True) -> Dict[str, Optional[float]]:
        if MAINTENANCE_MODE:
            return maintenance_payload(
                "calculation.x_c_rtc_flow_accumulator",
                fields=("x_c_5", "x_c_5_bb", "x_c_5_lr"),
            )

        direction = 1.0 if close >= open_ else -1.0
        delta = direction * volume
        current_value = self.value + delta

        result = {
            "x_c_5": current_value,
            "x_c_5_bb": self.bb.update(current_value, is_close),
            "x_c_5_lr": self.lr.update(current_value, is_close),
        }

        if is_close:
            self.value = current_value

        return result

    def reset(self) -> None:
        self.__init__(
            gradient_window=self.gradient_window,
            gradient_smoothing=self.gradient_smoothing,
        )
