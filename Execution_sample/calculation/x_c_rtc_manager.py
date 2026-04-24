"""Per-(symbol, timeframe) calculation orchestration."""

from __future__ import annotations

from typing import Any, Dict, Optional

from calculation.rtc_state import RTCStateBlock
from calculation.rtc_trigger import RTCTriggerBlock
from calculation.x_c_rtc_flow import XCFlowAccumulator, XCFlowWindow
from calculation.x_c_rtc_primary import XCRTCPrimaryBlock
from calculation.x_c_rtc_series import XCRTCSeriesBlock
from config import (
    CALC_BASE_WINDOW,
    CALC_CONFIRM_WINDOW,
    CALC_FLOW_WINDOW,
    CALC_GRADIENT_SMOOTHING,
    CALC_GRADIENT_WINDOW,
    CALC_SERIES_WINDOWS,
    MAINTENANCE_MODE,
    RTC_PARAMETER_GRID,
    RTC_SMOOTHING_WINDOW,
    RTC_USE_SMOOTHING,
)
from core.maintenance import log_maintenance_once, maintenance_payload


class XCRTCManager:
    """Coordinates all reusable calculation blocks for one symbol/timeframe pair."""

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        cfg = config or {}
        base_window = cfg.get("base_window", CALC_BASE_WINDOW)
        confirm_window = cfg.get("confirm_window", CALC_CONFIRM_WINDOW)
        gradient_window = cfg.get("gradient_window", CALC_GRADIENT_WINDOW)
        gradient_smoothing = cfg.get("gradient_smoothing", CALC_GRADIENT_SMOOTHING)
        series_windows = cfg.get("series_windows", CALC_SERIES_WINDOWS)
        rtc_parameter_grid = cfg.get("rtc_parameter_grid", RTC_PARAMETER_GRID)
        flow_window = cfg.get("flow_window", CALC_FLOW_WINDOW)
        rtc_smoothing_window = cfg.get("rtc_smoothing_window", RTC_SMOOTHING_WINDOW)
        rtc_use_smoothing = cfg.get("rtc_use_smoothing", RTC_USE_SMOOTHING)

        self.x_c_primary = XCRTCPrimaryBlock(
            base_window=base_window,
            confirm_window=confirm_window,
            gradient_window=gradient_window,
            gradient_smoothing=gradient_smoothing,
        )
        self.x_c_series = {
            length: XCRTCSeriesBlock(
                length=length,
                gradient_window=gradient_window,
                gradient_smoothing=gradient_smoothing,
            )
            for length in series_windows
        }
        self.rtc_blocks = {
            f"{keyvalue}_{atrperiod}": RTCTriggerBlock(
                keyvalue=keyvalue,
                atrperiod=atrperiod,
                gradient_window=gradient_window,
                gradient_smoothing=gradient_smoothing,
            )
            for keyvalue, atrperiod in rtc_parameter_grid
        }
        self.x_c_flow_window = XCFlowWindow(
            length=flow_window,
            gradient_window=gradient_window,
            gradient_smoothing=gradient_smoothing,
        )
        self.x_c_flow_accumulator = XCFlowAccumulator(
            gradient_window=gradient_window,
            gradient_smoothing=gradient_smoothing,
        )
        self.rtc_state = RTCStateBlock(
            series_windows=series_windows,
            rtc_parameter_grid=rtc_parameter_grid,
            smoothing_window=rtc_smoothing_window,
            use_smoothing=rtc_use_smoothing,
        )

    def update(self, candle: Dict[str, float], is_close: bool = True) -> Dict[str, Any]:
        """Return a flattened calculation snapshot for the supplied candle."""
        if MAINTENANCE_MODE:
            log_maintenance_once("calculation.x_c_rtc_manager")
            return maintenance_payload(
                "calculation.x_c_rtc_manager",
                fields=(
                    "x_c_1",
                    "x_c_2",
                    "x_c_3",
                    "x_c_4",
                    "x_c_5",
                    "rtc_spread",
                ),
            )

        high = candle["high"]
        low = candle["low"]
        close = candle["close"]
        open_ = candle["open"]
        volume = candle["volume"]

        snapshot: Dict[str, Any] = {
            "time": candle.get("time"),
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
            "is_close": bool(is_close),
        }

        primary_snapshot = self.x_c_primary.update(high, low, close, is_close)
        if primary_snapshot:
            snapshot.update(primary_snapshot)

        flow_window_snapshot = self.x_c_flow_window.update(close, volume, is_close)
        if flow_window_snapshot:
            snapshot.update(flow_window_snapshot)

        flow_accumulator_snapshot = self.x_c_flow_accumulator.update(open_, close, volume, is_close)
        if flow_accumulator_snapshot:
            snapshot.update(flow_accumulator_snapshot)

        for length, block in self.x_c_series.items():
            values = block.update(close, is_close)
            if not values:
                continue
            for key, value in values.items():
                snapshot[f"x_c_series_{length}_{key}"] = value

        for key, block in self.rtc_blocks.items():
            values = block.update(high, low, close, is_close)
            if not values:
                continue
            for field, value in values.items():
                snapshot[f"rtc_{key}_{field}"] = value

        rtc_snapshot = self.rtc_state.update(snapshot, is_close)
        if rtc_snapshot:
            snapshot.update(rtc_snapshot)

        return snapshot

    def shutdown(self) -> None:
        """Compatibility hook."""

    def reset(self) -> None:
        self.x_c_primary.reset()
        for block in self.x_c_series.values():
            block.reset()
        for block in self.rtc_blocks.values():
            block.reset()
        self.x_c_flow_window.reset()
        self.x_c_flow_accumulator.reset()
        self.rtc_state.reset()
