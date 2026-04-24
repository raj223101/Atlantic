"""
Runtime history warmup for closed candles.
"""

from __future__ import annotations

import csv
import glob
import os
import time
from collections import OrderedDict, deque
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional

from candle_engine.timeframe_manager import TimeframeManager
from config import (
    DATA_DIR,
    HISTORICAL_WARMUP_API_CHUNK_DAYS,
    HISTORICAL_WARMUP_CANDLES,
    HISTORICAL_WARMUP_ENABLED,
    HISTORICAL_WARMUP_FETCH_DELAY_S,
    candles_per_session,
    timeframe_label,
)
from core.api_context import get_trading_api
from core.logger import log
from core.state_memory import memory
from calculation.x_c_rtc_engine import x_c_rtc_engine


INTERVAL_MAP = {
    60: "ONE_MINUTE",
    300: "FIVE_MINUTE",
    600: "TEN_MINUTE",
    900: "FIFTEEN_MINUTE",
    1800: "THIRTY_MINUTE",
    3600: "ONE_HOUR",
}

EXCHANGE_MAP = {
    "nse_cm": "NSE",
    "bse_cm": "BSE",
    "nse_fo": "NFO",
    "bse_fo": "BFO",
}

LOCAL_DERIVATION_SOURCES = (60, 30, 15, 10, 5, 2)


def _parse_ts(raw: Any) -> datetime:
    if isinstance(raw, datetime):
        return raw.replace(tzinfo=None)
    text = str(raw).strip()
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S",
    ):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=None)
        except ValueError:
            continue
    raise ValueError(f"cannot parse timestamp: {raw}")


def _to_candle(
    ts: Any,
    open_price: Any,
    high_price: Any,
    low_price: Any,
    close_price: Any,
    volume: Any = 0,
) -> Dict[str, Any]:
    return {
        "time": _parse_ts(ts),
        "open": float(open_price),
        "high": float(high_price),
        "low": float(low_price),
        "close": float(close_price),
        "volume": int(float(volume or 0)),
    }


def _days_needed(tf_seconds: int, n_candles: int) -> int:
    candles_day = candles_per_session(tf_seconds)
    return int((n_candles / candles_day + 2) * 1.6) + 3


def _dedup_and_trim(candles: Iterable[Dict[str, Any]], limit: int) -> List[Dict[str, Any]]:
    seen: OrderedDict[datetime, Dict[str, Any]] = OrderedDict()
    for candle in sorted(candles, key=lambda item: item["time"]):
        seen[candle["time"]] = candle
    if limit <= 0:
        return list(seen.values())
    return list(deque(seen.values(), maxlen=int(limit)))


def _local_candle_files(symbol: str, tf_seconds: int) -> List[str]:
    file_name = f"{symbol}_{timeframe_label(tf_seconds)}.csv"
    patterns = (
        os.path.join(DATA_DIR, file_name),
        os.path.join(DATA_DIR, "**", file_name),
    )
    matches = {
        os.path.normpath(path)
        for pattern in patterns
        for path in glob.glob(pattern, recursive=True)
        if os.path.isfile(path)
    }
    return sorted(matches)


def _load_local_exact(symbol: str, tf_seconds: int, limit: int) -> List[Dict[str, Any]]:
    candles: List[Dict[str, Any]] = []
    for path in _local_candle_files(symbol, tf_seconds):
        try:
            with open(path, newline="", encoding="utf-8") as handle:
                reader = csv.DictReader(handle)
                for row in reader:
                    try:
                        candles.append(
                            _to_candle(
                                row["Time"],
                                row["Open"],
                                row["High"],
                                row["Low"],
                                row["Close"],
                                row.get("Volume", 0),
                            )
                        )
                    except Exception:
                        continue
        except Exception as exc:
            log.warning("[HistoryLoader] local read failed | path=%s error=%s", path, exc)
    return _dedup_and_trim(candles, limit)


def _aggregate_candles(
    candles: Iterable[Dict[str, Any]],
    *,
    target_tf: int,
    limit: int,
) -> List[Dict[str, Any]]:
    buckets: OrderedDict[datetime, Dict[str, Any]] = OrderedDict()
    for candle in sorted(candles, key=lambda item: item["time"]):
        bucket_start, _ = TimeframeManager.get_bucket(candle["time"], target_tf)
        current = buckets.get(bucket_start)
        if current is None:
            buckets[bucket_start] = {
                "time": bucket_start,
                "open": float(candle["open"]),
                "high": float(candle["high"]),
                "low": float(candle["low"]),
                "close": float(candle["close"]),
                "volume": int(candle.get("volume", 0)),
            }
            continue
        current["high"] = max(float(current["high"]), float(candle["high"]))
        current["low"] = min(float(current["low"]), float(candle["low"]))
        current["close"] = float(candle["close"])
        current["volume"] = int(current.get("volume", 0)) + int(candle.get("volume", 0))
    return _dedup_and_trim(buckets.values(), limit)


