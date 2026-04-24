from __future__ import annotations

from collections import Counter, deque, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
import os
import threading
import time
from typing import Any, Optional

from monitoring.config import MonitorConfig
from monitoring.stats import RateTracker, RatioTracker, ReasonCounter, RollingStats


@dataclass
class APIMetricsState:
    response_ms: RollingStats
    outcomes: RatioTracker = field(default_factory=RatioTracker)
    timeouts: int = 0
    retries: int = 0
    last_error: str = ""

    def snapshot(self, failure_limit_pct: float) -> dict:
        response = self.response_ms.summary().as_dict()
        health = "HEALTHY"
        if self.outcomes.failure_pct >= failure_limit_pct:
            health = "FAILED"
        elif self.outcomes.failure_pct >= max(failure_limit_pct / 2.0, 1.0) or self.timeouts > 0:
            health = "DEGRADED"
        return {
            "success_total": self.outcomes.success,
            "failure_total": self.outcomes.failure,
            "success_pct": self.outcomes.success_pct,
            "failure_pct": self.outcomes.failure_pct,
            "timeout_total": self.timeouts,
            "retry_total": self.retries,
            "response_ms": response,
            "health": health,
            "last_error": self.last_error,
        }


@dataclass
class StrategyMetricsState:
    pnl: float = 0.0
    wins: int = 0
    losses: int = 0
    signals_generated: int = 0
    signals_rejected: int = 0
    orders_placed: int = 0
    orders_filled: int = 0
    orders_rejected: int = 0
    latency_ms: RollingStats = field(default_factory=RollingStats)
    fill_latency_ms: RollingStats = field(default_factory=RollingStats)
    slippage: RollingStats = field(default_factory=RollingStats)

    def snapshot(self) -> dict:
        trades = self.wins + self.losses
        win_rate = (self.wins / trades) * 100.0 if trades > 0 else 0.0
        execution_success = (self.orders_filled / self.orders_placed) * 100.0 if self.orders_placed > 0 else 0.0
        return {
            "pnl": self.pnl,
            "wins": self.wins,
            "losses": self.losses,
            "win_rate_pct": win_rate,
            "signals_generated": self.signals_generated,
            "signals_rejected": self.signals_rejected,
            "orders_placed": self.orders_placed,
            "orders_filled": self.orders_filled,
            "orders_rejected": self.orders_rejected,
            "execution_success_rate_pct": execution_success,
            "avg_latency_ms": self.latency_ms.summary().avg,
            "fill_latency_ms": self.fill_latency_ms.summary().as_dict(),
            "slippage": self.slippage.summary().as_dict(),
        }


class ResourceSampler:
    def __init__(self) -> None:
        self._last_wall = time.perf_counter()
        self._last_cpu = time.process_time()

    def sample(self) -> dict:
        wall = time.perf_counter()
        cpu = time.process_time()
        elapsed_wall = max(wall - self._last_wall, 1e-6)
        elapsed_cpu = max(cpu - self._last_cpu, 0.0)
        self._last_wall = wall
        self._last_cpu = cpu

        cpu_pct = (elapsed_cpu / elapsed_wall) * 100.0 / max(os.cpu_count() or 1, 1)
        memory_mb = self._memory_mb()
        thread_count = threading.active_count()
        process_count = 1
        io_wait_pct = None

        try:
            import psutil  # type: ignore

            proc = psutil.Process(os.getpid())
            process_count = len(psutil.pids())
            io_wait_pct = getattr(psutil.cpu_times_percent(interval=None), "iowait", None)
            memory_mb = proc.memory_info().rss / (1024.0 * 1024.0)
            cpu_pct = max(proc.cpu_percent(interval=None) / max(os.cpu_count() or 1, 1), cpu_pct)
        except Exception:
            pass

        return {
            "cpu_pct": round(cpu_pct, 2),
            "memory_mb": round(memory_mb, 2),
            "thread_count": thread_count,
            "process_count": process_count,
            "io_wait_pct": round(io_wait_pct, 2) if io_wait_pct is not None else None,
        }

    def _memory_mb(self) -> float:
        try:
            import psutil  # type: ignore

            return psutil.Process(os.getpid()).memory_info().rss / (1024.0 * 1024.0)
        except Exception:
            pass

        if os.name == "nt":
            try:
                import ctypes
                from ctypes import wintypes

                class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
                    _fields_ = [
                        ("cb", wintypes.DWORD),
                        ("PageFaultCount", wintypes.DWORD),
                        ("PeakWorkingSetSize", ctypes.c_size_t),
                        ("WorkingSetSize", ctypes.c_size_t),
                        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                        ("PagefileUsage", ctypes.c_size_t),
                        ("PeakPagefileUsage", ctypes.c_size_t),
                    ]

                counters = PROCESS_MEMORY_COUNTERS()
                counters.cb = ctypes.sizeof(counters)
                proc = ctypes.windll.kernel32.GetCurrentProcess()
                ok = ctypes.windll.psapi.GetProcessMemoryInfo(proc, ctypes.byref(counters), counters.cb)
                if ok:
                    return counters.WorkingSetSize / (1024.0 * 1024.0)
            except Exception:
                return 0.0
        else:
            try:
                import resource

                usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
                if usage > 1024 * 1024:
                    return usage / (1024.0 * 1024.0)
                return usage / 1024.0
            except Exception:
                return 0.0
        return 0.0


