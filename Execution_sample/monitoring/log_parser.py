from __future__ import annotations

from pathlib import Path
import re
import threading
import time


SLOW_TICK_RE = re.compile(r"\[TickQueue\] slow tick \| ms=(?P<ms>[0-9.]+) symbol=(?P<symbol>\S+) queue=(?P<queue>\d+)")
QUEUE_STATS_RE = re.compile(r"\[TickQueue\] processed=(?P<processed>\d+) queued=(?P<queued>\d+) dropped=(?P<dropped>\d+)")
SIGNAL_RE = re.compile(r"\[SignalRouter\] signal \| strategy=(?P<strategy>\S+) symbol=(?P<symbol>\S+) signal=(?P<signal>\S+)")
SIGNAL_REJECT_RE = re.compile(r"\[SignalRouter\] signal not filled \| strategy=(?P<strategy>\S+) symbol=(?P<symbol>\S+) signal=(?P<signal>\S+)")
BROKER_OPEN_RE = re.compile(r"\[PaperBroker\] OPEN \| strategy=(?P<strategy>\S+) symbol=(?P<symbol>\S+) dir=(?P<side>\S+)")
BROKER_CLOSE_RE = re.compile(r"\[PaperBroker\] CLOSE \| strategy=(?P<strategy>\S+) symbol=(?P<symbol>\S+) dir=(?P<side>\S+)")


class LogParserMonitor:
    def __init__(self, monitor, log_path: str) -> None:
        self.monitor = monitor
        self.log_path = Path(log_path)
        self._running = False
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._tail_loop, name="MonitorLogParser", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=5.0)

    def _tail_loop(self) -> None:
        while self._running and not self.log_path.exists():
            time.sleep(1.0)
        if not self._running:
            return

        with self.log_path.open("r", encoding="utf-8", errors="ignore") as handle:
            handle.seek(0, 2)
            while self._running:
                line = handle.readline()
                if not line:
                    time.sleep(0.5)
                    continue
                self._parse_line(line.rstrip())

    def _parse_line(self, line: str) -> None:
        match = SLOW_TICK_RE.search(line)
        if match:
            self.monitor.on_stage(
                "tick_processing.log_parse",
                float(match.group("ms")),
            )
            return

        match = QUEUE_STATS_RE.search(line)
        if match:
            self.monitor.on_tick_queue_stats(
                queue_size=int(match.group("queued")),
                dropped=int(match.group("dropped")),
            )
            return

        match = SIGNAL_RE.search(line)
        if match:
            self.monitor.on_signal(
                strategy_name=match.group("strategy"),
                symbol=match.group("symbol"),
                signal_name=match.group("signal"),
                status="generated",
            )
            return

        match = SIGNAL_REJECT_RE.search(line)
        if match:
            self.monitor.on_signal(
                strategy_name=match.group("strategy"),
                symbol=match.group("symbol"),
                signal_name=match.group("signal"),
                status="rejected",
            )
            return

        match = BROKER_OPEN_RE.search(line)
        if match:
            self.monitor.on_order(
                strategy_name=match.group("strategy"),
                symbol=match.group("symbol"),
                order_side=match.group("side"),
                order_kind="ENTRY",
                status="filled",
            )
            return

        match = BROKER_CLOSE_RE.search(line)
        if match:
            self.monitor.on_order(
                strategy_name=match.group("strategy"),
                symbol=match.group("symbol"),
                order_side=match.group("side"),
                order_kind="EXIT",
                status="filled",
            )
