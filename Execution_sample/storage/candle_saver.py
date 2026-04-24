"""Persist closed candles with calculation snapshots and market-data context."""

from __future__ import annotations

import csv
import math
import os
from datetime import datetime
from typing import Dict

from config import CALC_SERIES_WINDOWS, MAINTENANCE_MODE, RTC_PARAMETER_GRID, timeframe_label
from core.logger import log
from core.maintenance import log_maintenance_once
from storage.day_paths import candle_dir
from execution.key_map import (
    ADX,
    CVD,
    CVD_BB,
    CVD_LR,
    DI_MINUS,
    DI_PLUS,
    SLOPE_ADX_BB,
    SLOPE_ADX_LR,
    SLOPE_DIM_BB,
    SLOPE_DIM_LR,
    SLOPE_DIP_BB,
    SLOPE_DIP_LR,
    TEMA,
    TEMA_BB,
    TEMA_LR,
    UT_SLOPE_BB,
    UT_SLOPE_LR,
    UT_STATE,
    UT_VALUE,
    VWMA,
    VWMA_BB,
    VWMA_LR,
)


def _build_headers() -> list[str]:
    headers = [
        "Time",
        "Open",
        "High",
        "Low",
        "Close",
        "Volume",
        "Tick_Count",
        "Market_Volume_Day",
        "Last_Traded_Qty",
        "Average_Traded_Price",
        "Total_Buy_Qty",
        "Total_Sell_Qty",
        "Open_Interest",
        "Open_Interest_High",
        "Open_Interest_Low",
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
        "Sequence_Number",
    ]
    headers += [
        "ADX",
        "DI_Plus",
        "DI_Plus_Angle",
        "S_DIP_BB",
        "S_DIP_BB_Max",
        "S_DIP_BB_Min",
        "S_DIP_LR",
        "S_DIP_LR_Max",
        "S_DIP_LR_Min",
        "DI_Minus",
        "DI_Minus_Angle",
        "DL_Angle_Spread",
        "S_DIM_BB",
        "S_DIM_BB_Max",
        "S_DIM_BB_Min",
        "S_DIM_LR",
        "S_DIM_LR_Max",
        "S_DIM_LR_Min",
        "S_ADX_BB",
        "S_ADX_BB_Max",
        "S_ADX_BB_Min",
        "S_ADX_LR",
        "S_ADX_LR_Max",
        "S_ADX_LR_Min",
        "VWMA",
        "VWMA_BB",
        "VWMA_BB_Max",
        "VWMA_BB_Min",
        "VWMA_LR",
        "VWMA_LR_Max",
        "VWMA_LR_Min",
        "CVD",
        "CVD_BB",
        "CVD_BB_Max",
        "CVD_BB_Min",
        "CVD_LR",
        "CVD_LR_Max",
        "CVD_LR_Min",
    ]

    for length in CALC_SERIES_WINDOWS:
        headers += [
            f"TEMA_{length}",
            f"TEMA_{length}_Angle",
            f"TEMA_{length}_BB",
            f"TEMA_{length}_BB_Max",
            f"TEMA_{length}_BB_Min",
            f"TEMA_{length}_LR",
            f"TEMA_{length}_LR_Max",
            f"TEMA_{length}_LR_Min",
        ]

    for keyvalue, atrperiod in RTC_PARAMETER_GRID:
        tag = f"UT_{keyvalue}_{atrperiod}"
        headers += [
            f"{tag}_Value",
            f"{tag}_State",
            f"{tag}_Angle",
            f"{tag}_BB",
            f"{tag}_BB_Max",
            f"{tag}_BB_Min",
            f"{tag}_LR",
            f"{tag}_LR_Max",
            f"{tag}_LR_Min",
        ]

    return headers


HEADERS = _build_headers()


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


def _snapshot_num(snapshot: Dict, key: str) -> float:
    return _num(snapshot.get(key))


def _text(snapshot: Dict, key: str) -> str:
    value = snapshot.get(key, "")
    return str(value) if value is not None else ""


def _stat(stats: Dict, key: str) -> float:
    return _num(stats.get(key))


