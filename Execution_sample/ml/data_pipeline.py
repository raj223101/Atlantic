"""
Build a training DataFrame from saved candle CSVs.

The entry timeframe is the primary label index.
Exit and HTF features are forward-filled onto entry-timeframe closes.
"""

from __future__ import annotations

import os
import warnings
from typing import List, Optional, Tuple

import numpy as np
import pandas as pd

from config import CALC_SERIES_WINDOWS, DATA_DIR, INSTRUMENTS, RTC_PARAMETER_GRID, TF_ENTRY, TF_EXIT_TRIGGER, TF_HTF, timeframe_label
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
from ml.feature_builder import FEATURE_NAMES, N_FEATURES
from ml.label_generator import LabelGenerator

warnings.filterwarnings("ignore", category=FutureWarning)


def _suffix(tf_seconds: int) -> str:
    return timeframe_label(tf_seconds)


def _build_rename_map() -> dict:
    mapping = {
        "ADX": ADX,
        "DI_Plus": DI_PLUS,
        "S_DIP_BB": SLOPE_DIP_BB,
        "S_DIP_BB_Max": f"{SLOPE_DIP_BB}_max",
        "S_DIP_BB_Min": f"{SLOPE_DIP_BB}_min",
        "S_DIP_LR": SLOPE_DIP_LR,
        "S_DIP_LR_Max": f"{SLOPE_DIP_LR}_max",
        "S_DIP_LR_Min": f"{SLOPE_DIP_LR}_min",
        "DI_Minus": DI_MINUS,
        "S_DIM_BB": SLOPE_DIM_BB,
        "S_DIM_BB_Max": f"{SLOPE_DIM_BB}_max",
        "S_DIM_BB_Min": f"{SLOPE_DIM_BB}_min",
        "S_DIM_LR": SLOPE_DIM_LR,
        "S_DIM_LR_Max": f"{SLOPE_DIM_LR}_max",
        "S_DIM_LR_Min": f"{SLOPE_DIM_LR}_min",
        "S_ADX_BB": SLOPE_ADX_BB,
        "S_ADX_BB_Max": f"{SLOPE_ADX_BB}_max",
        "S_ADX_BB_Min": f"{SLOPE_ADX_BB}_min",
        "S_ADX_LR": SLOPE_ADX_LR,
        "S_ADX_LR_Max": f"{SLOPE_ADX_LR}_max",
        "S_ADX_LR_Min": f"{SLOPE_ADX_LR}_min",
        "VWMA": VWMA,
        "VWMA_BB": VWMA_BB,
        "VWMA_BB_Max": f"{VWMA_BB}_max",
        "VWMA_BB_Min": f"{VWMA_BB}_min",
        "VWMA_LR": VWMA_LR,
        "VWMA_LR_Max": f"{VWMA_LR}_max",
        "VWMA_LR_Min": f"{VWMA_LR}_min",
        "CVD": CVD,
        "CVD_BB": CVD_BB,
        "CVD_BB_Max": f"{CVD_BB}_max",
        "CVD_BB_Min": f"{CVD_BB}_min",
        "CVD_LR": CVD_LR,
        "CVD_LR_Max": f"{CVD_LR}_max",
        "CVD_LR_Min": f"{CVD_LR}_min",
    }

    for length in CALC_SERIES_WINDOWS:
        mapping[f"TEMA_{length}"] = TEMA(length)
        mapping[f"TEMA_{length}_BB"] = TEMA_BB(length)
        mapping[f"TEMA_{length}_BB_Max"] = f"{TEMA_BB(length)}_max"
        mapping[f"TEMA_{length}_BB_Min"] = f"{TEMA_BB(length)}_min"
        mapping[f"TEMA_{length}_LR"] = TEMA_LR(length)
        mapping[f"TEMA_{length}_LR_Max"] = f"{TEMA_LR(length)}_max"
        mapping[f"TEMA_{length}_LR_Min"] = f"{TEMA_LR(length)}_min"

    for kv, atr_period in RTC_PARAMETER_GRID:
        tag = f"UT_{kv}_{atr_period}"
        mapping[f"{tag}_Value"] = UT_VALUE(kv, atr_period)
        mapping[f"{tag}_BB"] = UT_SLOPE_BB(kv, atr_period)
        mapping[f"{tag}_BB_Max"] = f"{UT_SLOPE_BB(kv, atr_period)}_max"
        mapping[f"{tag}_BB_Min"] = f"{UT_SLOPE_BB(kv, atr_period)}_min"
        mapping[f"{tag}_LR"] = UT_SLOPE_LR(kv, atr_period)
        mapping[f"{tag}_LR_Max"] = f"{UT_SLOPE_LR(kv, atr_period)}_max"
        mapping[f"{tag}_LR_Min"] = f"{UT_SLOPE_LR(kv, atr_period)}_min"

    return mapping


