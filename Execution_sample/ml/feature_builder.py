"""
Convert live calculation snapshots into a flat feature vector.

The feature schema mirrors the candle CSV columns and is keyed by the
configured exit, entry, and HTF timeframes.
"""

from __future__ import annotations

from typing import Dict, List, Tuple

import numpy as np

from config import CALC_SERIES_WINDOWS, RTC_PARAMETER_GRID, TF_ENTRY, TF_EXIT_TRIGGER, TF_HTF, timeframe_label
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
    UT_VALUE,
    VWMA,
    VWMA_BB,
    VWMA_LR,
)

ROLE_TIMEFRAMES = [TF_EXIT_TRIGGER, TF_ENTRY, TF_HTF]

VALUE_ONLY_KEYS = [ADX, DI_PLUS, DI_MINUS, VWMA, CVD]
SLOPE_KEYS = [
    SLOPE_DIP_BB,
    SLOPE_DIP_LR,
    SLOPE_DIM_BB,
    SLOPE_DIM_LR,
    SLOPE_ADX_BB,
    SLOPE_ADX_LR,
    VWMA_BB,
    VWMA_LR,
    CVD_BB,
    CVD_LR,
]


def _suffix(tf_seconds: int) -> str:
    return f"_{timeframe_label(tf_seconds)}"


def _with_stats(base_key: str) -> List[str]:
    return [base_key, f"{base_key}_max", f"{base_key}_min"]


def _build_feature_names() -> List[str]:
    names: List[str] = []

    for tf_seconds in ROLE_TIMEFRAMES:
        sfx = _suffix(tf_seconds)

        for key in VALUE_ONLY_KEYS:
            names.append(f"{key}{sfx}")

        for key in SLOPE_KEYS:
            for stat_key in _with_stats(key):
                names.append(f"{stat_key}{sfx}")

        for length in CALC_SERIES_WINDOWS:
            names.append(f"{TEMA(length)}{sfx}")
            for key in [TEMA_BB(length), TEMA_LR(length)]:
                for stat_key in _with_stats(key):
                    names.append(f"{stat_key}{sfx}")

        for kv, ap in RTC_PARAMETER_GRID:
            names.append(f"{UT_VALUE(kv, ap)}{sfx}")
            for key in [UT_SLOPE_BB(kv, ap), UT_SLOPE_LR(kv, ap)]:
                for stat_key in _with_stats(key):
                    names.append(f"{stat_key}{sfx}")

    return names


FEATURE_NAMES: List[str] = _build_feature_names()
N_FEATURES: int = len(FEATURE_NAMES)


class FeatureBuilder:
    """Build feature vectors for live inference and offline training."""

    @staticmethod
    def from_live(
        ind_exit: Dict,
        ind_entry: Dict,
        ind_htf: Dict,
        stats_exit: Dict,
        stats_entry: Dict,
        stats_htf: Dict,
    ) -> Tuple[np.ndarray, List[str]]:
        tf_data = {
            TF_EXIT_TRIGGER: (ind_exit, stats_exit),
            TF_ENTRY: (ind_entry, stats_entry),
            TF_HTF: (ind_htf, stats_htf),
        }
        return FeatureBuilder._build(tf_data)

    @staticmethod
    def from_csv_row(row: Dict) -> Tuple[np.ndarray, List[str]]:
        fv = np.array(
            [float(row.get(name, 0.0)) for name in FEATURE_NAMES],
            dtype=np.float32,
        )
        return fv, FEATURE_NAMES

    @staticmethod
    def _build(tf_data: Dict) -> Tuple[np.ndarray, List[str]]:
        lookup: Dict[str, float] = {}

        for tf_seconds, (snapshots, stats) in tf_data.items():
            sfx = _suffix(tf_seconds)

            for key, value in snapshots.items():
                lookup[f"{key}{sfx}"] = _safe(value)

            for key, value in stats.items():
                lookup[f"{key}{sfx}"] = _safe(value)

        fv = np.array(
            [lookup.get(name, 0.0) for name in FEATURE_NAMES],
            dtype=np.float32,
        )
        return fv, FEATURE_NAMES


def _safe(value) -> float:
    import math

    if value is None:
        return 0.0
    try:
        num = float(value)
        return 0.0 if (math.isnan(num) or math.isinf(num)) else num
    except (TypeError, ValueError):
        return 0.0
