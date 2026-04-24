from __future__ import annotations

from dataclasses import dataclass

import config as runtime_config


@dataclass(frozen=True)
class LowLatencyConfig:
    candle_worker_count: int = 4
    tick_queue_limit: int = 1000
    queue_put_timeout_ms: float = 2.0
    strategy_queue_limit: int = 1000
    execution_queue_limit: int = 500
    dispatch_price_threshold: float = 0.05
    stale_signal_ms: float = 0.0
    hard_latency_limit_ms: float = 500.0
    signal_price_drift_limit: float = 5.0
    queue_warning_ratio: float = 0.75
    load_shed_cooldown_s: float = 5.0
    idle_drain_timeout_s: float = 10.0

    @classmethod
    def from_runtime(cls) -> "LowLatencyConfig":
        return cls(
            candle_worker_count=max(int(getattr(runtime_config, "LOW_LATENCY_CANDLE_WORKERS", 1)), 1),
            tick_queue_limit=max(int(getattr(runtime_config, "LOW_LATENCY_TICK_QUEUE_LIMIT", 1000)), 1),
            queue_put_timeout_ms=max(float(getattr(runtime_config, "LOW_LATENCY_QUEUE_PUT_TIMEOUT_MS", 2.0)), 0.0),
            strategy_queue_limit=max(int(getattr(runtime_config, "LOW_LATENCY_STRATEGY_QUEUE_LIMIT", 1000)), 1),
            execution_queue_limit=max(int(getattr(runtime_config, "LOW_LATENCY_EXECUTION_QUEUE_LIMIT", 500)), 1),
            dispatch_price_threshold=float(getattr(runtime_config, "LOW_LATENCY_DISPATCH_PRICE_THRESHOLD", 0.05)),
            stale_signal_ms=float(getattr(runtime_config, "LOW_LATENCY_SIGNAL_MAX_AGE_MS", 0.0)),
            hard_latency_limit_ms=float(getattr(runtime_config, "LOW_LATENCY_HARD_LATENCY_LIMIT_MS", 500.0)),
            signal_price_drift_limit=float(getattr(runtime_config, "LOW_LATENCY_SIGNAL_PRICE_DRIFT_LIMIT", 5.0)),
            queue_warning_ratio=float(getattr(runtime_config, "LOW_LATENCY_QUEUE_WARNING_RATIO", 0.75)),
            load_shed_cooldown_s=float(getattr(runtime_config, "LOW_LATENCY_LOAD_SHED_COOLDOWN_S", 5.0)),
            idle_drain_timeout_s=float(getattr(runtime_config, "LOW_LATENCY_IDLE_DRAIN_TIMEOUT_S", 10.0)),
        )
