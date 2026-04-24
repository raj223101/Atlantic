"""RTC state block with projected and committed outputs."""

from __future__ import annotations

from typing import Any, Dict, Optional

from calculation.calc_lib import ATR, BBSlope, LinRegSlope
from config import MAINTENANCE_MODE
from core.maintenance import maintenance_payload


class RTCTriggerBlock:
    """State block with categorical regime and dual gradients."""

    def __init__(
        self,
        keyvalue: float = 3.0,
        atrperiod: int = 10,
        gradient_window: int = 14,
        gradient_smoothing: int = 3,
    ) -> None:
        self.keyvalue = keyvalue
        self.atrperiod = atrperiod
        self.gradient_window = gradient_window
        self.gradient_smoothing = gradient_smoothing

        self.atr = ATR(atrperiod)
        self.bb = BBSlope(gradient_smoothing)
        self.lr = LinRegSlope(gradient_window)

        self.trail: float = 0.0
        self.prev_close: Optional[float] = None

    def update(self, h: float, l: float, c: float, is_close: bool = True) -> Dict[str, Any]:
        if MAINTENANCE_MODE:
            return maintenance_payload(
                "calculation.rtc_trigger",
                fields=("value", "state", "bb", "lr"),
            )

        atr_val = self.atr.update(h, l, c, is_close)
        if atr_val is None:
            return {
                "value": None,
                "state": "UNKNOWN",
                "bb": 0.0,
                "lr": None,
            }

        nloss = atr_val * self.keyvalue
        trail_prev = self.trail
        close_prev = self.prev_close

        if close_prev is None:
            trail = (c - nloss) if c > trail_prev else (c + nloss)
        else:
            cond1 = (c > trail_prev) and (close_prev > trail_prev)
            cond2 = (c < trail_prev) and (close_prev < trail_prev)

            if cond1:
                trail = max(trail_prev, c - nloss)
            elif cond2:
                trail = min(trail_prev, c + nloss)
            elif c > trail_prev:
                trail = c - nloss
            else:
                trail = c + nloss

        state = "BULL" if c > trail else "BEAR"
        result = {
            "value": trail,
            "state": state,
            "bb": self.bb.update(trail, is_close),
            "lr": self.lr.update(trail, is_close),
        }

        if is_close:
            self.prev_close = c
            self.trail = trail

        return result

    def reset(self) -> None:
        self.__init__(
            keyvalue=self.keyvalue,
            atrperiod=self.atrperiod,
            gradient_window=self.gradient_window,
            gradient_smoothing=self.gradient_smoothing,
        )
