from __future__ import annotations

import threading
from typing import Dict


class SmartTickFilter:
    def __init__(self, price_change_threshold: float) -> None:
        self._price_change_threshold = max(float(price_change_threshold), 0.0)
        self._lock = threading.RLock()
        self._state: Dict[str, Dict] = {}

    def should_dispatch(
        self,
        symbol: str,
        price: float,
        live_candles: Dict[int, dict],
        *,
        unstable: bool = False,
    ) -> bool:
        threshold = self._price_change_threshold * (2.0 if unstable else 1.0)
        with self._lock:
            state = self._state.setdefault(symbol, {"last_price": None, "buckets": {}})
            current_buckets = {
                int(tf): candle.get("time")
                for tf, candle in live_candles.items()
                if candle is not None
            }
            bucket_changed = any(
                current_buckets.get(tf) != state["buckets"].get(tf)
                for tf in current_buckets
            )
            last_price = state["last_price"]
            significant = last_price is None or abs(price - float(last_price)) >= threshold
            if bucket_changed or significant:
                state["last_price"] = float(price)
                state["buckets"] = current_buckets
                return True
            return False