RENAME_MAP = _build_rename_map()


class DataPipeline:

    @staticmethod
    def _read_csv(path: str) -> pd.DataFrame:
        if not os.path.exists(path):
            return pd.DataFrame()

        df = pd.read_csv(path)
        if df.empty or "Time" not in df.columns:
            return pd.DataFrame()

        df["Time"] = pd.to_datetime(df["Time"])
        df = (
            df.set_index("Time")
            .sort_index()
            .between_time("09:15", "15:30")
        )
        df = df.rename(
            columns={key: value for key, value in RENAME_MAP.items() if key in df.columns}
        )
        return df

    @staticmethod
    def load_symbol(symbol: str, data_dir: str = DATA_DIR) -> pd.DataFrame:
        exit_label = _suffix(TF_EXIT_TRIGGER)
        entry_label = _suffix(TF_ENTRY)
        htf_label = _suffix(TF_HTF)

        df_exit = DataPipeline._read_csv(
            os.path.join(data_dir, f"{symbol}_{exit_label}.csv")
        )
        df_entry = DataPipeline._read_csv(
            os.path.join(data_dir, f"{symbol}_{entry_label}.csv")
        )
        df_htf = DataPipeline._read_csv(
            os.path.join(data_dir, f"{symbol}_{htf_label}.csv")
        )

        if df_entry.empty:
            print(
                f"  {symbol}: no entry-timeframe data at "
                f"{data_dir}/{symbol}_{entry_label}.csv"
            )
            return pd.DataFrame()

        df_entry = LabelGenerator.apply_to_df(df_entry, close_col="Close")

        def _with_suffix(df: pd.DataFrame, tf_seconds: int) -> pd.DataFrame:
            keep = {"Open", "High", "Low", "Close", "Volume", "label"}
            label = _suffix(tf_seconds)
            return df.rename(
                columns={col: f"{col}_{label}" for col in df.columns if col not in keep}
            )

        df_exit_s = _with_suffix(df_exit, TF_EXIT_TRIGGER)
        df_entry_s = _with_suffix(df_entry, TF_ENTRY)
        df_htf_s = _with_suffix(df_htf, TF_HTF)

        merged = df_entry_s.copy()
        for tf_df in [df_exit_s, df_htf_s]:
            if tf_df.empty:
                continue
            aligned = tf_df.reindex(
                merged.index,
                method="ffill",
                tolerance=pd.Timedelta(seconds=TF_HTF),
            )
            for col in aligned.columns:
                merged[col] = aligned[col]

        for column in FEATURE_NAMES:
            if column not in merged.columns:
                merged[column] = 0.0

        merged = merged.fillna(0.0).replace([np.inf, -np.inf], 0.0)
        return merged

    @staticmethod
    def load_all_symbols(
        symbols: Optional[List[str]] = None,
        data_dir: str = DATA_DIR,
    ) -> pd.DataFrame:
        symbols = symbols or list(INSTRUMENTS.keys())
        frames = []
        for symbol in symbols:
            print(f"  Loading {symbol}...", end=" ", flush=True)
            df = DataPipeline.load_symbol(symbol, data_dir)
            if df.empty:
                print("skipped")
                continue
            df["symbol"] = symbol
            frames.append(df)
            print(f"{len(df):,} rows")
        return pd.concat(frames).sort_index() if frames else pd.DataFrame()

    @staticmethod
    def to_xy(df: pd.DataFrame) -> Tuple[np.ndarray, np.ndarray]:
        if df.empty:
            return np.empty((0, N_FEATURES), np.float32), np.empty(0, np.int8)

        available = [col for col in FEATURE_NAMES if col in df.columns]
        features = df[available].values.astype(np.float32)
        if len(available) < N_FEATURES:
            padding = np.zeros((len(features), N_FEATURES - len(available)), np.float32)
            features = np.hstack([features, padding])

        labels = df["label"].values.astype(np.int8)
        return features, labels

    @staticmethod
    def describe(df: pd.DataFrame):
        if df.empty:
            print("  Empty DataFrame")
            return
        print(f"  Shape  : {df.shape}")
        print(f"  Period : {df.index.min()} -> {df.index.max()}")
        if "label" in df.columns:
            LabelGenerator.class_distribution(df["label"].values)
