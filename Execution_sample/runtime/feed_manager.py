from __future__ import annotations

import threading
import time

from core.logger import log
from feeds.angel_feed import AngelFeed
from monitoring.performance_monitor import performance_monitor
from runtime.engine import LowLatencyTradingEngine


class LowLatencyFeedManager:
    def __init__(self, auth_token: str, feed_token: str, engine: LowLatencyTradingEngine):
        self._engine = engine
        self._angel = AngelFeed(auth_token, feed_token, engine)
        self._health_thread: threading.Thread | None = None
        self._running = False

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._engine.start()
        self._angel.start()
        self._health_thread = threading.Thread(
            target=self._health_loop,
            name="LowLatencyHealth",
            daemon=True,
        )
        self._health_thread.start()
        log.info("[LowLatencyFeedManager] Started")

    def stop(self) -> None:
        self._running = False
        try:
            self._angel.stop()
        finally:
            self._engine.stop()
        log.info("[LowLatencyFeedManager] stop requested")

    def _health_loop(self) -> None:
        while self._running:
            time.sleep(30)
            stats = self._engine.stats()
            performance_monitor.on_heartbeat("low_latency_engine", stats)
            symbol_queue_sizes = stats.get("symbol_queue_sizes", {})
            symbol_high_watermarks = stats.get("symbol_queue_high_watermarks", {})
            assigned_strategies = stats.get("assigned_strategies", {})
            hottest_symbol = max(
                symbol_queue_sizes,
                key=symbol_queue_sizes.get,
                default="-",
            )
            log.info(
                "[LowLatencyEngine] lanes=%d hottest=%s queue=%d high_watermark=%d dropped=%d unstable=%s strategy_assignments=%s",
                len(symbol_queue_sizes),
                hottest_symbol,
                max(symbol_queue_sizes.values(), default=0),
                max(symbol_high_watermarks.values(), default=0),
                stats.get("dropped_events", 0),
                stats.get("unstable", False),
                ", ".join(
                    f"{symbol}:{assigned_strategies.get(symbol, 0)}"
                    for symbol in sorted(symbol_queue_sizes)
                ) or "-",
            )