def _ensure_schema(path: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    if not os.path.isfile(path):
        with open(path, "w", newline="") as handle:
            csv.writer(handle).writerow(HEADERS)
        return

    try:
        with open(path, newline="") as handle:
            reader = csv.reader(handle)
            existing = next(reader, [])
    except Exception:
        existing = []

    if existing == HEADERS:
        return

    backup = f"{path}.legacy_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    os.replace(path, backup)
    with open(path, "w", newline="") as handle:
        csv.writer(handle).writerow(HEADERS)


def save_candle(
    symbol: str,
    tf: int,
    candle: dict,
    snapshot: dict | None = None,
    stats: dict | None = None,
) -> None:
    if MAINTENANCE_MODE:
        log_maintenance_once("storage.candle_saver")
        return

    try:
        candle_ts = candle.get("time")
        path = os.path.join(candle_dir(tf, candle_ts), f"{symbol}_{timeframe_label(tf)}.csv")
        _ensure_schema(path)

        snap = snapshot or {}
        candle_stats = stats or {}

        row = [
            candle["time"].strftime("%Y-%m-%d %H:%M:%S"),
            round(candle.get("open", 0.0), 4),
            round(candle.get("high", 0.0), 4),
            round(candle.get("low", 0.0), 4),
            round(candle.get("close", 0.0), 4),
            int(candle.get("volume", 0)),
            int(candle.get("tick_count", 0)),
            int(candle.get("volume", 0) if candle.get("market_volume_day") is None else candle.get("market_volume_day", 0)),
            int(candle.get("last_traded_quantity", 0)),
            _num(candle.get("average_traded_price")),
            _num(candle.get("total_buy_quantity")),
            _num(candle.get("total_sell_quantity")),
            int(candle.get("open_interest", 0)),
            _num(candle.get("open_interest_high")),
            _num(candle.get("open_interest_low")),
            _num(candle.get("open_interest_change_percentage")),
            _num(candle.get("best_bid_price")),
            int(candle.get("best_bid_qty", 0)),
            _num(candle.get("best_ask_price")),
            int(candle.get("best_ask_qty", 0)),
            _num(candle.get("spread")),
            _num(candle.get("open_price_of_the_day")),
            _num(candle.get("high_price_of_the_day")),
            _num(candle.get("low_price_of_the_day")),
            _num(candle.get("closed_price")),
            _num(candle.get("upper_circuit_limit")),
            _num(candle.get("lower_circuit_limit")),
            int(candle.get("sequence_number", 0)),
            _snapshot_num(snap, ADX),
            _snapshot_num(snap, DI_PLUS),
            _snapshot_num(snap, "di_plus_angle"),
            _snapshot_num(snap, SLOPE_DIP_BB),
            _stat(candle_stats, f"{SLOPE_DIP_BB}_max"),
            _stat(candle_stats, f"{SLOPE_DIP_BB}_min"),
            _snapshot_num(snap, SLOPE_DIP_LR),
            _stat(candle_stats, f"{SLOPE_DIP_LR}_max"),
            _stat(candle_stats, f"{SLOPE_DIP_LR}_min"),
            _snapshot_num(snap, DI_MINUS),
            _snapshot_num(snap, "di_minus_angle"),
            _snapshot_num(snap, "dl_angle_spread"),
            _snapshot_num(snap, SLOPE_DIM_BB),
            _stat(candle_stats, f"{SLOPE_DIM_BB}_max"),
            _stat(candle_stats, f"{SLOPE_DIM_BB}_min"),
            _snapshot_num(snap, SLOPE_DIM_LR),
            _stat(candle_stats, f"{SLOPE_DIM_LR}_max"),
            _stat(candle_stats, f"{SLOPE_DIM_LR}_min"),
            _snapshot_num(snap, SLOPE_ADX_BB),
            _stat(candle_stats, f"{SLOPE_ADX_BB}_max"),
            _stat(candle_stats, f"{SLOPE_ADX_BB}_min"),
            _snapshot_num(snap, SLOPE_ADX_LR),
            _stat(candle_stats, f"{SLOPE_ADX_LR}_max"),
            _stat(candle_stats, f"{SLOPE_ADX_LR}_min"),
            _snapshot_num(snap, VWMA),
            _snapshot_num(snap, VWMA_BB),
            _stat(candle_stats, f"{VWMA_BB}_max"),
            _stat(candle_stats, f"{VWMA_BB}_min"),
            _snapshot_num(snap, VWMA_LR),
            _stat(candle_stats, f"{VWMA_LR}_max"),
            _stat(candle_stats, f"{VWMA_LR}_min"),
            _snapshot_num(snap, CVD),
            _snapshot_num(snap, CVD_BB),
            _stat(candle_stats, f"{CVD_BB}_max"),
            _stat(candle_stats, f"{CVD_BB}_min"),
            _snapshot_num(snap, CVD_LR),
            _stat(candle_stats, f"{CVD_LR}_max"),
            _stat(candle_stats, f"{CVD_LR}_min"),
        ]

        for length in CALC_SERIES_WINDOWS:
            row += [
                _snapshot_num(snap, TEMA(length)),
                _snapshot_num(snap, f"tema_{length}_tema_angle"),
                _snapshot_num(snap, TEMA_BB(length)),
                _stat(candle_stats, f"{TEMA_BB(length)}_max"),
                _stat(candle_stats, f"{TEMA_BB(length)}_min"),
                _snapshot_num(snap, TEMA_LR(length)),
                _stat(candle_stats, f"{TEMA_LR(length)}_max"),
                _stat(candle_stats, f"{TEMA_LR(length)}_min"),
            ]

        for keyvalue, atrperiod in RTC_PARAMETER_GRID:
            slope_bb = UT_SLOPE_BB(keyvalue, atrperiod)
            slope_lr = UT_SLOPE_LR(keyvalue, atrperiod)
            row += [
                _snapshot_num(snap, UT_VALUE(keyvalue, atrperiod)),
                _text(snap, UT_STATE(keyvalue, atrperiod)),
                _snapshot_num(snap, f"ut_{keyvalue}_{atrperiod}_ut_angle"),
                _snapshot_num(snap, slope_bb),
                _stat(candle_stats, f"{slope_bb}_max"),
                _stat(candle_stats, f"{slope_bb}_min"),
                _snapshot_num(snap, slope_lr),
                _stat(candle_stats, f"{slope_lr}_max"),
                _stat(candle_stats, f"{slope_lr}_min"),
            ]

        with open(path, "a", newline="") as handle:
            csv.writer(handle).writerow(row)
    except Exception as exc:
        log.error("[CandleSaver] failed | symbol=%s tf=%ss error=%s", symbol, tf, exc, exc_info=True)
