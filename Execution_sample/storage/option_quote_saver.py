"""
Asynchronous option L1 quote persistence.
"""

from __future__ import annotations

import atexit
import csv
import math
import os
import queue
import threading
from datetime import datetime
from typing import TYPE_CHECKING, Dict

from core.logger import log
from storage.day_paths import option_quotes_dir

if TYPE_CHECKING:
    from execution.angel_option_service import OptionContract, OptionQuote


HEADERS = [
    "Time",
    "Underlying_Symbol",
    "Watch_Label",
    "Option_Symbol",
    "Token",
    "Exchange",
    "Exchange_Type",
    "Option_Type",
    "Strike",
    "Expiry",
    "Lot_Size",
    "Tick_Size",
    "LTP",
    "Bid",
    "Ask",
    "Bid_Qty",
    "Ask_Qty",
    "Spread",
    "Microprice",
    "Quote_Source",
]

FLUSH_EVERY = 200


def _num(value) -> float:
    if value is None:
        return 0.0
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return 0.0
    if math.isnan(numeric) or math.isinf(numeric):
        return 0.0
    return round(numeric, 6)


def _int(value) -> int:
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return 0


def _ensure_schema(path: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    if not os.path.isfile(path):
        with open(path, "w", newline="", encoding="utf-8") as handle:
            csv.writer(handle).writerow(HEADERS)
        return

    try:
        with open(path, newline="", encoding="utf-8") as handle:
            reader = csv.reader(handle)
            existing = next(reader, [])
    except Exception:
        existing = []

    if existing == HEADERS:
        return

    backup = f"{path}.legacy_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    os.replace(path, backup)
    with open(path, "w", newline="", encoding="utf-8") as handle:
        csv.writer(handle).writerow(HEADERS)


class OptionQuoteSaver:
    def __init__(self) -> None:
        self._q: queue.Queue[dict | None] = queue.Queue(maxsize=0)
        self._thread: threading.Thread | None = None
        self._started = False
        self._closed = False
        self._state_lock = threading.Lock()
        self._handles: Dict[str, object] = {}
        self._writers: Dict[str, csv.writer] = {}
        self._flush_counts: Dict[str, int] = {}

    def start(self) -> None:
        with self._state_lock:
            if self._started or self._closed:
                return
            self._started = True
            self._thread = threading.Thread(
                target=self._worker,
                name="OptionQuoteSaver",
                daemon=True,
            )
            self._thread.start()
            log.info("[OptionQuoteSaver] worker started")

    def write(self, contract: "OptionContract", quote: "OptionQuote", watch_label: str) -> None:
        if self._closed:
            return

        self.start()
        day_key = quote.ts.strftime("%Y-%m-%d")
        item = {
            "time": quote.ts.strftime("%Y-%m-%d %H:%M:%S.%f"),
            "day_key": day_key,
            "underlying_symbol": str(contract.underlying_symbol),
            "watch_label": str(watch_label or "UNSPECIFIED"),
            "option_symbol": str(contract.symbol),
            "token": str(contract.token),
            "exchange": str(contract.exchange),
            "exchange_type": _int(contract.exchange_type),
            "option_type": str(contract.option_type),
            "strike": _num(contract.strike),
            "expiry": str(contract.expiry),
            "lot_size": _int(contract.lot_size),
            "tick_size": _num(contract.tick_size),
            "ltp": _num(quote.ltp),
            "bid": _num(quote.bid),
            "ask": _num(quote.ask),
            "bid_qty": _int(quote.bid_size),
            "ask_qty": _int(quote.ask_size),
            "spread": _num(quote.spread),
            "microprice": _num(quote.microprice()),
            "quote_source": str(quote.source),
        }
        self._q.put_nowait(item)

    def close(self) -> None:
        with self._state_lock:
            if self._closed:
                return
            self._closed = True
            if self._started:
                self._q.put_nowait(None)
            thread = self._thread

        if thread is not None and thread.is_alive() and threading.current_thread() is not thread:
            thread.join(timeout=5.0)

        self._close_all()

    def _worker(self) -> None:
        while True:
            item = self._q.get()
            if item is None:
                break
            try:
                self._write_item(item)
            except Exception as exc:
                log.error(
                    "[OptionQuoteSaver] write failed | symbol=%s error=%s",
                    item.get("option_symbol"),
                    exc,
                    exc_info=True,
                )
        self._close_all()

    def _write_item(self, item: dict) -> None:
        underlying_symbol = item["underlying_symbol"] or "UNKNOWN"
        watch_label = item["watch_label"] or "UNSPECIFIED"
        writer_key = f"{item.get('day_key', '')}:{underlying_symbol}:{watch_label}"
        writer = self._ensure_writer(writer_key, underlying_symbol, watch_label, item.get("time"))
        writer.writerow(
            [
                item["time"],
                item["underlying_symbol"],
                item["watch_label"],
                item["option_symbol"],
                item["token"],
                item["exchange"],
                item["exchange_type"],
                item["option_type"],
                item["strike"],
                item["expiry"],
                item["lot_size"],
                item["tick_size"],
                item["ltp"],
                item["bid"],
                item["ask"],
                item["bid_qty"],
                item["ask_qty"],
                item["spread"],
                item["microprice"],
                item["quote_source"],
            ]
        )

        self._flush_counts[writer_key] = self._flush_counts.get(writer_key, 0) + 1
        if self._flush_counts[writer_key] >= FLUSH_EVERY:
            handle = self._handles.get(writer_key)
            if handle is not None:
                handle.flush()
            self._flush_counts[writer_key] = 0

    def _ensure_writer(self, writer_key: str, underlying_symbol: str, watch_label: str, ts_value) -> csv.writer:
        writer = self._writers.get(writer_key)
        if writer is not None:
            return writer

        safe_label = str(watch_label).replace(" ", "_")
        path = os.path.join(
            option_quotes_dir(ts_value),
            f"{underlying_symbol}_{safe_label}_option_quotes.csv",
        )
        _ensure_schema(path)
        handle = open(path, "a", newline="", encoding="utf-8")
        writer = csv.writer(handle)
        self._handles[writer_key] = handle
        self._writers[writer_key] = writer
        self._flush_counts.setdefault(writer_key, 0)
        return writer

    def _close_all(self) -> None:
        for writer_key, handle in list(self._handles.items()):
            try:
                handle.flush()
                handle.close()
            except Exception:
                log.exception("[OptionQuoteSaver] close failed | key=%s", writer_key)
        self._handles.clear()
        self._writers.clear()
        self._flush_counts.clear()


option_quote_saver = OptionQuoteSaver()
atexit.register(option_quote_saver.close)