def _load_local_derived(symbol: str, tf_seconds: int, limit: int) -> List[Dict[str, Any]]:
    for source_tf in LOCAL_DERIVATION_SOURCES:
        if source_tf >= tf_seconds or tf_seconds % source_tf != 0:
            continue
        source_candles = _load_local_exact(symbol, source_tf, max(limit * (tf_seconds // source_tf), limit))
        if not source_candles:
            continue
        derived = _aggregate_candles(source_candles, target_tf=tf_seconds, limit=limit)
        if derived:
            return derived
    return []


def _fetch_rows(
    api: Any,
    *,
    token: str,
    exchange: str,
    interval: str,
    from_dt: datetime,
    to_dt: datetime,
) -> List[List[Any]]:
    params = {
        "exchange": exchange,
        "symboltoken": token,
        "interval": interval,
        "fromdate": from_dt.strftime("%Y-%m-%d %H:%M"),
        "todate": to_dt.strftime("%Y-%m-%d %H:%M"),
    }
    try:
        response = api.getCandleData(params)
    except Exception as exc:
        log.warning(
            "[HistoryLoader] API history failed | exchange=%s token=%s interval=%s error=%s",
            exchange,
            token,
            interval,
            exc,
        )
        return []

    if not response:
        return []
    if not response.get("status"):
        log.warning(
            "[HistoryLoader] API history rejected | exchange=%s token=%s interval=%s msg=%s code=%s",
            exchange,
            token,
            interval,
            response.get("message", "?"),
            response.get("errorcode", ""),
        )
        return []
    return response.get("data") or []


def _load_api_exact(api: Any, info: Dict[str, Any], tf_seconds: int, limit: int) -> List[Dict[str, Any]]:
    interval = INTERVAL_MAP.get(int(tf_seconds))
    if not interval:
        return []

    exchange_raw = str(info.get("exchange", "NSE")).lower()
    exchange = EXCHANGE_MAP.get(exchange_raw, str(info.get("exchange", "NSE")).upper())
    token = str(info["token"])
    days_back = _days_needed(tf_seconds, limit)
    chunk_days = max(int(HISTORICAL_WARMUP_API_CHUNK_DAYS), 1)
    to_dt = datetime.now()
    from_dt = to_dt - timedelta(days=days_back)

    rows: List[List[Any]] = []
    chunk_from = from_dt
    while chunk_from < to_dt:
        chunk_to = min(chunk_from + timedelta(days=chunk_days), to_dt)
        rows.extend(
            _fetch_rows(
                api,
                token=token,
                exchange=exchange,
                interval=interval,
                from_dt=chunk_from,
                to_dt=chunk_to,
            )
        )
        chunk_from = chunk_to + timedelta(seconds=tf_seconds)
        sleep_seconds = float(HISTORICAL_WARMUP_FETCH_DELAY_S)
        if sleep_seconds > 0:
            time.sleep(sleep_seconds)

    candles: List[Dict[str, Any]] = []
    for row in rows:
        try:
            candles.append(_to_candle(row[0], row[1], row[2], row[3], row[4], row[5] if len(row) > 5 else 0))
        except Exception:
            continue
    return _dedup_and_trim(candles, limit)


def _load_api_derived(api: Any, info: Dict[str, Any], tf_seconds: int, limit: int) -> List[Dict[str, Any]]:
    if tf_seconds < 120 or tf_seconds % 60 != 0:
        return []
    base_limit = max(limit * (tf_seconds // 60), limit)
    one_minute = _load_api_exact(api, info, 60, base_limit)
    if not one_minute:
        return []
    return _aggregate_candles(one_minute, target_tf=tf_seconds, limit=limit)


def _load_timeframe_history(
    symbol: str,
    info: Dict[str, Any],
    tf_seconds: int,
    limit: int,
    api: Any,
) -> List[Dict[str, Any]]:
    exact_local = _load_local_exact(symbol, tf_seconds, limit)
    if exact_local:
        return exact_local

    derived_local = _load_local_derived(symbol, tf_seconds, limit)
    if derived_local:
        return derived_local

    if api is None:
        return []

    exact_api = _load_api_exact(api, info, tf_seconds, limit)
    if exact_api:
        return exact_api

    return _load_api_derived(api, info, tf_seconds, limit)


def load_runtime_history(
    instruments: Dict[str, Dict[str, Any]],
    timeframes: Iterable[int],
) -> Dict[str, Dict[int, int]]:
    if not bool(HISTORICAL_WARMUP_ENABLED):
        return {}

    api = get_trading_api()
    limit = max(int(HISTORICAL_WARMUP_CANDLES), 0)
    if limit <= 0:
        return {}

    summary: Dict[str, Dict[int, int]] = {}
    active_timeframes = tuple(sorted(set(int(tf) for tf in timeframes)))

    for symbol, info in instruments.items():
        loaded_for_symbol: Dict[int, int] = {}
        for tf_seconds in active_timeframes:
            candles = _load_timeframe_history(symbol, info, tf_seconds, limit, api)
            if not candles:
                continue

            for candle in candles:
                memory.update_closed_candle(symbol, tf_seconds, candle)
            x_c_rtc_engine.warm_up(symbol, tf_seconds, candles)
            loaded_for_symbol[int(tf_seconds)] = len(candles)
            log.info(
                "[HistoryLoader] warmup loaded | symbol=%s tf=%ss candles=%d",
                symbol,
                tf_seconds,
                len(candles),
            )

        if loaded_for_symbol:
            summary[symbol] = loaded_for_symbol

    return summary
