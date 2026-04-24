"""
candle_state.py — Per-timeframe candle state management.

NEW: Handles all 7 timeframes simultaneously with minimal memory overhead.
Uses fixed-size ring buffers for efficient storage.
"""

from datetime import datetime
from typing import Dict, Optional, List
from collections import deque
from core.logger import log


class CandleState:
    """Manages OHLCV state for a single timeframe."""

    def __init__(self, symbol: str, tf_seconds: int, max_history: int = 500):
        self.symbol = symbol
        self.tf_seconds = tf_seconds
        self.max_history = max_history

        # Current in-progress candle
        self._current: Optional[Dict] = None
        self._current_bucket: Optional[int] = None

        # Closed candles (ring buffer)
        self._history: deque = deque(maxlen=max_history)

    def set_current_candle(self, time: datetime, open_: float, market_data: Optional[Dict] = None) -> None:
        """Initialize a new candle at candle open."""
        self._current = {
            "time": time,
            "open": open_,
            "high": open_,
            "low": open_,
            "close": open_,
            "volume": 0,
            "tick_count": 0,
        }
        if market_data:
            self._merge_market_data(market_data)

    def update_tick(self, ltp: float, volume_delta: int, market_data: Optional[Dict] = None) -> None:
        """Update current candle with intrabar tick."""
        if self._current is None:
            return

        self._current["high"] = max(self._current["high"], ltp)
        self._current["low"] = min(self._current["low"], ltp)
        self._current["close"] = ltp
        self._current["volume"] += volume_delta
        self._current["tick_count"] = int(self._current.get("tick_count", 0)) + 1
        if market_data:
            self._merge_market_data(market_data)

    def close_candle(self) -> Optional[Dict]:
        """Close current candle and store in history."""
        if self._current is None:
            return None

        closed = dict(self._current)
        self._history.append(closed)
        self._current = None
        self._current_bucket = None
        return closed

    def get_current(self) -> Optional[Dict]:
        """Get current in-progress candle."""
        return dict(self._current) if self._current else None

    def get_history(self, limit: Optional[int] = None) -> List[Dict]:
        """Get closed candle history."""
        if limit is None:
            return list(self._history)
        return list(self._history)[-limit:] if limit > 0 else []

    def get_last_closed(self) -> Optional[Dict]:
        """Get most recent closed candle."""
        if len(self._history) == 0:
            return None
        return dict(self._history[-1])

    def reset(self) -> None:
        """Reset all state."""
        self._current = None
        self._current_bucket = None
        self._history.clear()

    def _merge_market_data(self, market_data: Dict) -> None:
        if self._current is None:
            return

        for key, value in market_data.items():
            if key in {"open_interest", "best_bid_price", "best_ask_price"}:
                previous = self._current.get(key)
                self._current[key] = value
                if key == "open_interest":
                    if previous is None:
                        self._current["open_interest_high"] = value
                        self._current["open_interest_low"] = value
                    else:
                        self._current["open_interest_high"] = max(
                            float(self._current.get("open_interest_high", value)),
                            float(value),
                        )
                        self._current["open_interest_low"] = min(
                            float(self._current.get("open_interest_low", value)),
                            float(value),
                        )
                continue

            self._current[key] = value


class TimeframeStateManager:
    """Manages candle state for all timeframes of a symbol."""

    def __init__(self, symbol: str, timeframes: List[int]):
        self.symbol = symbol
        self.timeframes = timeframes
        self._states: Dict[int, CandleState] = {
            tf: CandleState(symbol, tf)
            for tf in timeframes
        }

    def get_state(self, tf: int) -> Optional[CandleState]:
        """Get candle state for a timeframe."""
        return self._states.get(tf)

    def get_all_states(self) -> Dict[int, CandleState]:
        """Get all timeframe states."""
        return dict(self._states)

    def reset(self) -> None:
        """Reset all timeframe states."""
        for state in self._states.values():
            state.reset()
