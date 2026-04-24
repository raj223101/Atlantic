"""
Lossless asynchronous tick queue.

The websocket producer must never block and ticks must not be dropped, so the
queue is intentionally unbounded. Backpressure is surfaced through queue-depth
metrics and slow-tick warnings rather than lossy overflow handling.
"""

from __future__ import annotations

import queue
import threading
import time
from datetime import datetime

from core.logger import log
from monitoring.performance_monitor import performance_monitor
from storage.tick_saver import tick_saver

CIRCUIT_BREAKER_THRESHOLD = 10
CIRCUIT_BREAKER_PAUSE_S = 30
SLOW_TICK_WARN_MS = 20


class TickQueue:
    def __init__(self, on_tick_fn, maxsize: int = 0):
        self._q = queue.Queue(maxsize=0)
        self._on_tick = on_tick_fn
        self._running = False
        self._thread = None

        self._processed = 0
        self._dropped = 0
        self._consec_errors = 0
        self._cb_active = False
        self._cb_trip_count = 0

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(target=self._worker, name="TickWorker", daemon=True)
        self._thread.start()
        log.info("[TickQueue] worker started")

    def stop(self) -> None:
        self._running = False
        log.info("[TickQueue] stop requested")

    def enqueue(self, symbol: str, ltp: float, ts: datetime, raw: dict) -> None:
        tick = {
            "symbol": symbol,
            "ltp": ltp,
            "timestamp": ts,
            "volume": raw.get("volume", 0),
            "raw": dict(raw),
            "recv_epoch": time.time(),
        }
        try:
            tick_saver.enqueue(tick)
        except Exception as exc:
            log.error(
                "[TickQueue] tick save enqueue failed | symbol=%s error=%s",
                symbol,
                exc,
                exc_info=True,
            )
        self._q.put_nowait(tick)
        performance_monitor.on_tick_received(
            symbol=symbol,
            tick_ts=ts,
            recv_epoch=tick["recv_epoch"],
            queue_size=self._q.qsize(),
            sequence_number=raw.get("sequence_number"),
        )

    def stats(self) -> dict:
        return {
            "queued": self._q.qsize(),
            "processed": self._processed,
            "dropped": self._dropped,
            "cb_trips": self._cb_trip_count,
        }

    def _worker(self) -> None:
        log.info("[TickQueue] worker ready")
        while self._running:
            if self._cb_active:
                log.warning(
                    "[TickQueue] circuit breaker active | pause=%ss trips=%d",
                    CIRCUIT_BREAKER_PAUSE_S,
                    self._cb_trip_count,
                )
                time.sleep(CIRCUIT_BREAKER_PAUSE_S)
                self._cb_active = False
                self._consec_errors = 0
                continue

            try:
                tick = self._q.get(timeout=1.0)
            except queue.Empty:
                continue

            started = time.perf_counter()
            started_epoch = time.time()
            try:
                self._on_tick(tick["symbol"], tick)
                self._processed += 1
                self._consec_errors = 0
                elapsed_ms = (time.perf_counter() - started) * 1000.0
                performance_monitor.on_tick_processed(
                    symbol=tick["symbol"],
                    queue_size=self._q.qsize(),
                    queue_wait_ms=max((started_epoch - tick["recv_epoch"]) * 1000.0, 0.0),
                    processing_ms=elapsed_ms,
                    end_to_end_ms=max((time.time() - tick["recv_epoch"]) * 1000.0, elapsed_ms),
                )
                if elapsed_ms > SLOW_TICK_WARN_MS:
                    log.warning(
                        "[TickQueue] slow tick | ms=%.1f symbol=%s queue=%d",
                        elapsed_ms,
                        tick["symbol"],
                        self._q.qsize(),
                    )
            except Exception as exc:
                self._consec_errors += 1
                elapsed_ms = (time.perf_counter() - started) * 1000.0
                performance_monitor.on_tick_processed(
                    symbol=tick["symbol"],
                    queue_size=self._q.qsize(),
                    queue_wait_ms=max((started_epoch - tick["recv_epoch"]) * 1000.0, 0.0),
                    processing_ms=elapsed_ms,
                    end_to_end_ms=max((time.time() - tick["recv_epoch"]) * 1000.0, elapsed_ms),
                    dropped=True,
                )
                log.error(
                    "[TickQueue] tick processing failed | consecutive=%d error=%s",
                    self._consec_errors,
                    exc,
                    exc_info=True,
                )
                if self._consec_errors >= CIRCUIT_BREAKER_THRESHOLD:
                    self._cb_trip_count += 1
                    self._cb_active = True

        log.info("[TickQueue] worker stopped")
