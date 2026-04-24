from __future__ import annotations

from contextlib import contextmanager
from functools import wraps
import time
from typing import Any, Callable


@contextmanager
def observe_stage(monitor, stage_name: str, **metadata):
    started = time.perf_counter()
    try:
        yield
    finally:
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        if monitor is not None:
            try:
                monitor.on_stage(stage_name, elapsed_ms, **metadata)
            except Exception:
                pass


def monitor_stage(monitor, stage_name: str, **base_metadata) -> Callable:
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any):
            started = time.perf_counter()
            try:
                return func(*args, **kwargs)
            finally:
                elapsed_ms = (time.perf_counter() - started) * 1000.0
                if monitor is not None:
                    try:
                        monitor.on_stage(stage_name, elapsed_ms, **base_metadata)
                    except Exception:
                        pass

        return wrapper

    return decorator
