"""Generic calculation package exports."""

from .calc_cache import CalculationCache, calculation_cache
from .calc_lib import ATR, BBSlope, EMA, LinRegSlope, RMA, SMA, is_na, nz
from .rtc_state import RTCStateBlock
from .rtc_trigger import RTCTriggerBlock
from .x_c_rtc_engine import XCRTCEngine, x_c_rtc_engine
from .x_c_rtc_flow import XCFlowAccumulator, XCFlowWindow
from .x_c_rtc_manager import XCRTCManager
from .x_c_rtc_primary import XCRTCPrimaryBlock
from .x_c_rtc_series import XCRTCSeriesBlock

__all__ = [
    "ATR",
    "BBSlope",
    "CalculationCache",
    "EMA",
    "LinRegSlope",
    "RMA",
    "RTCStateBlock",
    "RTCTriggerBlock",
    "SMA",
    "XCFlowAccumulator",
    "XCFlowWindow",
    "XCRTCEngine",
    "XCRTCManager",
    "XCRTCPrimaryBlock",
    "XCRTCSeriesBlock",
    "calculation_cache",
    "is_na",
    "nz",
    "x_c_rtc_engine",
]
