"""Shared calculation snapshot cache keyed by symbol, timeframe, and candle state."""

from __future__ import annotations

import threading
import time
from typing import Any, Dict, Optional, Tuple


class CalculationCache:
    def __init__(self, max_age_ms: int = 250) -> None:
        self._lock = threading.RLock()
        self._max_age_s = max_age_ms / 1000.0
        self._cache: Dict[tuple[str, int], Dict[str, Any]] = {}
        self._stats = {
            "hits": 0,
            "misses": 0,
            "writes": 0,
            "invalidations": 0,
        }

    def get(
        self,
        symbol: str,
        tf: int,
        fingerprint: Tuple[Any, ...],
    ) -> Optional[Dict[str, Any]]:
        with self._lock:
            entry = self._cache.get((symbol, tf))
            if entry is None:
                self._stats["misses"] += 1
                return None

            if entry["fingerprint"] != fingerprint:
                self._stats["misses"] += 1
                return None

            if time.monotonic() - entry["updated_at"] > self._max_age_s:
                self._cache.pop((symbol, tf), None)
                self._stats["invalidations"] += 1
                self._stats["misses"] += 1
                return None

            self._stats["hits"] += 1
            return dict(entry["snapshot"])

    def set(
        self,
        symbol: str,
        tf: int,
        fingerprint: Tuple[Any, ...],
        snapshot: Dict[str, Any],
    ) -> None:
        with self._lock:
            self._cache[(symbol, tf)] = {
                "fingerprint": fingerprint,
                "snapshot": dict(snapshot),
                "updated_at": time.monotonic(),
            }
            self._stats["writes"] += 1

    def get_latest_snapshot(self, symbol: str, tf: int) -> Optional[Dict[str, Any]]:
        with self._lock:
            entry = self._cache.get((symbol, tf))
            if entry is None:
                return None
            if time.monotonic() - entry["updated_at"] > self._max_age_s:
                self._cache.pop((symbol, tf), None)
                self._stats["invalidations"] += 1
                return None
            return dict(entry["snapshot"])

    def invalidate(self, symbol: Optional[str] = None, tf: Optional[int] = None) -> int:
        with self._lock:
            keys = [
                key
                for key in self._cache
                if (symbol is None or key[0] == symbol)
                and (tf is None or key[1] == tf)
            ]
            for key in keys:
                del self._cache[key]
            self._stats["invalidations"] += len(keys)
            return len(keys)

    def reset_stats(self) -> None:
        with self._lock:
            for key in self._stats:
                self._stats[key] = 0

    def get_stats(self) -> Dict[str, float]:
        with self._lock:
            total = self._stats["hits"] + self._stats["misses"]
            hit_rate = (self._stats["hits"] / total * 100.0) if total else 0.0
            return {
                **self._stats,
                "total_lookups": total,
                "hit_rate_pct": round(hit_rate, 2),
                "cache_size": len(self._cache),
            }


calculation_cache = CalculationCache(max_age_ms=250)
