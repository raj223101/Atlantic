"""
Live multi-timeframe OHLCV aggregation for Angel index ticks.
"""

from __future__ import annotations

import threading
from datetime import datetime
from typing import Dict, Optional, Tuple

from candle_engine.candle_state import TimeframeStateManager
from candle_engine.timeframe_manager import TimeframeManager
from core.logger import log
from core.state_memory import memory
from calculation.x_c_rtc_engine import x_c_rtc_engine
from storage.candle_saver import save_candle


class CandleBuilder:
    _timeframes: tuple[int, ...] = ()
    _state_managers: Dict[str, TimeframeStateManager] = {}
    _symbol_locks: Dict[str, threading.RLock] = {}
    _last_buckets: Dict[Tuple[str, int], int] = {}
    _last_bucket_date: Dict[Tuple[str, int], object] = {}
    _history_loaded: set[str] = set()
    _last_cum_vol: Dict[str, int] = {}
    _last_cum_vol_date: Dict[str, object] = {}
    _token_to_symbol: Dict[str, str] = {}
    _lock = threading.RLock()

    @classmethod
    def initialize(cls, instruments: Dict, timeframes: list[int]) -> None:
        normalized_timeframes = tuple(sorted(set(int(tf) for tf in timeframes)))
        with cls._lock:
            cls._timeframes = normalized_timeframes
            cls._state_managers = {
                symbol: TimeframeStateManager(symbol, list(normalized_timeframes))
                for symbol in instruments
            }
            cls._symbol_locks = {
                symbol: threading.RLock()
                for symbol in instruments
            }
            cls._last_buckets.clear()
            cls._last_bucket_date.clear()
            cls._history_loaded.clear()
            cls._last_cum_vol.clear()
            cls._last_cum_vol_date.clear()
            cls._token_to_symbol = {
                str(info["token"]): name
                for name, info in instruments.items()
            }

        log.info(
            "[CandleBuilder] initialized | instruments=%d timeframes=%d",
            len(instruments),
            len(normalized_timeframes),
        )

    @classmethod
    def reset(cls, symbol: Optional[str] = None) -> None:
        with cls._lock:
            if symbol is None:
                cls._timeframes = ()
                cls._state_managers.clear()
                cls._symbol_locks.clear()
                cls._last_buckets.clear()
                cls._last_bucket_date.clear()
                cls._history_loaded.clear()
                cls._last_cum_vol.clear()
                cls._last_cum_vol_date.clear()
                cls._token_to_symbol.clear()
                return

            cls._state_managers.pop(symbol, None)
            cls._symbol_locks.pop(symbol, None)
            cls._history_loaded.discard(symbol)
            cls._last_cum_vol.pop(symbol, None)
            cls._last_cum_vol_date.pop(symbol, None)
            for mapping in (cls._last_buckets, cls._last_bucket_date):
                keys = [key for key in mapping if key[0] == symbol]
                for key in keys:
                    del mapping[key]

    @classmethod
    def mark_history_loaded(cls, symbol: str) -> None:
        with cls._lock:
            cls._history_loaded.add(symbol)
        log.info("[CandleBuilder] %s ready for live ticks", symbol)

    @classmethod
    def get_state_manager(cls, symbol: str) -> Optional[TimeframeStateManager]:
        with cls._lock:
            return cls._state_managers.get(symbol)

    @classmethod
    def on_tick(cls, token: str, tick_data: dict) -> Dict[int, dict]:
        try:
            with cls._lock:
                symbol = cls._token_to_symbol.get(str(token))
                if symbol is None or symbol not in cls._history_loaded or not cls._timeframes:
                    return {}
                mgr = cls._state_managers.get(symbol)
                symbol_lock = cls._symbol_locks.get(symbol)
                timeframes = cls._timeframes

            if mgr is None or symbol_lock is None:
                return {}

            ltp = float(tick_data["ltp"])
            current_ts: datetime = tick_data["timestamp"]
            today = current_ts.date()
            cum_vol = int(tick_data.get("volume", 0))
            market_data = cls._market_data_from_tick(tick_data)

            with symbol_lock:
                prev_cum = cls._last_cum_vol.get(symbol, 0)
                prev_cum_date = cls._last_cum_vol_date.get(symbol)
                if prev_cum_date is not None and prev_cum_date != today:
                    prev_cum = 0

                vol_delta = max(0, cum_vol - prev_cum)
                cls._last_cum_vol[symbol] = cum_vol
                cls._last_cum_vol_date[symbol] = today

            live_candles: Dict[int, dict] = {}
            all_buckets = TimeframeManager.get_all_open_buckets(current_ts, timeframes)

            with symbol_lock:
                for tf_seconds in timeframes:
                    live_candle = cls._process_timeframe(
                        symbol=symbol,
                        tf_seconds=tf_seconds,
                        ltp=ltp,
                        vol_delta=vol_delta,
                        current_ts=current_ts,
                        today=today,
                        bucket_info=all_buckets[tf_seconds],
                        mgr=mgr,
                        market_data=market_data,
                    )
                    if live_candle is not None:
                        live_candles[tf_seconds] = live_candle

            return live_candles
        except Exception as exc:
            log.error("[CandleBuilder] tick processing failed: %s", exc, exc_info=True)
            return {}

    @classmethod
    def _process_timeframe(
        cls,
        symbol: str,
        tf_seconds: int,
        ltp: float,
        vol_delta: int,
        current_ts: datetime,
        today: object,
        bucket_info: Tuple[datetime, int],
        mgr: TimeframeStateManager,
        market_data: Dict,
    ) -> Optional[dict]:
        del current_ts

        key = (symbol, tf_seconds)
        candle_start, bucket_idx = bucket_info
        tf_state = mgr.get_state(tf_seconds)
        if tf_state is None:
            return None

        prev_date = cls._last_bucket_date.get(key)
        is_new_day = prev_date is not None and today != prev_date
        is_first_tick = key not in cls._last_buckets
        prev_bucket = cls._last_buckets.get(key)

        if is_first_tick or is_new_day:
            if is_new_day and not is_first_tick:
                cls._close_candle(symbol, tf_seconds, mgr)
            cls._open_candle(
                symbol,
                tf_seconds,
                candle_start,
                bucket_idx,
                today,
                ltp,
                vol_delta,
                tf_state,
                market_data,
            )
            return tf_state.get_current()

        if prev_bucket is not None and bucket_idx > prev_bucket:
            if bucket_idx - prev_bucket > 1:
                log.warning(
                    "[CandleBuilder] gap detected | symbol=%s tf=%ss missing=%d",
                    symbol,
                    tf_seconds,
                    bucket_idx - prev_bucket - 1,
                )
            cls._close_candle(symbol, tf_seconds, mgr)
            cls._open_candle(
                symbol,
                tf_seconds,
                candle_start,
                bucket_idx,
                today,
                ltp,
                vol_delta,
                tf_state,
                market_data,
            )
            return tf_state.get_current()

        tf_state.update_tick(ltp, vol_delta, market_data)
        memory.update_live_candle_tick(symbol, tf_seconds, ltp, vol_delta)
        return tf_state.get_current()

    @classmethod
    def _open_candle(
        cls,
        symbol: str,
        tf_seconds: int,
        candle_start: datetime,
        bucket_idx: int,
        today: object,
        ltp: float,
        vol_delta: int,
        tf_state,
        market_data: Dict,
    ) -> None:
        cls._last_buckets[(symbol, tf_seconds)] = bucket_idx
        cls._last_bucket_date[(symbol, tf_seconds)] = today
        tf_state.set_current_candle(candle_start, ltp, market_data)
        tf_state.update_tick(ltp, vol_delta, market_data)
        live_candle = tf_state.get_current()
        if live_candle is not None:
            memory.set_live_candle(symbol, tf_seconds, live_candle)
            memory.reset_calculation_stats(symbol, tf_seconds)

    @classmethod
    def _close_candle(
        cls,
        symbol: str,
        tf_seconds: int,
        mgr: TimeframeStateManager,
    ) -> None:
        tf_state = mgr.get_state(tf_seconds)
        if tf_state is None:
            return

        candle = tf_state.close_candle()
        if candle is None:
            return

        memory.clear_live_candle(symbol, tf_seconds)
        memory.update_closed_candle(symbol, tf_seconds, candle)
        snapshot = x_c_rtc_engine.on_candle_close(symbol, tf_seconds, candle)
        stats = memory.get_and_reset_stats(symbol, tf_seconds)
        save_candle(symbol, tf_seconds, candle, snapshot=snapshot, stats=stats)

    @staticmethod
    def _market_data_from_tick(tick_data: Dict) -> Dict:
        raw = tick_data.get("raw") or {}
        if not isinstance(raw, dict):
            return {}
        market = dict(raw)
        market.pop("raw_message", None)
        return market
