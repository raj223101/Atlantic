from __future__ import annotations

from datetime import datetime
import queue
import threading
import time
from typing import Any, Optional

from core.logger import log
from monitoring.alerts import AlertEngine
from monitoring.analyzer import MetricsAnalyzer
from monitoring.collector import MetricsCollector
from monitoring.config import MonitorConfig
from monitoring.dashboard import render_dashboard
from monitoring.log_parser import LogParserMonitor
from monitoring.storage import MetricsStorage, register_storage_for_shutdown


class PerformanceMonitor:
    def __init__(self, config: Optional[MonitorConfig] = None) -> None:
        self.config = config or MonitorConfig.from_runtime()
        self.collector = MetricsCollector(self.config)
        self.analyzer = MetricsAnalyzer(self.config)
        self.alert_engine = AlertEngine(self.config.alert_cooldown_s)
        self.storage = MetricsStorage(
            self.config.storage_dir,
            persist_jsonl=self.config.persist_jsonl,
            persist_csv=self.config.persist_csv,
        )
        self.log_parser = (
            LogParserMonitor(self, self.config.log_path)
            if self.config.log_parser_mode
            else None
        )

        self._event_queue: queue.Queue[tuple[str, dict[str, Any]] | None] = queue.Queue(
            maxsize=max(self.config.event_queue_size, 1000)
        )
        self._worker_thread: threading.Thread | None = None
        self._report_thread: threading.Thread | None = None
        self._running = False
        self._lock = threading.RLock()
        self._dropped_events = 0
        self._last_dashboard = ""

    def start(self) -> None:
        if not self.config.enabled:
            return
        with self._lock:
            if self._running:
                return
            self._running = True
            self.storage.start()
            register_storage_for_shutdown(self.storage)
            self._worker_thread = threading.Thread(target=self._worker_loop, name="MonitorWorker", daemon=True)
            self._report_thread = threading.Thread(target=self._report_loop, name="MonitorReporter", daemon=True)
            self._worker_thread.start()
            self._report_thread.start()
            if self.log_parser is not None:
                self.log_parser.start()
        log.info(
            "[Monitor] started | mode=%s%s%s storage=%s",
            "event-hook" if self.config.event_hook_mode else "",
            "+log-parser" if self.config.log_parser_mode else "",
            "+wrappers" if self.config.wrapper_mode else "",
            self.config.storage_dir,
        )

    def stop(self) -> None:
        with self._lock:
            if not self._running:
                return
            self._running = False
            try:
                self._event_queue.put_nowait(None)
            except queue.Full:
                pass
            worker = self._worker_thread
            reporter = self._report_thread
        if self.log_parser is not None:
            self.log_parser.stop()
        if worker is not None:
            worker.join(timeout=5.0)
        if reporter is not None:
            reporter.join(timeout=5.0)
        self.storage.stop()
        log.info("[Monitor] stopped | dropped_events=%d", self._dropped_events)

    def on_tick_received(
        self,
        *,
        symbol: str,
        tick_ts: datetime,
        recv_epoch: float,
        queue_size: int,
        sequence_number: Optional[int] = None,
    ) -> None:
        self._submit(
            "tick_received",
            {
                "symbol": symbol,
                "tick_ts": tick_ts,
                "recv_epoch": recv_epoch,
                "queue_size": queue_size,
                "sequence_number": sequence_number,
            },
        )

    def on_tick_processed(
        self,
        *,
        symbol: str,
        queue_size: int,
        queue_wait_ms: float,
        processing_ms: float,
        end_to_end_ms: float,
        dropped: bool = False,
    ) -> None:
        self._submit(
            "tick_processed",
            {
                "symbol": symbol,
                "queue_size": queue_size,
                "queue_wait_ms": queue_wait_ms,
                "processing_ms": processing_ms,
                "end_to_end_ms": end_to_end_ms,
                "dropped": dropped,
            },
        )

    def on_tick_queue_stats(self, *, queue_size: int, dropped: int) -> None:
        self._submit(
            "tick_queue_stats",
            {
                "queue_size": queue_size,
                "dropped": dropped,
            },
        )

    def on_stage(
        self,
        stage_name: str,
        elapsed_ms: float,
        *,
        strategy_name: Optional[str] = None,
    ) -> None:
        self._submit(
            "stage",
            {
                "stage_name": stage_name,
                "elapsed_ms": elapsed_ms,
                "strategy_name": strategy_name,
            },
        )

    def on_api_call(
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
        self._submit(
            "api_call",
            {
                "service": service,
                "operation": operation,
                "success": success,
                "elapsed_ms": elapsed_ms,
                "retries": retries,
                "timeout": timeout,
                "error": error,
            },
        )

    def on_signal(
        self,
        *,
        strategy_name: str,
        symbol: str,
        signal_name: str,
        status: str,
        ts: Optional[datetime] = None,
    ) -> None:
        self._submit(
            "signal",
            {
                "strategy_name": strategy_name,
                "symbol": symbol,
                "signal_name": signal_name,
                "status": status,
                "ts": ts or datetime.now(),
            },
        )

    def on_order(
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
        self._submit(
            "order",
            {
                "strategy_name": strategy_name,
                "symbol": symbol,
                "order_side": order_side,
                "order_kind": order_kind,
                "status": status,
                "latency_ms": latency_ms,
                "fill_latency_ms": fill_latency_ms,
                "slippage": slippage,
                "reason": reason,
            },
        )

    def on_trade_closed(
        self,
        *,
        strategy_name: str,
        pnl: float,
        win: bool,
    ) -> None:
        self._submit(
            "trade_closed",
            {
                "strategy_name": strategy_name,
                "pnl": pnl,
                "win": win,
            },
        )

    def on_heartbeat(self, component: str, payload: Optional[dict] = None) -> None:
        self._submit(
            "heartbeat",
            {
                "component": component,
                "payload": payload or {},
            },
        )

    def get_tick_latency_stats(self) -> dict:
        return self.collector.snapshot().get("latency", {}).get("end_to_end_ms", {})

    def get_component_stats(self) -> dict:
        return self.collector.snapshot().get("latency", {}).get("stages", {})

    def get_strategy_stats(self) -> dict:
        return self.collector.snapshot().get("strategies", {})

    def get_cache_stats(self) -> dict:
        from calculation.calc_cache import calculation_cache

        return calculation_cache.get_stats()

    def log_summary(self) -> None:
        snapshot = self.collector.snapshot()
        analysis = self.analyzer.analyze(snapshot).as_dict()
        snapshot["status"] = analysis["status"]
        dashboard = render_dashboard(snapshot, analysis)
        log.info("\n%s", dashboard)

    def summary(self) -> dict:
        snapshot = self.collector.snapshot()
        analysis = self.analyzer.analyze(snapshot).as_dict()
        snapshot["status"] = analysis["status"]
        snapshot["analysis"] = analysis
        snapshot["cache"] = self.get_cache_stats()
        snapshot["dropped_events"] = self._dropped_events
        return snapshot

    def _submit(self, event_type: str, payload: dict[str, Any]) -> None:
        if not self.config.enabled:
            return
        if not self._running:
            self.start()
        try:
            self._event_queue.put_nowait((event_type, payload))
        except queue.Full:
            self._dropped_events += 1

    def _worker_loop(self) -> None:
        while self._running:
            try:
                item = self._event_queue.get(timeout=1.0)
            except queue.Empty:
                continue
            if item is None:
                break
            event_type, payload = item
            try:
                self._handle_event(event_type, payload)
            except Exception as exc:
                log.error("[Monitor] event handling failed | type=%s error=%s", event_type, exc, exc_info=True)

    def _handle_event(self, event_type: str, payload: dict[str, Any]) -> None:
        if event_type == "tick_received":
            self.collector.record_tick_received(**payload)
            return
        if event_type == "tick_processed":
            self.collector.record_tick_processed(**payload)
            return
        if event_type == "tick_queue_stats":
            self.collector.tick_queue_size.add(payload.get("queue_size", 0))
            for _ in range(max(int(payload.get("dropped", 0)), 0)):
                self.collector.tick_drops += 1
            return
        if event_type == "stage":
            self.collector.record_stage_latency(
                payload["stage_name"],
                payload["elapsed_ms"],
                strategy_name=payload.get("strategy_name"),
            )
            return
        if event_type == "api_call":
            self.collector.record_api_call(**payload)
            return
        if event_type == "signal":
            self.collector.record_signal(**payload)
            return
        if event_type == "order":
            self.collector.record_order(**payload)
            return
        if event_type == "trade_closed":
            self.collector.record_trade_close(**payload)
            return
        if event_type == "heartbeat":
            return

    def _report_loop(self) -> None:
        next_resource = 0.0
        while self._running:
            now = time.time()
            if now >= next_resource:
                self.collector.update_resources()
                next_resource = now + self.config.resource_interval_s

            snapshot = self.collector.snapshot()
            analysis = self.analyzer.analyze(snapshot).as_dict()
            snapshot["status"] = analysis["status"]
            dashboard = render_dashboard(snapshot, analysis)
            self._last_dashboard = dashboard

            if self.config.log_dashboard:
                log.info("\n%s", dashboard)

            emitted = self.alert_engine.emit(analysis.get("alerts", []))
            self.storage.enqueue_snapshot(snapshot)
            for alert in emitted:
                self.storage.enqueue_alert(alert.as_dict())

            sleep_for = max(self.config.dashboard_interval_s, 1.0)
            for _ in range(int(sleep_for * 10)):
                if not self._running:
                    return
                time.sleep(0.1)


_monitor_singleton: PerformanceMonitor | None = None


def get_monitor() -> PerformanceMonitor:
    global _monitor_singleton
    if _monitor_singleton is None:
        _monitor_singleton = PerformanceMonitor()
    return _monitor_singleton


performance_monitor = get_monitor()
