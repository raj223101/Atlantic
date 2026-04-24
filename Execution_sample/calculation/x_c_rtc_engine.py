"""Global calculation engine with shared per-(symbol, timeframe) managers and cache."""

from __future__ import annotations

import threading
from typing import Any, Dict, List, Optional, Tuple

from calculation.calc_cache import calculation_cache
from calculation.x_c_rtc_manager import XCRTCManager
from core.logger import log


def _fingerprint(candle: Dict[str, float], is_close: bool) -> Tuple[Any, ...]:
    return (
        candle.get("time"),
        round(float(candle["open"]), 10),
        round(float(candle["high"]), 10),
        round(float(candle["low"]), 10),
        round(float(candle["close"]), 10),
        int(candle.get("volume", 0)),
        bool(is_close),
    )


class XCRTCEngine:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._managers: Dict[tuple[str, int], XCRTCManager] = {}

    def _get_manager(self, symbol: str, tf: int) -> XCRTCManager:
        key = (symbol, tf)
        with self._lock:
            manager = self._managers.get(key)
            if manager is None:
                manager = XCRTCManager()
                self._managers[key] = manager
            return manager

    def warm_up(
        self,
        symbol: str,
        tf: int,
        candles: List[Dict[str, float]],
    ) -> Optional[Dict[str, Any]]:
        if not candles:
            return None

        manager = self._get_manager(symbol, tf)
        latest: Optional[Dict[str, Any]] = None
        for candle in candles:
            latest = manager.update(candle, is_close=True)
            calculation_cache.set(symbol, tf, _fingerprint(candle, True), latest)

        log.info(
            "[XCRTCEngine] warmup complete | symbol=%s tf=%ss candles=%d",
            symbol,
            tf,
            len(candles),
        )
        return latest

    def on_tick(
        self,
        symbol: str,
        tf: int,
        price: float,
        candle: Optional[Dict[str, float]] = None,
        is_close: bool = False,
    ) -> Optional[Dict[str, Any]]:
        if candle is None:
            candle = {
                "open": price,
                "high": price,
                "low": price,
                "close": price,
                "volume": 0,
            }

        fp = _fingerprint(candle, is_close)
        cached = calculation_cache.get(symbol, tf, fp)
        if cached is not None:
            return cached

        manager = self._get_manager(symbol, tf)
        try:
            snapshot = manager.update(candle, is_close=is_close)
        except Exception as exc:
            log.error(
                "[XCRTCEngine] tick update failed | symbol=%s tf=%ss error=%s",
                symbol,
                tf,
                exc,
                exc_info=True,
            )
            return None

        calculation_cache.set(symbol, tf, fp, snapshot)
        return snapshot

    def on_candle_close(
        self,
        symbol: str,
        tf: int,
        candle: Dict[str, float],
    ) -> Optional[Dict[str, Any]]:
        return self.on_tick(symbol, tf, candle["close"], candle=candle, is_close=True)

    on_candle = on_candle_close

    def reset(self, symbol: Optional[str] = None) -> None:
        with self._lock:
            if symbol is None:
                managers = list(self._managers.values())
                self._managers.clear()
            else:
                keys = [key for key in self._managers if key[0] == symbol]
                managers = [self._managers.pop(key) for key in keys]

        for manager in managers:
            manager.reset()
        if symbol is None:
            calculation_cache.invalidate()
            return
        calculation_cache.invalidate(symbol=symbol)

    def shutdown(self) -> None:
        with self._lock:
            managers = list(self._managers.values())
        for manager in managers:
            manager.shutdown()


x_c_rtc_engine = XCRTCEngine()
