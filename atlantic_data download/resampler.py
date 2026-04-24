from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd


TIMEFRAME_RULES = {
    "1s": "1s",
    "5s": "5s",
    "10s": "10s",
    "15s": "15s",
    "30s": "30s",
    "1min": "1min",
}

MID_OHLC = ["open", "high", "low", "close"]
BID_OHLC = ["bid_open", "bid_high", "bid_low", "bid_close"]
ASK_OHLC = ["ask_open", "ask_high", "ask_low", "ask_close"]
SPREAD_OHLC = ["spread_open", "spread_high", "spread_low", "spread_close"]
SUM_COLUMNS = ["volume", "bid_volume", "ask_volume", "tick_count", "synthetic_seconds"]
FLOAT_COLUMNS = MID_OHLC + BID_OHLC + ASK_OHLC + SPREAD_OHLC + ["spread_mean"]


@dataclass
class ProcessingStats:
    source_files: int = 0
    raw_rows: int = 0
    valid_rows: int = 0
    duplicate_rows: int = 0
    bad_rows: int = 0
    empty_files: int = 0
    first_timestamp: str | None = None
    last_timestamp: str | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _empty_tick_frame() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "timestamp",
            "bid_price",
            "ask_price",
            "bid_volume",
            "ask_volume",
            "mid_price",
            "spread",
        ]
    )


def _empty_candle_frame() -> pd.DataFrame:
    frame = pd.DataFrame(
        columns=[
            "open",
            "high",
            "low",
            "close",
            "bid_open",
            "bid_high",
            "bid_low",
            "bid_close",
            "ask_open",
            "ask_high",
            "ask_low",
            "ask_close",
            "spread_open",
            "spread_high",
            "spread_low",
            "spread_close",
            "spread_mean",
            "volume",
            "bid_volume",
            "ask_volume",
            "tick_count",
            "synthetic_seconds",
        ]
    )
    frame.index = pd.DatetimeIndex([], tz="UTC", name="timestamp")
    return frame


