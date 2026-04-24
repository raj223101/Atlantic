"""
End-of-day force exit and session reset helpers.
"""

from __future__ import annotations

from datetime import datetime

from candle_engine.candle_builder import CandleBuilder
from core.logger import log
from core.state_memory import memory
from execution.paper_broker import PaperBroker
from execution.signal_router import signal_router
from execution.time_manager import TimeManager
from calculation.x_c_rtc_engine import x_c_rtc_engine

_done = False


def check_and_force_exit(price_map: dict) -> None:
    global _done
    if _done or not TimeManager.check_force_exit():
        return

    ts = datetime.now()
    closed = PaperBroker.force_exit_all(price_map, ts, "FORCE_EXIT_EOD")
    log.info("[ForceExit] EOD force exit | closed_positions=%d", closed)

    signal_router.reset()
    x_c_rtc_engine.reset()
    memory.reset()
    CandleBuilder.reset()
    PaperBroker.print_summary()
    _done = True


def reset_for_new_session() -> None:
    global _done
    _done = False
