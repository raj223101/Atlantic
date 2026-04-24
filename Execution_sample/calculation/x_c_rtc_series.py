"""Rolling X_C series block with projected and committed outputs."""

from __future__ import annotations

from typing import Dict, Optional

from calculation.calc_lib import BBSlope, EMA, LinRegSlope
from config import MAINTENANCE_MODE
from core.maintenance import maintenance_payload


class XCRTCSeriesBlock:
    """Reusable rolling series with two gradient views."""

    def __init__(self, length: int = 9, gradient_window: int = 14, gradient_smoothing: int = 3):
        self.length = length
        self.gradient_window = gradient_window
        self.gradient_smoothing = gradient_smoothing

        self.e1 = EMA(length)
        self.e2 = EMA(length)
        self.e3 = EMA(length)

        self.bb = BBSlope(gradient_smoothing)
        self.lr = LinRegSlope(gradient_window)

    def update(self, close: float, is_close: bool = True) -> Dict[str, Optional[float]]:
        if MAINTENANCE_MODE:
            return maintenance_payload(
                "calculation.x_c_rtc_series",
                fields=("value", "bb", "lr"),
            )

        v1 = self.e1.update(close, is_close)
        v2 = self.e2.update(v1, is_close)
        v3 = self.e3.update(v2, is_close)

        series_value = 3.0 * (v1 - v2) + v3
        return {
            "value": series_value,
            "bb": self.bb.update(series_value, is_close),
            "lr": self.lr.update(series_value, is_close),
        }

    def reset(self) -> None:
        self.__init__(
            length=self.length,
            gradient_window=self.gradient_window,
            gradient_smoothing=self.gradient_smoothing,
        )
