"""
Asynchronous live tick persistence.
"""

from __future__ import annotations

import atexit
import csv
import math
import os
import queue
import threading
from datetime import datetime
from typing import Dict

from core.logger import log
from storage.day_paths import ticks_dir

HEADERS = [
    "Time",
    "Symbol",
    "LTP",
    "Volume",
    "Market_Volume_Day",
    "Token",
    "Exchange_Type",
    "Angel_Symbol",
    "Subscription_Mode",
    "Sequence_Number",
    "Last_Traded_Qty",
    "Average_Traded_Price",
    "Total_Buy_Qty",
    "Total_Sell_Qty",
    "Open_Interest",
    "OI_Change_Pct",
    "Best_Bid_Price",
    "Best_Bid_Qty",
    "Best_Ask_Price",
    "Best_Ask_Qty",
    "Spread",
    "Day_Open",
    "Day_High",
    "Day_Low",
    "Prev_Close",
    "Upper_Circuit",
    "Lower_Circuit",
    "Last_Traded_Timestamp",
    "Recv_Epoch",
]

FLUSH_EVERY = 100


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


class TickSaver:
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
                name="TickSaver",
                daemon=True,
            )
            self._thread.start()
            log.info("[TickSaver] worker started")

    def enqueue(self, tick: dict) -> None:
        if self._closed:
            return

        self.start()

        raw = tick.get("raw") or {}
        ts = tick.get("timestamp")
        if isinstance(ts, datetime):
            ts_text = ts.strftime("%Y-%m-%d %H:%M:%S.%f")
            day_key = ts.strftime("%Y-%m-%d")
        else:
            ts_text = ""
            day_key = datetime.now().strftime("%Y-%m-%d")

        item = {
            "time": ts_text,
            "day_key": day_key,
            "symbol": str(tick.get("symbol", "")),
            "ltp": _num(tick.get("ltp")),
            "volume": _int(tick.get("volume", raw.get("volume", 0))),
            "market_volume_day": _int(raw.get("market_volume_day", raw.get("volume", 0))),
            "token": str(raw.get("token", "")),
            "exchange_type": _int(raw.get("exchange_type")),
            "angel_symbol": str(raw.get("angel_symbol", "")),
            "subscription_mode": _int(raw.get("subscription_mode")),
            "sequence_number": _int(raw.get("sequence_number")),
            "last_traded_quantity": _int(raw.get("last_traded_quantity")),
            "average_traded_price": _num(raw.get("average_traded_price")),
            "total_buy_quantity": _num(raw.get("total_buy_quantity")),
            "total_sell_quantity": _num(raw.get("total_sell_quantity")),
            "open_interest": _int(raw.get("open_interest")),
            "oi_change_pct": _num(raw.get("open_interest_change_percentage")),
            "best_bid_price": _num(raw.get("best_bid_price")),
            "best_bid_qty": _int(raw.get("best_bid_qty")),
            "best_ask_price": _num(raw.get("best_ask_price")),
            "best_ask_qty": _int(raw.get("best_ask_qty")),
            "spread": _num(raw.get("spread")),
            "day_open": _num(raw.get("open_price_of_the_day")),
            "day_high": _num(raw.get("high_price_of_the_day")),
            "day_low": _num(raw.get("low_price_of_the_day")),
            "prev_close": _num(raw.get("closed_price")),
            "upper_circuit": _num(raw.get("upper_circuit_limit")),
            "lower_circuit": _num(raw.get("lower_circuit_limit")),
            "last_traded_timestamp": _int(raw.get("last_traded_timestamp")),
            "recv_epoch": _num(tick.get("recv_epoch")),
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
                    "[TickSaver] write failed | symbol=%s error=%s",
                    item.get("symbol"),
                    exc,
                    exc_info=True,
                )
        self._close_all()

    def _write_item(self, item: dict) -> None:
        symbol = item["symbol"] or "UNKNOWN"
        writer_key = f"{item.get('day_key', '')}:{symbol}"
        writer = self._ensure_writer(writer_key, symbol, item.get("time"))
        writer.writerow(
            [
                item["time"],
                symbol,
                item["ltp"],
                item["volume"],
                item["market_volume_day"],
                item["token"],
                item["exchange_type"],
                item["angel_symbol"],
                item["subscription_mode"],
                item["sequence_number"],
                item["last_traded_quantity"],
                item["average_traded_price"],
                item["total_buy_quantity"],
                item["total_sell_quantity"],
                item["open_interest"],
                item["oi_change_pct"],
                item["best_bid_price"],
                item["best_bid_qty"],
                item["best_ask_price"],
                item["best_ask_qty"],
                item["spread"],
                item["day_open"],
                item["day_high"],
                item["day_low"],
                item["prev_close"],
                item["upper_circuit"],
                item["lower_circuit"],
                item["last_traded_timestamp"],
                item["recv_epoch"],
            ]
        )

        self._flush_counts[writer_key] = self._flush_counts.get(writer_key, 0) + 1
        if self._flush_counts[writer_key] >= FLUSH_EVERY:
            handle = self._handles.get(writer_key)
            if handle is not None:
                handle.flush()
            self._flush_counts[writer_key] = 0

    def _ensure_writer(self, writer_key: str, symbol: str, ts_value) -> csv.writer:
        writer = self._writers.get(writer_key)
        if writer is not None:
            return writer

        path = os.path.join(ticks_dir(ts_value), f"{symbol}_ticks.csv")
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
                log.exception("[TickSaver] close failed | key=%s", writer_key)
        self._handles.clear()
        self._writers.clear()
        self._flush_counts.clear()


tick_saver = TickSaver()
atexit.register(tick_saver.close)