def _normalize_timestamp(series: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(series, errors="coerce")
    if numeric.notna().all():
        return pd.to_datetime(numeric.astype("int64"), unit="ms", utc=True)
    return pd.to_datetime(series, utc=True, errors="coerce")


def normalize_tick_chunk(
    chunk: pd.DataFrame,
    max_spread_ratio: float = 0.10,
) -> tuple[pd.DataFrame, dict[str, int]]:
    stats = {
        "raw_rows": int(len(chunk)),
        "valid_rows": 0,
        "duplicate_rows": 0,
        "bad_rows": 0,
    }
    if chunk.empty:
        return _empty_tick_frame(), stats

    working = chunk.rename(
        columns={
            "Timestamp": "timestamp",
            "askPrice": "ask_price",
            "bidPrice": "bid_price",
            "askVolume": "ask_volume",
            "bidVolume": "bid_volume",
        }
    ).copy()

    required = {"timestamp", "bid_price", "ask_price"}
    missing = required.difference(working.columns)
    if missing:
        raise ValueError(f"Missing required tick columns: {sorted(missing)}")

    if "bid_volume" not in working.columns:
        working["bid_volume"] = 0.0
    if "ask_volume" not in working.columns:
        working["ask_volume"] = 0.0

    working["timestamp"] = _normalize_timestamp(working["timestamp"])
    for column in ("bid_price", "ask_price", "bid_volume", "ask_volume"):
        working[column] = pd.to_numeric(working[column], errors="coerce")

    before = len(working)
    working = working.dropna(subset=["timestamp", "bid_price", "ask_price"])
    stats["bad_rows"] += before - len(working)

    mask = (working["bid_price"] > 0) & (working["ask_price"] > 0) & (
        working["ask_price"] >= working["bid_price"]
    )
    invalid_count = int((~mask).sum())
    if invalid_count:
        stats["bad_rows"] += invalid_count
    working = working.loc[mask].copy()

    if working.empty:
        return _empty_tick_frame(), stats

    working["mid_price"] = (working["ask_price"] + working["bid_price"]) / 2.0
    working["spread"] = working["ask_price"] - working["bid_price"]
    spread_mask = (working["spread"] / working["mid_price"]).fillna(np.inf) <= max_spread_ratio
    spread_bad = int((~spread_mask).sum())
    if spread_bad:
        stats["bad_rows"] += spread_bad
    working = working.loc[spread_mask].copy()

    duplicate_mask = working.duplicated(
        subset=["timestamp", "bid_price", "ask_price", "bid_volume", "ask_volume"],
        keep="last",
    )
    duplicate_count = int(duplicate_mask.sum())
    if duplicate_count:
        stats["duplicate_rows"] = duplicate_count
        working = working.loc[~duplicate_mask].copy()

    working = working.sort_values("timestamp", kind="mergesort")
    stats["valid_rows"] = int(len(working))
    return working, stats


def aggregate_ticks_to_1s(ticks: pd.DataFrame) -> pd.DataFrame:
    if ticks.empty:
        return _empty_candle_frame()

    indexed = ticks.set_index("timestamp")

    mid_ohlc = indexed["mid_price"].resample("1s").ohlc()
    bid_ohlc = indexed["bid_price"].resample("1s").ohlc().add_prefix("bid_")
    ask_ohlc = indexed["ask_price"].resample("1s").ohlc().add_prefix("ask_")

    spread_resample = indexed["spread"].resample("1s")
    output = pd.concat(
        [
            mid_ohlc,
            bid_ohlc,
            ask_ohlc,
            spread_resample.first().rename("spread_open"),
            spread_resample.max().rename("spread_high"),
            spread_resample.min().rename("spread_low"),
            spread_resample.last().rename("spread_close"),
            spread_resample.mean().rename("spread_mean"),
            indexed["bid_volume"].resample("1s").sum().rename("bid_volume"),
            indexed["ask_volume"].resample("1s").sum().rename("ask_volume"),
            indexed["mid_price"].resample("1s").size().rename("tick_count"),
        ],
        axis=1,
    )

    output["volume"] = (output["bid_volume"].fillna(0.0) + output["ask_volume"].fillna(0.0)) / 2.0
    output["synthetic_seconds"] = 0
    output = output.loc[output["close"].notna()].copy()
    output.index.name = "timestamp"
    return output


def _merge_stats(target: ProcessingStats, update: dict[str, int], frame: pd.DataFrame) -> None:
    target.raw_rows += int(update["raw_rows"])
    target.valid_rows += int(update["valid_rows"])
    target.duplicate_rows += int(update["duplicate_rows"])
    target.bad_rows += int(update["bad_rows"])
    if not frame.empty:
        first_ts = frame["timestamp"].iloc[0].isoformat()
        last_ts = frame["timestamp"].iloc[-1].isoformat()
        target.first_timestamp = first_ts if target.first_timestamp is None else min(
            target.first_timestamp, first_ts
        )
        target.last_timestamp = last_ts if target.last_timestamp is None else max(
            target.last_timestamp, last_ts
        )


def process_tick_file(
    file_path: str | Path,
    chunk_size: int = 1_000_000,
    max_spread_ratio: float = 0.10,
) -> tuple[pd.DataFrame, ProcessingStats]:
    file_path = Path(file_path)
    stats = ProcessingStats(source_files=1)
    carryover = _empty_tick_frame()
    parts: list[pd.DataFrame] = []

    for chunk in pd.read_csv(file_path, chunksize=chunk_size):
        normalized, chunk_stats = normalize_tick_chunk(chunk, max_spread_ratio=max_spread_ratio)
        if not carryover.empty:
            normalized = pd.concat([carryover, normalized], axis=0, ignore_index=True)
            normalized = normalized.sort_values("timestamp", kind="mergesort")
            carryover = _empty_tick_frame()

        if normalized.empty:
            _merge_stats(stats, chunk_stats, _empty_tick_frame())
            continue

        bucket = normalized["timestamp"].dt.floor("1s")
        final_second = bucket.iloc[-1]
        is_carryover = bucket == final_second
        carryover = normalized.loc[is_carryover].copy()
        processable = normalized.loc[~is_carryover].copy()

        if not processable.empty:
            parts.append(aggregate_ticks_to_1s(processable))
        _merge_stats(stats, chunk_stats, normalized)

    if not carryover.empty:
        parts.append(aggregate_ticks_to_1s(carryover))

    if not parts:
        stats.empty_files += 1
        return _empty_candle_frame(), stats

    output = pd.concat(parts, axis=0).sort_index()
    output = output[~output.index.duplicated(keep="last")]
    return output, stats


def build_base_timeframe(
    files: Iterable[str | Path],
    chunk_size: int = 1_000_000,
    max_spread_ratio: float = 0.10,
) -> tuple[pd.DataFrame, ProcessingStats]:
    combined_stats = ProcessingStats()
    frames: list[pd.DataFrame] = []

    for file_path in files:
        frame, stats = process_tick_file(
            file_path=file_path,
            chunk_size=chunk_size,
            max_spread_ratio=max_spread_ratio,
        )
        combined_stats.source_files += stats.source_files
        combined_stats.raw_rows += stats.raw_rows
        combined_stats.valid_rows += stats.valid_rows
        combined_stats.duplicate_rows += stats.duplicate_rows
        combined_stats.bad_rows += stats.bad_rows
        combined_stats.empty_files += stats.empty_files

        if stats.first_timestamp is not None:
            combined_stats.first_timestamp = (
                stats.first_timestamp
                if combined_stats.first_timestamp is None
                else min(combined_stats.first_timestamp, stats.first_timestamp)
            )
        if stats.last_timestamp is not None:
            combined_stats.last_timestamp = (
                stats.last_timestamp
                if combined_stats.last_timestamp is None
                else max(combined_stats.last_timestamp, stats.last_timestamp)
            )

        if not frame.empty:
            frames.append(frame)

    if not frames:
        return _empty_candle_frame(), combined_stats

    merged = pd.concat(frames, axis=0).sort_index()
    merged = merged[~merged.index.duplicated(keep="last")]
    return merged, combined_stats


def ensure_continuous_seconds(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()

    continuous_index = pd.date_range(
        start=frame.index.min().floor("1s"),
        end=frame.index.max().floor("1s"),
        freq="1s",
        tz="UTC",
        name="timestamp",
    )
    output = frame.sort_index().reindex(continuous_index)
    synthetic_mask = output["close"].isna()

    for open_col, high_col, low_col, close_col in (
        ("open", "high", "low", "close"),
        ("bid_open", "bid_high", "bid_low", "bid_close"),
        ("ask_open", "ask_high", "ask_low", "ask_close"),
    ):
        close_series = output[close_col].ffill()
        fill_mask = output[close_col].isna()
        output.loc[fill_mask, open_col] = close_series.loc[fill_mask]
        output.loc[fill_mask, high_col] = close_series.loc[fill_mask]
        output.loc[fill_mask, low_col] = close_series.loc[fill_mask]
        output.loc[fill_mask, close_col] = close_series.loc[fill_mask]

    spread_reference = output["ask_close"] - output["bid_close"]
    for column in SPREAD_OHLC:
        output[column] = output[column].fillna(spread_reference)
    output["spread_mean"] = output["spread_mean"].fillna(spread_reference)

    for column in ("volume", "bid_volume", "ask_volume"):
        output[column] = output[column].fillna(0.0)
    output["tick_count"] = output["tick_count"].fillna(0).astype("int64")
    output["synthetic_seconds"] = np.where(synthetic_mask, 1, output["synthetic_seconds"].fillna(0)).astype(
        "int64"
    )
    return output


def resample_from_base(frame: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    if timeframe not in TIMEFRAME_RULES:
        raise KeyError(f"Unsupported timeframe: {timeframe}")
    if timeframe == "1s":
        return frame.copy()
    if frame.empty:
        return frame.copy()

    rule = TIMEFRAME_RULES[timeframe]
    resampled = pd.DataFrame(index=frame.resample(rule).size().index)

    for open_col, high_col, low_col, close_col in (
        ("open", "high", "low", "close"),
        ("bid_open", "bid_high", "bid_low", "bid_close"),
        ("ask_open", "ask_high", "ask_low", "ask_close"),
    ):
        resampled[open_col] = frame[open_col].resample(rule).first()
        resampled[high_col] = frame[high_col].resample(rule).max()
        resampled[low_col] = frame[low_col].resample(rule).min()
        resampled[close_col] = frame[close_col].resample(rule).last()

    resampled["spread_open"] = frame["spread_open"].resample(rule).first()
    resampled["spread_high"] = frame["spread_high"].resample(rule).max()
    resampled["spread_low"] = frame["spread_low"].resample(rule).min()
    resampled["spread_close"] = frame["spread_close"].resample(rule).last()
    resampled["spread_mean"] = frame["spread_mean"].resample(rule).mean()

    for column in SUM_COLUMNS:
        resampled[column] = frame[column].resample(rule).sum()

    resampled = resampled.loc[resampled["close"].notna()].copy()
    return resampled


def to_storage_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=["timestamp"] + list(frame.columns))

    output = frame.reset_index().copy()
    output["timestamp"] = (output["timestamp"].astype("int64") // 1_000_000).astype("int64")

    for column in FLOAT_COLUMNS + ["volume", "bid_volume", "ask_volume"]:
        if column in output.columns:
            output[column] = output[column].astype("float64")

    if "tick_count" in output.columns:
        output["tick_count"] = output["tick_count"].astype("int64")
    if "synthetic_seconds" in output.columns:
        output["synthetic_seconds"] = output["synthetic_seconds"].astype("int64")

    return output
