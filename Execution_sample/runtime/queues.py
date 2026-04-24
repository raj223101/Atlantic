from __future__ import annotations

import threading
import time
from collections import deque
from typing import Deque, Generic, TypeVar


T = TypeVar("T")


class QueueClosed(Exception):
    pass


class DropOldestQueue(Generic[T]):
    def __init__(self, *, maxsize: int, name: str) -> None:
        self.maxsize = max(int(maxsize), 1)
        self.name = name
        self._items: Deque[T] = deque()
        self._cv = threading.Condition()
        self._closed = False
        self._dropped = 0
        self._high_watermark = 0

    def put(self, item: T) -> int:
        dropped = 0
        with self._cv:
            if self._closed:
                raise QueueClosed(self.name)
            while len(self._items) >= self.maxsize:
                self._items.popleft()
                self._dropped += 1
                dropped += 1
            self._items.append(item)
            self._high_watermark = max(self._high_watermark, len(self._items))
            self._cv.notify()
        return dropped

    def get(self, timeout: float | None = None) -> T:
        with self._cv:
            deadline = None if timeout is None else time.monotonic() + timeout
            while not self._items:
                if self._closed:
                    raise QueueClosed(self.name)
                if deadline is None:
                    self._cv.wait()
                    continue
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(self.name)
                self._cv.wait(remaining)
            return self._items.popleft()

    def close(self) -> None:
        with self._cv:
            self._closed = True
            self._cv.notify_all()

    def qsize(self) -> int:
        with self._cv:
            return len(self._items)

    def dropped(self) -> int:
        with self._cv:
            return self._dropped

    def high_watermark(self) -> int:
        with self._cv:
            return self._high_watermark

    def empty(self) -> bool:
        return self.qsize() == 0


class BoundedQueue(Generic[T]):
    def __init__(self, *, maxsize: int, name: str) -> None:
        self.maxsize = max(int(maxsize), 1)
        self.name = name
        self._items: Deque[T] = deque()
        self._cv = threading.Condition()
        self._closed = False
        self._high_watermark = 0

    def put(self, item: T, timeout: float | None = None) -> bool:
        with self._cv:
            if self._closed:
                raise QueueClosed(self.name)

            deadline = None if timeout is None else time.monotonic() + max(float(timeout), 0.0)
            while len(self._items) >= self.maxsize:
                if self._closed:
                    raise QueueClosed(self.name)
                if deadline is None:
                    self._cv.wait()
                    continue
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._cv.wait(remaining)

            self._items.append(item)
            self._high_watermark = max(self._high_watermark, len(self._items))
            self._cv.notify_all()
            return True

    def get(self, timeout: float | None = None) -> T:
        with self._cv:
            deadline = None if timeout is None else time.monotonic() + timeout
            while not self._items:
                if self._closed:
                    raise QueueClosed(self.name)
                if deadline is None:
                    self._cv.wait()
                    continue
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(self.name)
                self._cv.wait(remaining)
            item = self._items.popleft()
            self._cv.notify_all()
            return item

    def close(self) -> None:
        with self._cv:
            self._closed = True
            self._cv.notify_all()

    def qsize(self) -> int:
        with self._cv:
            return len(self._items)

    def high_watermark(self) -> int:
        with self._cv:
            return self._high_watermark

    def empty(self) -> bool:
        return self.qsize() == 0
