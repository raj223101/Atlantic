"""
Live runtime bootstrap with startup signal warmup and option ladder priming.
"""

from __future__ import annotations

from candle_engine.candle_builder import CandleBuilder
from config import (
    ACTIVE_CANDLE_SYMBOLS,
    ALL_INSTRUMENTS,
    OPTION_LADDER_STRIKES_EACH_SIDE,
    RUNTIME_STARTUP_WARMUP_TICKS,
)
from core.logger import log
from core.state_memory import memory
from execution.history_loader import load_runtime_history
from execution.angel_option_service import angel_option_service
from execution.strategy_definitions import required_timeframes
from calculation.x_c_rtc_engine import x_c_rtc_engine


def initialize_live_runtime() -> None:
    candle_instruments = {
        symbol: ALL_INSTRUMENTS[symbol]
        for symbol in ACTIVE_CANDLE_SYMBOLS
        if symbol in ALL_INSTRUMENTS
    }
    active_timeframes = required_timeframes()

    memory.reset()
    x_c_rtc_engine.reset()
    CandleBuilder.reset()
    CandleBuilder.initialize(candle_instruments, active_timeframes)
    angel_option_service.prepare_contract_master()
    history_summary = load_runtime_history(candle_instruments, active_timeframes)

    for symbol in candle_instruments:
        CandleBuilder.mark_history_loaded(symbol)
        angel_option_service.request_ladder_subscription(
            symbol,
            OPTION_LADDER_STRIKES_EACH_SIDE,
        )

    warmup_ticks = max(int(RUNTIME_STARTUP_WARMUP_TICKS), 0)
    memory.set_value("warmup_required", warmup_ticks > 0)
    memory.set_value("warmup_ticks_remaining", warmup_ticks)

    loaded_frames = sum(len(tf_map) for tf_map in history_summary.values())
    loaded_candles = sum(count for tf_map in history_summary.values() for count in tf_map.values())

    log.info("=" * 60)
    log.info("  LIVE SESSION INITIALIZED")
    if loaded_frames > 0:
        log.info("  Historical warmup: enabled | frames=%d candles=%d", loaded_frames, loaded_candles)
    else:
        log.info("  Historical warmup: enabled | no prior candles loaded")
    log.info("  Startup warmup gate: %d ticks", warmup_ticks)
    if int(OPTION_LADDER_STRIKES_EACH_SIDE) > 0:
        log.info("  Option ladder depth: +/- %d strikes around ITM", int(OPTION_LADDER_STRIKES_EACH_SIDE))
    else:
        log.info("  Option watch: live ATM + 1x ITM + 2x ITM CE/PE per active index")
    log.info("  Candle Symbols: %s", ", ".join(candle_instruments))
    log.info("  Timeframes: %s", ", ".join(f"{tf}s" for tf in active_timeframes))
    log.info("=" * 60)
