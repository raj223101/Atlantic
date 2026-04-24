"""Thread-safe shared runtime state for live candles, calculation snapshots, and history."""

from __future__ import annotations

import math
import threading
from collections import defaultdict, deque
from typing import Any, Dict, List, Optional


class StateMemory:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._stats: Dict[tuple[str, int], Dict[str, float]] = defaultdict(dict)
        self.live_calculation_snapshots: Dict[str, Dict[int, Dict[str, Any]]] = defaultdict(
            lambda: defaultdict(dict)
        )
        self._candle_history: Dict[tuple[str, int], deque] = defaultdict(
            lambda: deque(maxlen=500)
        )
        self._live_candles: Dict[tuple[str, int], dict] = {}
        self._session_state: Dict[str, Any] = {}

    def set_live_candle(self, symbol: str, tf: int, candle: dict) -> None:
        with self._lock:
            self._live_candles[(symbol, tf)] = dict(candle)

    def get_live_candle(self, symbol: str, tf: int) -> Optional[dict]:
        with self._lock:
            candle = self._live_candles.get((symbol, tf))
            return dict(candle) if candle is not None else None

    def clear_live_candle(self, symbol: str, tf: int) -> None:
        with self._lock:
            self._live_candles.pop((symbol, tf), None)

    def update_live_candle_tick(
        self,
        symbol: str,
        tf: int,
        ltp: float,
        vol_delta: int = 0,
    ) -> None:
        with self._lock:
            candle = self._live_candles.get((symbol, tf))
            if candle is None:
                return
            candle["high"] = max(candle["high"], ltp)
            candle["low"] = min(candle["low"], ltp)
            candle["close"] = ltp
            candle["volume"] = candle.get("volume", 0) + int(vol_delta)

    def update_stats(self, symbol: str, tf: int, snapshot: Dict[str, Any]) -> None:
        if not snapshot:
            return

        with self._lock:
            stats = self._stats[(symbol, tf)]
            for field, value in snapshot.items():
                if isinstance(value, str) or value is None:
                    continue
                try:
                    numeric = float(value)
                except (TypeError, ValueError):
                    continue
                if math.isnan(numeric) or math.isinf(numeric):
                    continue

                max_key = f"{field}_max"
                min_key = f"{field}_min"
                if max_key not in stats or numeric > stats[max_key]:
                    stats[max_key] = numeric
                if min_key not in stats or numeric < stats[min_key]:
                    stats[min_key] = numeric

            self.live_calculation_snapshots[symbol][tf] = dict(snapshot)

    def reset_calculation_stats(self, symbol: str, tf: int) -> None:
        with self._lock:
            self._stats[(symbol, tf)] = {}

    def get_and_reset_stats(self, symbol: str, tf: int) -> Dict[str, float]:
        with self._lock:
            key = (symbol, tf)
            stats = dict(self._stats.get(key, {}))
            self._stats[key] = {}
            return stats

    def get_stats(self, symbol: str, tf: int) -> Dict[str, float]:
        with self._lock:
            return dict(self._stats.get((symbol, tf), {}))

    def update_closed_candle(self, symbol: str, tf: int, candle: dict) -> None:
        with self._lock:
            self._candle_history[(symbol, tf)].append(dict(candle))

    def get_candle_history(self, symbol: str, tf: int) -> List[dict]:
        with self._lock:
            return list(self._candle_history.get((symbol, tf), []))

    def get_last_candle(self, symbol: str, tf: int) -> Optional[dict]:
        with self._lock:
            history = self._candle_history.get((symbol, tf))
            if history:
                return dict(history[-1])
            return None

    def set_value(self, key: str, value: Any) -> None:
        with self._lock:
            self._session_state[str(key)] = value

    def get_value(self, key: str, default: Any = None) -> Any:
        with self._lock:
            return self._session_state.get(str(key), default)

    def consume_warmup_tick(self) -> Optional[int]:
        with self._lock:
            if not bool(self._session_state.get("warmup_required", False)):
                return None

            remaining = int(self._session_state.get("warmup_ticks_remaining", 0) or 0)
            remaining = max(remaining - 1, 0)
            self._session_state["warmup_ticks_remaining"] = remaining
            if remaining <= 0:
                self._session_state["warmup_required"] = False
            return remaining

    def reset(self, symbol: Optional[str] = None) -> None:
        with self._lock:
            if symbol is None:
                self._stats.clear()
                self.live_calculation_snapshots.clear()
                self._candle_history.clear()
                self._live_candles.clear()
                self._session_state.clear()
                return

            for store in (self._stats, self._candle_history, self._live_candles):
                keys = [key for key in store if key[0] == symbol]
                for key in keys:
                    del store[key]

            self.live_calculation_snapshots.pop(symbol, None)


memory = StateMemory()