class MetricsCollector:
    def __init__(self, config: MonitorConfig) -> None:
        self.config = config
        self._lock = threading.RLock()
        self.started_at = time.time()
        self.resource_sampler = ResourceSampler()

        self.tick_rate = RateTracker(config.rate_window_s)
        self.signal_rate = RateTracker(config.rate_window_s)
        self.order_rate = RateTracker(config.rate_window_s)

        self.tick_delay_ms = RollingStats(config.snapshot_window)
        self.tick_queue_size = RollingStats(config.snapshot_window)
        self.tick_queue_wait_ms = RollingStats(config.snapshot_window)
        self.tick_processing_ms = RollingStats(config.snapshot_window)
        self.end_to_end_ms = RollingStats(config.snapshot_window)

        self.stage_latencies: dict[str, RollingStats] = defaultdict(
            lambda: RollingStats(config.snapshot_window)
        )
        self.api_metrics: dict[str, APIMetricsState] = defaultdict(
            lambda: APIMetricsState(response_ms=RollingStats(config.snapshot_window))
        )
        self.strategy_metrics: dict[str, StrategyMetricsState] = defaultdict(StrategyMetricsState)

        self.signal_counts = Counter()
        self.order_counts = Counter()
        self.execution_counts = Counter()
        self.rejection_reasons = ReasonCounter()
        self.recent_signals: deque[tuple[str, str, str, str]] = deque(maxlen=2000)
        self.recent_signal_index: set[tuple[str, str, str, str]] = set()

        self.tick_gaps = 0
        self.tick_duplicates = 0
        self.tick_out_of_order = 0
        self.tick_drops = 0
        self.slow_ticks = 0

        self.last_tick_ts_by_symbol: dict[str, datetime] = {}
        self.last_seq_by_symbol: dict[str, int] = {}
        self.last_resources: dict[str, Any] = {}

    def record_tick_received(
        self,
        *,
        symbol: str,
        tick_ts: datetime,
        recv_epoch: float,
        queue_size: int,
        sequence_number: Optional[int] = None,
    ) -> None:
        with self._lock:
            now = time.time()
            self.tick_rate.mark(now)
            self.tick_delay_ms.add((recv_epoch - tick_ts.timestamp()) * 1000.0)
            self.tick_queue_size.add(queue_size)

            prev_ts = self.last_tick_ts_by_symbol.get(symbol)
            if prev_ts is not None:
                if tick_ts < prev_ts:
                    self.tick_out_of_order += 1
                elif tick_ts == prev_ts:
                    self.tick_duplicates += 1
            self.last_tick_ts_by_symbol[symbol] = tick_ts

            if sequence_number is not None:
                prev_seq = self.last_seq_by_symbol.get(symbol)
                if prev_seq is not None:
                    if sequence_number == prev_seq:
                        self.tick_duplicates += 1
                    elif sequence_number > prev_seq + 1:
                        self.tick_gaps += sequence_number - prev_seq - 1
                self.last_seq_by_symbol[symbol] = sequence_number

    def record_tick_processed(
        self,
        *,
        symbol: str,
        queue_size: int,
        queue_wait_ms: float,
        processing_ms: float,
        end_to_end_ms: float,
        dropped: bool = False,
    ) -> None:
        del symbol
        with self._lock:
            self.tick_queue_size.add(queue_size)
            self.tick_queue_wait_ms.add(queue_wait_ms)
            self.tick_processing_ms.add(processing_ms)
            self.end_to_end_ms.add(end_to_end_ms)
            if processing_ms > self.config.slow_tick_limit_ms:
                self.slow_ticks += 1
            if dropped:
                self.tick_drops += 1

    def record_stage_latency(
        self,
        stage: str,
        elapsed_ms: float,
        *,
        strategy_name: Optional[str] = None,
    ) -> None:
        with self._lock:
            self.stage_latencies[stage].add(elapsed_ms)
            if strategy_name:
                self.strategy_metrics[strategy_name].latency_ms.add(elapsed_ms)

    def record_api_call(
        self,
        *,
        service: str,
        operation: str,
        success: bool,
        elapsed_ms: float,
        retries: int = 0,
        timeout: bool = False,
        error: str = "",
    ) -> None:
        key = f"{service}.{operation}"
        with self._lock:
            state = self.api_metrics[key]
            state.response_ms.add(elapsed_ms)
            state.outcomes.record(success)
            state.retries += max(int(retries), 0)
            if timeout:
                state.timeouts += 1
            if error:
                state.last_error = error

    def record_signal(
        self,
        *,
        strategy_name: str,
        symbol: str,
        signal_name: str,
        ts: datetime,
        status: str,
    ) -> None:
        key = (strategy_name, symbol, signal_name, ts.isoformat())
        with self._lock:
            if status == "generated":
                self.signal_counts["generated"] += 1
                self.signal_rate.mark()
                self.strategy_metrics[strategy_name].signals_generated += 1
                if key in self.recent_signal_index:
                    self.signal_counts["duplicate"] += 1
                else:
                    if len(self.recent_signals) == self.recent_signals.maxlen:
                        dropped = self.recent_signals.popleft()
                        self.recent_signal_index.discard(dropped)
                    self.recent_signals.append(key)
                    self.recent_signal_index.add(key)
            elif status == "rejected":
                self.signal_counts["rejected"] += 1
                self.strategy_metrics[strategy_name].signals_rejected += 1
            elif status == "filled":
                self.signal_counts["filled"] += 1

    def record_order(
        self,
        *,
        strategy_name: str,
        symbol: str,
        order_side: str,
        order_kind: str,
        status: str,
        latency_ms: float = 0.0,
        fill_latency_ms: float = 0.0,
        slippage: float = 0.0,
        reason: str = "",
    ) -> None:
        del symbol, order_side, order_kind
        with self._lock:
            if status == "attempted":
                self.order_counts["attempted"] += 1
                self.order_rate.mark()
                self.strategy_metrics[strategy_name].orders_placed += 1
            elif status == "filled":
                self.order_counts["filled"] += 1
                self.execution_counts["filled"] += 1
                self.strategy_metrics[strategy_name].orders_filled += 1
                self.strategy_metrics[strategy_name].fill_latency_ms.add(fill_latency_ms or latency_ms)
                self.strategy_metrics[strategy_name].slippage.add(slippage)
                self.signal_counts["filled"] += 1
            elif status == "rejected":
                self.order_counts["rejected"] += 1
                self.execution_counts["rejected"] += 1
                self.strategy_metrics[strategy_name].orders_rejected += 1
                self.rejection_reasons.add(reason)
            if latency_ms > 0:
                self.strategy_metrics[strategy_name].latency_ms.add(latency_ms)

    def record_trade_close(
        self,
        *,
        strategy_name: str,
        pnl: float,
        win: bool,
    ) -> None:
        with self._lock:
            metrics = self.strategy_metrics[strategy_name]
            metrics.pnl += pnl
            if win:
                metrics.wins += 1
            else:
                metrics.losses += 1

    def update_resources(self) -> dict:
        with self._lock:
            self.last_resources = self.resource_sampler.sample()
            return dict(self.last_resources)

    def snapshot(self) -> dict:
        with self._lock:
            api_summary_success = sum(item.outcomes.success for item in self.api_metrics.values())
            api_summary_failure = sum(item.outcomes.failure for item in self.api_metrics.values())
            api_total = api_summary_success + api_summary_failure
            api_success_pct = (api_summary_success / api_total) * 100.0 if api_total > 0 else 100.0
            api_failure_pct = (api_summary_failure / api_total) * 100.0 if api_total > 0 else 0.0
            signal_generated = self.signal_counts.get("generated", 0)
            signal_filled = self.signal_counts.get("filled", 0)
            fill_rate = (signal_filled / signal_generated) * 100.0 if signal_generated > 0 else 0.0

            underperformers = [
                {"strategy": name, **metrics.snapshot()}
                for name, metrics in self.strategy_metrics.items()
                if metrics.snapshot()["pnl"] < 0 or metrics.snapshot()["execution_success_rate_pct"] < 50.0
            ]
            underperformers.sort(key=lambda item: (item["pnl"], item["execution_success_rate_pct"]))

            return {
                "ts": datetime.now().isoformat(),
                "uptime_s": round(time.time() - self.started_at, 2),
                "tick_health": {
                    "tick_rate_per_sec": self.tick_rate.rate(),
                    "delay_ms": self.tick_delay_ms.summary().as_dict(),
                    "queue_size": self.tick_queue_size.summary().as_dict(),
                    "queue_wait_ms": self.tick_queue_wait_ms.summary().as_dict(),
                    "processing_ms": self.tick_processing_ms.summary().as_dict(),
                    "tick_gaps": self.tick_gaps,
                    "tick_duplicates": self.tick_duplicates,
                    "tick_out_of_order": self.tick_out_of_order,
                    "tick_drops": self.tick_drops,
                    "slow_ticks": self.slow_ticks,
                },
                "latency": {
                    "end_to_end_ms": self.end_to_end_ms.summary().as_dict(),
                    "stages": {
                        name: stats.summary().as_dict()
                        for name, stats in sorted(self.stage_latencies.items())
                    },
                },
                "api": {
                    "summary": {
                        "success_total": api_summary_success,
                        "failure_total": api_summary_failure,
                        "success_pct": api_success_pct,
                        "failure_pct": api_failure_pct,
                    },
                    "endpoints": {
                        name: state.snapshot(self.config.api_failure_limit_pct)
                        for name, state in sorted(self.api_metrics.items())
                    },
                },
                "signal": {
                    "generated_total": signal_generated,
                    "generated_per_sec": self.signal_rate.rate(),
                    "rejected_total": self.signal_counts.get("rejected", 0),
                    "duplicate_total": self.signal_counts.get("duplicate", 0),
                    "filled_total": signal_filled,
                    "fill_rate_pct": fill_rate,
                },
                "execution": {
                    "orders_attempted": self.order_counts.get("attempted", 0),
                    "orders_filled": self.order_counts.get("filled", 0),
                    "orders_rejected": self.order_counts.get("rejected", 0),
                    "orders_per_sec": self.order_rate.rate(),
                    "rejection_reasons": self.rejection_reasons.top(),
                },
                "strategies": {
                    name: metrics.snapshot()
                    for name, metrics in sorted(self.strategy_metrics.items())
                },
                "system": {
                    "mode": "event_hook",
                    "underperformers": underperformers[:5],
                },
                "resources": dict(self.last_resources),
            }
