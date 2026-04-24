from __future__ import annotations

from collections import Counter, deque
from dataclasses import dataclass
import math
import time
from typing import Deque, Iterable


def _clean_float(value: float | int | None) -> float:
    try:
        numeric = float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0
    if math.isnan(numeric) or math.isinf(numeric):
        return 0.0
    return numeric


@dataclass
class RollingStatsSummary:
    count: int
    avg: float
    p95: float
    p99: float
    max: float
    min: float
    latest: float

    def as_dict(self) -> dict:
        return {
            "count": self.count,
            "avg": self.avg,
            "p95": self.p95,
            "p99": self.p99,
            "max": self.max,
            "min": self.min,
            "latest": self.latest,
        }


class RollingStats:
    def __init__(self, maxlen: int = 5000) -> None:
        self._values: Deque[float] = deque(maxlen=maxlen)

    def add(self, value: float | int | None) -> None:
        self._values.append(_clean_float(value))

    def extend(self, values: Iterable[float | int]) -> None:
        for value in values:
            self.add(value)

    def summary(self) -> RollingStatsSummary:
        if not self._values:
            return RollingStatsSummary(0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)

        samples = sorted(self._values)
        count = len(samples)
        return RollingStatsSummary(
            count=count,
            avg=sum(samples) / count,
            p95=samples[min(int(count * 0.95), count - 1)],
            p99=samples[min(int(count * 0.99), count - 1)],
            max=samples[-1],
            min=samples[0],
            latest=self._values[-1],
        )

    def latest(self) -> float:
        return self._values[-1] if self._values else 0.0


class RateTracker:
    def __init__(self, window_s: float = 5.0) -> None:
        self.window_s = max(float(window_s), 1.0)
        self._times: Deque[float] = deque()

    def mark(self, ts: float | None = None, count: int = 1) -> None:
        now = ts or time.time()
        for _ in range(max(int(count), 1)):
            self._times.append(now)
        self._trim(now)

    def rate(self, now: float | None = None) -> float:
        current = now or time.time()
        self._trim(current)
        if not self._times:
            return 0.0
        window = max(current - self._times[0], 1e-6)
        window = max(window, min(self.window_s, 1.0))
        return len(self._times) / window

    def _trim(self, now: float) -> None:
        cutoff = now - self.window_s
        while self._times and self._times[0] < cutoff:
            self._times.popleft()


class RatioTracker:
    def __init__(self) -> None:
        self.success = 0
        self.failure = 0

    def record(self, success: bool) -> None:
        if success:
            self.success += 1
        else:
            self.failure += 1

    @property
    def total(self) -> int:
        return self.success + self.failure

    @property
    def success_pct(self) -> float:
        if self.total <= 0:
            return 0.0
        return (self.success / self.total) * 100.0

    @property
    def failure_pct(self) -> float:
        if self.total <= 0:
            return 0.0
        return (self.failure / self.total) * 100.0


class ReasonCounter:
    def __init__(self) -> None:
        self._counter: Counter[str] = Counter()

    def add(self, reason: str | None) -> None:
        text = str(reason or "UNKNOWN").strip() or "UNKNOWN"
        self._counter[text] += 1

    def top(self, limit: int = 5) -> list[dict]:
        return [
            {"reason": reason, "count": count}
            for reason, count in self._counter.most_common(limit)
        ]

    def as_dict(self) -> dict[str, int]:
        return dict(self._counter)
