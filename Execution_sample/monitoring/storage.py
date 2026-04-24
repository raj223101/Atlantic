from __future__ import annotations

import atexit
import csv
import json
import os
import queue
import threading
from typing import Any


SNAPSHOT_HEADERS = [
    "ts",
    "status",
    "tick_rate_per_sec",
    "queue_size",
    "queue_wait_avg_ms",
    "tick_delay_avg_ms",
    "latency_avg_ms",
    "latency_p95_ms",
    "api_success_pct",
    "signal_fill_rate_pct",
    "cpu_pct",
    "memory_mb",
]


class MetricsStorage:
    def __init__(self, storage_dir: str, persist_jsonl: bool = True, persist_csv: bool = True) -> None:
        self.storage_dir = storage_dir
        self.persist_jsonl = persist_jsonl
        self.persist_csv = persist_csv
        self._q: queue.Queue[tuple[str, dict[str, Any]] | None] = queue.Queue(maxsize=10000)
        self._thread: threading.Thread | None = None
        self._running = False
        self._csv_handle = None
        self._csv_writer = None
        self._alerts_handle = None
        self._snapshots_handle = None

    def start(self) -> None:
        if self._running:
            return
        os.makedirs(self.storage_dir, exist_ok=True)
        self._running = True
        self._thread = threading.Thread(target=self._worker, name="MetricsStorage", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        try:
            self._q.put_nowait(None)
        except queue.Full:
            pass
        if self._thread is not None:
            self._thread.join(timeout=5.0)
        self._close_handles()

    def enqueue_snapshot(self, snapshot: dict) -> None:
        if not self._running:
            return
        self._enqueue(("snapshot", snapshot))

    def enqueue_alert(self, alert: dict) -> None:
        if not self._running:
            return
        self._enqueue(("alert", alert))

    def _enqueue(self, item: tuple[str, dict[str, Any]]) -> None:
        try:
            self._q.put_nowait(item)
        except queue.Full:
            return

    def _worker(self) -> None:
        while True:
            item = self._q.get()
            if item is None:
                break
            kind, payload = item
            if kind == "snapshot":
                self._write_snapshot(payload)
            elif kind == "alert":
                self._write_alert(payload)
        self._close_handles()

    def _write_snapshot(self, snapshot: dict) -> None:
        if self.persist_jsonl:
            handle = self._ensure_snapshots_handle()
            handle.write(json.dumps(snapshot, ensure_ascii=True) + "\n")
            handle.flush()
        if self.persist_csv:
            writer = self._ensure_csv_writer()
            writer.writerow(
                [
                    snapshot.get("ts", ""),
                    snapshot.get("status", ""),
                    snapshot.get("tick_health", {}).get("tick_rate_per_sec", 0.0),
                    snapshot.get("tick_health", {}).get("queue_size", {}).get("latest", 0.0),
                    snapshot.get("tick_health", {}).get("queue_wait_ms", {}).get("avg", 0.0),
                    snapshot.get("tick_health", {}).get("delay_ms", {}).get("avg", 0.0),
                    snapshot.get("latency", {}).get("end_to_end_ms", {}).get("avg", 0.0),
                    snapshot.get("latency", {}).get("end_to_end_ms", {}).get("p95", 0.0),
                    snapshot.get("api", {}).get("summary", {}).get("success_pct", 0.0),
                    snapshot.get("signal", {}).get("fill_rate_pct", 0.0),
                    snapshot.get("resources", {}).get("cpu_pct", 0.0),
                    snapshot.get("resources", {}).get("memory_mb", 0.0),
                ]
            )
            self._csv_handle.flush()

    def _write_alert(self, alert: dict) -> None:
        if not self.persist_jsonl:
            return
        handle = self._ensure_alerts_handle()
        handle.write(json.dumps(alert, ensure_ascii=True) + "\n")
        handle.flush()

    def _ensure_csv_writer(self):
        if self._csv_writer is not None:
            return self._csv_writer
        path = os.path.join(self.storage_dir, "dashboard_metrics.csv")
        exists = os.path.exists(path)
        self._csv_handle = open(path, "a", newline="", encoding="utf-8")
        self._csv_writer = csv.writer(self._csv_handle)
        if not exists:
            self._csv_writer.writerow(SNAPSHOT_HEADERS)
            self._csv_handle.flush()
        return self._csv_writer

    def _ensure_snapshots_handle(self):
        if self._snapshots_handle is None:
            path = os.path.join(self.storage_dir, "snapshots.jsonl")
            self._snapshots_handle = open(path, "a", encoding="utf-8")
        return self._snapshots_handle

    def _ensure_alerts_handle(self):
        if self._alerts_handle is None:
            path = os.path.join(self.storage_dir, "alerts.jsonl")
            self._alerts_handle = open(path, "a", encoding="utf-8")
        return self._alerts_handle

    def _close_handles(self) -> None:
        for handle in (self._csv_handle, self._alerts_handle, self._snapshots_handle):
            try:
                if handle is not None:
                    handle.flush()
                    handle.close()
            except Exception:
                pass
        self._csv_handle = None
        self._csv_writer = None
        self._alerts_handle = None
        self._snapshots_handle = None


_storage_ref: MetricsStorage | None = None


def register_storage_for_shutdown(storage: MetricsStorage) -> None:
    global _storage_ref
    _storage_ref = storage


@atexit.register
def _close_registered_storage() -> None:
    if _storage_ref is not None:
        _storage_ref.stop()
