"""Primary X_C calculation block with projected and committed outputs."""

from __future__ import annotations

from typing import Dict, Optional

from calculation.calc_lib import BBSlope, LinRegSlope, RMA, nz, true_range
from config import MAINTENANCE_MODE
from core.maintenance import maintenance_payload

_NAN_RESULT = {
    "x_c_1": None,
    "x_c_2": None,
    "x_c_3": None,
    "x_c_1_bb": 0.0,
    "x_c_1_lr": None,
    "x_c_2_bb": 0.0,
    "x_c_2_lr": None,
    "x_c_3_bb": 0.0,
    "x_c_3_lr": None,
}


class XCRTCPrimaryBlock:
    """Primary reusable block with three base components and dual gradients."""

    def __init__(
        self,
        base_window: int = 14,
        confirm_window: int = 14,
        gradient_window: int = 14,
        gradient_smoothing: int = 3,
    ) -> None:
        self.base_window = base_window
        self.confirm_window = confirm_window
        self.gradient_window = gradient_window
        self.gradient_smoothing = gradient_smoothing

        self.tr_rma = RMA(base_window)
        self.pdm_rma = RMA(base_window)
        self.ndm_rma = RMA(base_window)
        self.dx_rma = RMA(confirm_window)

        self.prev_high: Optional[float] = None
        self.prev_low: Optional[float] = None
        self.prev_close: Optional[float] = None

        self.bb_a = BBSlope(gradient_smoothing)
        self.bb_b = BBSlope(gradient_smoothing)
        self.bb_c = BBSlope(gradient_smoothing)
        self.lr_a = LinRegSlope(gradient_window)
        self.lr_b = LinRegSlope(gradient_window)
        self.lr_c = LinRegSlope(gradient_window)

    def update(self, h: float, l: float, c: float, is_close: bool = True) -> Dict[str, Optional[float]]:
        if MAINTENANCE_MODE:
            return maintenance_payload("calculation.x_c_rtc_primary", fields=_NAN_RESULT)

        ph = self.prev_high if self.prev_high is not None else h
        pl = self.prev_low if self.prev_low is not None else l

        up = h - ph
        down = pl - l
        pdm = up if (up > down and up > 0) else 0.0
        ndm = down if (down > up and down > 0) else 0.0

        tr = true_range(h, l, self.prev_close)
        tr_s = self.tr_rma.update(tr, is_close)
        pdm_s = self.pdm_rma.update(pdm, is_close)
        ndm_s = self.ndm_rma.update(ndm, is_close)

        if tr_s is None:
            if is_close:
                self.prev_high, self.prev_low, self.prev_close = h, l, c
            return dict(_NAN_RESULT)

        div = tr_s if tr_s != 0 else 1.0
        x_c_2 = 100.0 * pdm_s / div
        x_c_3 = 100.0 * ndm_s / div

        x_sum = x_c_2 + x_c_3
        dx = 100.0 * abs(x_c_2 - x_c_3) / (x_sum if x_sum != 0 else 1.0)
        x_c_1 = nz(self.dx_rma.update(dx, is_close), 0.0)

        result = {
            "x_c_1": x_c_1,
            "x_c_2": x_c_2,
            "x_c_3": x_c_3,
            "x_c_1_bb": self.bb_a.update(x_c_1, is_close),
            "x_c_1_lr": self.lr_a.update(x_c_1, is_close),
            "x_c_2_bb": self.bb_b.update(x_c_2, is_close),
            "x_c_2_lr": self.lr_b.update(x_c_2, is_close),
            "x_c_3_bb": self.bb_c.update(x_c_3, is_close),
            "x_c_3_lr": self.lr_c.update(x_c_3, is_close),
        }

        if is_close:
            self.prev_high, self.prev_low, self.prev_close = h, l, c

        return result

    def reset(self) -> None:
        self.__init__(
            base_window=self.base_window,
            confirm_window=self.confirm_window,
            gradient_window=self.gradient_window,
            gradient_smoothing=self.gradient_smoothing,
        )
