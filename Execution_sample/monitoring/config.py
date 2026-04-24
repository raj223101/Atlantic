from __future__ import annotations

from dataclasses import dataclass
import os

import config as runtime_config


@dataclass(frozen=True)
class MonitorConfig:
    enabled: bool = True
    event_hook_mode: bool = True
    log_parser_mode: bool = False
    wrapper_mode: bool = False
    dashboard_interval_s: float = 30.0
    resource_interval_s: float = 5.0
    alert_cooldown_s: float = 60.0
    snapshot_window: int = 5000
    rate_window_s: float = 5.0
    event_queue_size: int = 50000
    latency_limit_ms: float = 250.0
    queue_limit: int = 5000
    api_failure_limit_pct: float = 10.0
    tick_delay_limit_ms: float = 1000.0
    slow_tick_limit_ms: float = 20.0
    no_fill_signal_limit: int = 25
    cpu_warn_pct: float = 85.0
    memory_warn_mb: float = 2048.0
    persist_jsonl: bool = True
    persist_csv: bool = True
    log_dashboard: bool = True
    storage_dir: str = "data/monitoring"
    log_path: str = "logs/engine.log"

    @classmethod
    def from_runtime(cls) -> "MonitorConfig":
        data_dir = getattr(runtime_config, "DATA_DIR", "data")
        log_dir = getattr(runtime_config, "LOG_DIR", "logs")
        storage_dir = getattr(
            runtime_config,
            "MONITORING_DIR",
            os.path.join(data_dir, "monitoring"),
        )
        log_path = getattr(
            runtime_config,
            "MONITORING_LOG_PATH",
            os.path.join(log_dir, "engine.log"),
        )
        return cls(
            enabled=bool(getattr(runtime_config, "MONITORING_ENABLED", True)),
            event_hook_mode=bool(getattr(runtime_config, "MONITORING_EVENT_HOOK_MODE", True)),
            log_parser_mode=bool(getattr(runtime_config, "MONITORING_LOG_PARSER_MODE", False)),
            wrapper_mode=bool(getattr(runtime_config, "MONITORING_WRAPPER_MODE", False)),
            dashboard_interval_s=float(getattr(runtime_config, "MONITORING_DASHBOARD_INTERVAL_S", 30.0)),
            resource_interval_s=float(getattr(runtime_config, "MONITORING_RESOURCE_INTERVAL_S", 5.0)),
            alert_cooldown_s=float(getattr(runtime_config, "MONITORING_ALERT_COOLDOWN_S", 60.0)),
            snapshot_window=int(getattr(runtime_config, "MONITORING_SNAPSHOT_WINDOW", 5000)),
            rate_window_s=float(getattr(runtime_config, "MONITORING_RATE_WINDOW_S", 5.0)),
            event_queue_size=int(getattr(runtime_config, "MONITORING_EVENT_QUEUE_SIZE", 50000)),
            latency_limit_ms=float(getattr(runtime_config, "MONITORING_LATENCY_LIMIT_MS", 250.0)),
            queue_limit=int(getattr(runtime_config, "MONITORING_QUEUE_LIMIT", 5000)),
            api_failure_limit_pct=float(getattr(runtime_config, "MONITORING_API_FAILURE_LIMIT_PCT", 10.0)),
            tick_delay_limit_ms=float(getattr(runtime_config, "MONITORING_TICK_DELAY_LIMIT_MS", 1000.0)),
            slow_tick_limit_ms=float(getattr(runtime_config, "MONITORING_SLOW_TICK_LIMIT_MS", 20.0)),
            no_fill_signal_limit=int(getattr(runtime_config, "MONITORING_NO_FILL_SIGNAL_LIMIT", 25)),
            cpu_warn_pct=float(getattr(runtime_config, "MONITORING_CPU_WARN_PCT", 85.0)),
            memory_warn_mb=float(getattr(runtime_config, "MONITORING_MEMORY_WARN_MB", 2048.0)),
            persist_jsonl=bool(getattr(runtime_config, "MONITORING_PERSIST_JSONL", True)),
            persist_csv=bool(getattr(runtime_config, "MONITORING_PERSIST_CSV", True)),
            log_dashboard=bool(getattr(runtime_config, "MONITORING_LOG_DASHBOARD", True)),
            storage_dir=storage_dir,
            log_path=log_path,
        )
