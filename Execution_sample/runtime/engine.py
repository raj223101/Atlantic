from __future__ import annotations

import threading
import time
from collections import defaultdict
from time import perf_counter
from typing import Any, Dict, List, MutableMapping, Optional

from candle_engine.candle_builder import CandleBuilder
from config import ACTIVE_CANDLE_SYMBOLS, ACTIVE_TRADING_SYMBOLS, ALL_INSTRUMENTS, MAINTENANCE_CONTACT_MESSAGE, MAINTENANCE_MODE
from core.logger import log
from core.maintenance import log_maintenance_once
from core.state_memory import memory
from execution.multi_strategy_engine import StrategyRuntime, multi_strategy_engine
from execution.paper_broker import PaperBroker
from execution.signal_router import SignalRouter
from execution.time_manager import TimeManager
from calculation.x_c_rtc_engine import x_c_rtc_engine
from monitoring.performance_monitor import performance_monitor
from runtime.config import LowLatencyConfig
from runtime.events import TickEvent
from runtime.queues import BoundedQueue, QueueClosed
from runtime.tick_filter import SmartTickFilter
from storage.tick_saver import tick_saver


class LowLatencyTradingEngine:
    def __init__(
        self,
        *,
        signal_router: SignalRouter,
        last_price_store: Optional[MutableMapping[str, float]] = None,
        config: Optional[LowLatencyConfig] = None,
    ) -> None:
        self.config = config or LowLatencyConfig.from_runtime()
        self._signal_router = signal_router
        self._last_price_store = last_price_store if last_price_store is not None else {}
        self._filter = SmartTickFilter(self.config.dispatch_price_threshold)
        self._symbol_queues: Dict[str, BoundedQueue[TickEvent]] = {}
        self._symbol_threads: Dict[str, threading.Thread] = {}
        self._symbol_snapshots: Dict[str, Dict[int, Dict[str, Any]]] = defaultdict(dict)
        self._symbol_assignments: Dict[str, List[StrategyRuntime]] = {}
        self._mtm_thread: threading.Thread | None = None
        self._running = False
        self._lock = threading.RLock()
        self._mtm_lock = threading.RLock()
        self._unstable_until = 0.0
        self._dropped_events = 0
        self._queue_pressure_warned: set[str] = set()
        self._mtm_prices: Dict[str, tuple[float, Any]] = {}

    def start(self) -> None:
        with self._lock:
            if self._running:
                return

            runtimes = multi_strategy_engine.runtimes()
            self._symbol_assignments = self._build_symbol_assignments(runtimes)
            candle_symbols = [
                symbol
                for symbol in ACTIVE_CANDLE_SYMBOLS
                if symbol in ALL_INSTRUMENTS
            ]
            self._symbol_queues = {
                symbol: BoundedQueue(
                    maxsize=self.config.tick_queue_limit,
                    name=f"ticks_{symbol}",
                )
                for symbol in candle_symbols
            }
            self._symbol_threads = {
                symbol: threading.Thread(
                    target=self._symbol_worker,
                    name=f"SymbolWorker-{symbol}",
                    daemon=True,
                    args=(
                        symbol,
                        self._symbol_queues[symbol],
                        list(self._symbol_assignments.get(symbol, [])),
                    ),
                )
                for symbol in candle_symbols
            }
            self._symbol_snapshots = defaultdict(dict)
            self._queue_pressure_warned.clear()
            self._running = True

            for thread in self._symbol_threads.values():
                thread.start()

            self._mtm_thread = threading.Thread(
                target=self._mark_to_market_worker,
                name="MarkToMarketWorker",
                daemon=True,
            )
            self._mtm_thread.start()

        log.info(
            "[LowLatencyEngine] started | symbol_workers=%d symbols=%s",
            len(self._symbol_threads),
            ", ".join(self._symbol_threads),
        )
        if MAINTENANCE_MODE:
            log_maintenance_once("runtime.engine.start")
        performance_monitor.on_heartbeat(
            "low_latency_engine.start",
            {
                "symbol_workers": list(sorted(self._symbol_threads)),
                "tick_queue_limit": self.config.tick_queue_limit,
                "queue_put_timeout_ms": self.config.queue_put_timeout_ms,
                "maintenance_message": MAINTENANCE_CONTACT_MESSAGE if MAINTENANCE_MODE else "",
            },
        )

    def stop(self) -> None:
        with self._lock:
            if not self._running:
                return
            self._running = False
            symbol_queues = dict(self._symbol_queues)
            symbol_threads = dict(self._symbol_threads)
            mtm_thread = self._mtm_thread

        for queue in symbol_queues.values():
            queue.close()

        for thread in symbol_threads.values():
            thread.join(timeout=2.0)
        if mtm_thread is not None:
            mtm_thread.join(timeout=2.0)

        log.info("[LowLatencyEngine] stopped")

    def enqueue(self, symbol: str, ltp: float, ts, raw: dict) -> None:
        recv_epoch = time.time()
        tick = {
            "symbol": symbol,
            "ltp": ltp,
            "timestamp": ts,
            "volume": raw.get("volume", 0),
            "raw": dict(raw),
            "recv_epoch": recv_epoch,
        }
        self._last_price_store[symbol] = float(ltp)

        try:
            tick_saver.enqueue(tick)
        except Exception as exc:
            log.error("[LowLatencyEngine] tick save enqueue failed | symbol=%s error=%s", symbol, exc, exc_info=True)

        queue = self._symbol_queues.get(symbol)
        if queue is None:
            return

        event = TickEvent(
            symbol=symbol,
            tick=tick,
            recv_epoch=recv_epoch,
            sequence_number=int(raw.get("sequence_number", 0) or 0),
        )

        try:
            accepted = queue.put(
                event,
                timeout=max(float(self.config.queue_put_timeout_ms), 0.0) / 1000.0,
            )
        except QueueClosed:
            return

        queue_size = queue.qsize()
        self._observe_queue_pressure(symbol, queue)
        if not accepted:
            self._dropped_events += 1
            self._mark_unstable(
                f"symbol queue overloaded for {symbol}; rejected_newest=1",
            )
            performance_monitor.on_tick_queue_stats(queue_size=queue_size, dropped=1)
            log.warning(
                "[LowLatencyEngine] enqueue timeout | symbol=%s queue_size=%d high_watermark=%d",
                symbol,
                queue_size,
                queue.high_watermark(),
            )
            return

        performance_monitor.on_tick_received(
            symbol=symbol,
            tick_ts=ts,
            recv_epoch=recv_epoch,
            queue_size=queue_size,
            sequence_number=event.sequence_number,
        )

    def wait_for_idle(self, timeout_s: Optional[float] = None) -> bool:
        deadline = time.time() + float(timeout_s or self.config.idle_drain_timeout_s)
        while time.time() < deadline:
            if all(queue.empty() for queue in self._symbol_queues.values()):
                return True
            time.sleep(0.05)
        return False

    def last_prices_snapshot(self) -> Dict[str, float]:
        return dict(self._last_price_store)

    def stats(self) -> Dict[str, Any]:
        return {
            "symbol_queue_sizes": {
                symbol: queue.qsize()
                for symbol, queue in self._symbol_queues.items()
            },
            "symbol_queue_high_watermarks": {
                symbol: queue.high_watermark()
                for symbol, queue in self._symbol_queues.items()
            },
            "dropped_events": self._dropped_events,
            "unstable": self.is_unstable(),
            "symbol_workers": list(sorted(self._symbol_threads)),
            "assigned_strategies": {
                symbol: len(runtimes)
                for symbol, runtimes in self._symbol_assignments.items()
            },
        }

    def is_unstable(self) -> bool:
        return time.time() < self._unstable_until

    def _mark_unstable(self, reason: str) -> None:
        until = time.time() + self.config.load_shed_cooldown_s
        if until <= self._unstable_until:
            return
        self._unstable_until = until
        log.warning("[LowLatencyEngine] UNSTABLE | %s", reason)
        performance_monitor.on_heartbeat(
            "low_latency_engine.unstable",
            {"reason": reason, "until_epoch": until},
        )

    def _build_symbol_assignments(
        self,
        runtimes: List[StrategyRuntime],
    ) -> Dict[str, List[StrategyRuntime]]:
        assignments: Dict[str, List[StrategyRuntime]] = defaultdict(list)
        for runtime in runtimes:
            assignments[runtime.symbol].append(runtime)
        return {
            symbol: list(symbol_runtimes)
            for symbol, symbol_runtimes in assignments.items()
        }

    def _observe_queue_pressure(self, symbol: str, queue: BoundedQueue[TickEvent]) -> None:
        ratio = queue.qsize() / float(max(queue.maxsize, 1))
        if ratio >= float(self.config.queue_warning_ratio):
            if symbol not in self._queue_pressure_warned:
                self._queue_pressure_warned.add(symbol)
                log.warning(
                    "[LowLatencyEngine] queue pressure | symbol=%s size=%d/%d high_watermark=%d",
                    symbol,
                    queue.qsize(),
                    queue.maxsize,
                    queue.high_watermark(),
                )
            return
        self._queue_pressure_warned.discard(symbol)

    def _symbol_worker(
        self,
        symbol: str,
        queue: BoundedQueue[TickEvent],
        runtimes: List[StrategyRuntime],
    ) -> None:
        token = ALL_INSTRUMENTS[symbol]["token"]

        while self._running:
            try:
                event = queue.get(timeout=1.0)
            except TimeoutError:
                continue
            except QueueClosed:
                break

            started = perf_counter()
            queue_wait_ms = max((time.time() - event.recv_epoch) * 1000.0, 0.0)
            if queue_wait_ms > self.config.hard_latency_limit_ms:
                self._mark_unstable(
                    f"{symbol} tick wait {queue_wait_ms:.1f}ms exceeded hard limit",
                )

            tick = event.tick
            ts = tick["timestamp"]

            try:
                if not TimeManager.is_market_open(ts):
                    continue

                candle_started = perf_counter()
                live_candles = CandleBuilder.on_tick(token, tick)
                performance_monitor.on_stage(
                    "candle_builder",
                    (perf_counter() - candle_started) * 1000.0,
                )
                if not live_candles:
                    continue

                calculation_started = perf_counter()
                updates: Dict[int, Dict[str, Any]] = {}
                snapshot_book = self._symbol_snapshots[symbol]
                for tf, candle in live_candles.items():
                    snapshot = x_c_rtc_engine.on_tick(
                        symbol=symbol,
                        tf=tf,
                        price=tick["ltp"],
                        candle=candle,
                        is_close=False,
                    )
                    if snapshot:
                        memory.update_stats(symbol, tf, snapshot)
                        snapshot_copy = dict(snapshot)
                        updates[int(tf)] = snapshot_copy
                        snapshot_book[int(tf)] = snapshot_copy
                performance_monitor.on_stage(
                    "calculation_engine",
                    (perf_counter() - calculation_started) * 1000.0,
                )

                if symbol in ACTIVE_TRADING_SYMBOLS:
                    with self._mtm_lock:
                        self._mtm_prices[symbol] = (float(tick["ltp"]), ts)

                if not updates or symbol not in ACTIVE_TRADING_SYMBOLS:
                    continue

                if MAINTENANCE_MODE:
                    log_maintenance_once("runtime.engine.symbol_worker")
                    continue

                warmup_remaining = memory.consume_warmup_tick()
                if warmup_remaining is not None:
                    if warmup_remaining == 0:
                        log.info("[LowLatencyEngine] warmup complete | signals now live")
                    continue

                if not self._filter.should_dispatch(
                    symbol,
                    tick["ltp"],
                    live_candles,
                    unstable=self.is_unstable(),
                ):
                    continue

                signal_started = perf_counter()
                events = multi_strategy_engine.evaluate_runtimes(
                    runtimes=runtimes,
                    symbol=symbol,
                    price=float(tick["ltp"]),
                    snapshots_by_tf={
                        tf: dict(snapshot)
                        for tf, snapshot in snapshot_book.items()
                    },
                    ts=ts,
                )
                performance_monitor.on_stage(
                    "signal_generation",
                    (perf_counter() - signal_started) * 1000.0,
                )
                for signal_event in events:
                    self._dispatch_signal_event(signal_event, event.recv_epoch)
            except Exception as exc:
                log.error("[LowLatencyEngine] symbol worker failed | symbol=%s error=%s", symbol, exc, exc_info=True)
                self._mark_unstable(f"symbol worker error for {symbol}: {exc}")
            finally:
                elapsed_ms = (perf_counter() - started) * 1000.0
                performance_monitor.on_tick_processed(
                    symbol=symbol,
                    queue_size=queue.qsize(),
                    queue_wait_ms=queue_wait_ms,
                    processing_ms=elapsed_ms,
                    end_to_end_ms=max((time.time() - event.recv_epoch) * 1000.0, elapsed_ms),
                )
                performance_monitor.on_stage("tick_pipeline_market_data", elapsed_ms)

    def _dispatch_signal_event(self, event, recv_epoch: float) -> None:
        started = perf_counter()
        age_ms = max((time.time() - recv_epoch) * 1000.0, 0.0)
        current_price = float(self._last_price_store.get(event.symbol, event.price))
        drift = abs(current_price - float(event.price))

        if float(self.config.stale_signal_ms) > 0.0 and age_ms > float(self.config.stale_signal_ms):
            performance_monitor.on_signal(
                strategy_name=event.strategy_name,
                symbol=event.symbol,
                signal_name=event.signal.value,
                status="rejected",
                ts=event.ts,
            )
            log.warning(
                "[LowLatencyEngine] stale signal dropped | strategy=%s symbol=%s signal=%s age_ms=%.1f",
                event.strategy_name,
                event.symbol,
                event.signal.value,
                age_ms,
            )
            return

        if drift > self.config.signal_price_drift_limit:
            performance_monitor.on_signal(
                strategy_name=event.strategy_name,
                symbol=event.symbol,
                signal_name=event.signal.value,
                status="rejected",
                ts=event.ts,
            )
            log.warning(
                "[LowLatencyEngine] price drift reject | strategy=%s symbol=%s signal=%s drift=%.2f",
                event.strategy_name,
                event.symbol,
                event.signal.value,
                drift,
            )
            return

        self._signal_router.handle_signal_event(event, signal_age_ms=age_ms)
        performance_monitor.on_stage(
            "execution_worker",
            (perf_counter() - started) * 1000.0,
            strategy_name=event.strategy_name,
        )

    def _mark_to_market_worker(self) -> None:
        while self._running:
            time.sleep(0.25)
            with self._mtm_lock:
                prices = dict(self._mtm_prices)
            for symbol, (price, ts) in prices.items():
                try:
                    PaperBroker.mark_to_market(symbol, price, ts)
                except Exception as exc:
                    log.error(
                        "[LowLatencyEngine] mark-to-market failed | symbol=%s error=%s",
                        symbol,
                        exc,
                        exc_info=True,
                    )
