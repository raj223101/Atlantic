"""Incremental math primitives shared by the calculation layer."""

import math
from collections import deque
from typing import Optional


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def is_na(x) -> bool:
    """Return True if x is None, NaN, or inf."""
    return x is None or (isinstance(x, float) and (math.isnan(x) or math.isinf(x)))


def nz(x: Optional[float], replacement: float = 0.0) -> float:
    """Pine nz(): return x if valid, else replacement."""
    return replacement if is_na(x) else float(x)


def true_range(high: float, low: float, prev_close: Optional[float]) -> float:
    """Pine ta.tr for a single bar."""
    if prev_close is None:
        return high - low
    return max(high - low, abs(high - prev_close), abs(low - prev_close))


# ─────────────────────────────────────────────────────────────────────────────
# RMA – Wilder Moving Average (alpha = 1/length)
# ─────────────────────────────────────────────────────────────────────────────

class RMA:
    """
    Exact Pine ta.rma: seeded with SMA of first `length` values, then recursive.

    is_close=True  → commits value to state (use on bar close)
    is_close=False → returns projected value without mutating state (use on live tick)
    """

    def __init__(self, length: int):
        self.length = length
        self.alpha = 1.0 / length
        self.buffer = deque(maxlen=length)
        self.value: Optional[float] = None

    def update(self, x: float, is_close: bool = True) -> Optional[float]:
        x = float(x)

        # Still filling seed buffer
        if self.value is None:
            if len(self.buffer) < self.length - 1:
                if is_close:
                    self.buffer.append(x)
                return None

            # Seed bar: SMA of first `length` values
            window = list(self.buffer) + [x]
            seed = sum(window) / self.length
            if is_close:
                self.buffer.append(x)
                self.value = seed
            return seed

        # Recursive update
        result = self.alpha * x + (1 - self.alpha) * self.value
        if is_close:
            self.value = result
        return result

    def reset(self):
        self.buffer.clear()
        self.value = None


# ─────────────────────────────────────────────────────────────────────────────
# EMA – Exponential Moving Average (alpha = 2/(length+1))
# ────────────────────���────────────────────────────────────────────────────────

class EMA:
    """Exact Pine ta.ema: seeded with first value."""

    def __init__(self, length: int):
        self.length = length
        self.alpha = 2.0 / (length + 1)
        self.value: Optional[float] = None

    def update(self, x: float, is_close: bool = True) -> float:
        x = float(x)
        if self.value is None:
            if is_close:
                self.value = x
            return x

        result = self.alpha * x + (1 - self.alpha) * self.value
        if is_close:
            self.value = result
        return result

    def reset(self):
        self.value = None


# ─────────────────────────────────────────────────────────────────────────────
# SMA – Simple Moving Average
# ─────────────────────────────────────────────────────────────────────────────

class SMA:
    """Exact Pine ta.sma: returns None until full window."""

    def __init__(self, length: int):
        self.length = length
        self.buf = deque(maxlen=length)

    def update(self, x: float, is_close: bool = True) -> Optional[float]:
        x = float(x)

        if is_close:
            self.buf.append(x)
            if len(self.buf) < self.length:
                return None
            return sum(self.buf) / self.length

        # Peek: compute with current value appended without mutating
        window = list(self.buf)[-(self.length - 1):] + [x] if self.length > 1 else [x]
        if len(window) < self.length:
            return None
        return sum(window) / self.length

    def reset(self):
        self.buf.clear()


# ─────────────────────────────────────────────────────────────────────────────
# ATR – Average True Range (wraps RMA + prev_close tracking)
# ─────────────────────────────────────────────────────────────────────────────

class ATR:
    """Pine ta.atr: RMA of true range."""

    def __init__(self, length: int):
        self.rma = RMA(length)
        self.prev_close: Optional[float] = None

    def update(self, h: float, l: float, c: float, is_close: bool = True) -> Optional[float]:
        tr = true_range(h, l, self.prev_close)
        result = self.rma.update(tr, is_close)
        if is_close:
            self.prev_close = c
        return result

    def reset(self):
        self.rma.reset()
        self.prev_close = None


# ─────────────────────────────────────────────────────────────────────────────
# LinRegSlope – Standard linear regression slope over a window
# ─────────────────────────────────────────────────────────────────────────────

class LinRegSlope:
    """
    Standard linear regression slope over the last `length` values.
    Returns the slope coefficient (not Pine's linreg endpoint difference).
    """

    def __init__(self, length: int):
        self.length = length
        self.buf = deque(maxlen=length)

        # Pre-compute x terms (they never change)
        xs = list(range(length))
        self.x_mean = sum(xs) / length
        self.x_devs = [xi - self.x_mean for xi in xs]
        self.x_var = sum(d * d for d in self.x_devs)

    def update(self, x: float, is_close: bool = True) -> Optional[float]:
        x = float(x)

        if is_close:
            self.buf.append(x)
            if len(self.buf) < self.length:
                return None
            ys = list(self.buf)
        else:
            # Peek: compute with current value appended without mutating
            ys = list(self.buf)[-(self.length - 1):] + [x] if self.length > 1 else [x]
            if len(ys) < self.length:
                return None

        y_mean = sum(ys) / self.length
        num = sum((ys[i] - y_mean) * self.x_devs[i] for i in range(self.length))
        return num / self.x_var if self.x_var != 0 else 0.0

    def reset(self):
        self.buf.clear()


# ─────────────────────────────────────────────────────────────────────────────
# BBSlope – Bar-to-bar slope with optional SMA smoothing
# ─────────────────────────────────────────────────────────────────────────────

class BBSlope:
    """
    Bar-to-bar change (ta.change), optionally smoothed by SMA.
    Matches Pine: ta.sma(ta.change(src), smooth).
    """

    def __init__(self, smooth: int = 0):
        self.prev: Optional[float] = None
        self.sma = SMA(smooth) if smooth > 0 else None

    def update(self, x: float, is_close: bool = True) -> float:
        if self.prev is None:
            if is_close:
                self.prev = x
            return 0.0

        slope = x - self.prev
        if is_close:
            self.prev = x

        if self.sma:
            result = self.sma.update(slope, is_close)
            return nz(result, 0.0)

        return slope

    def reset(self):
        self.prev = None
        if self.sma:
            self.sma.reset()
