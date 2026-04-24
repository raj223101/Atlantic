from __future__ import annotations

import json
import random
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

import pandas as pd


DEFAULT_TIMEFRAMES = ["1s", "5s", "10s", "15s", "30s", "1min"]
GROUP_ALIASES = {
    "all": {"forex", "index", "commodity", "crypto"},
    "forex": {"forex"},
    "indices": {"index"},
    "index": {"index"},
    "commodities": {"commodity"},
    "commodity": {"commodity"},
    "crypto": {"crypto"},
}


@dataclass
class ExecutionConfig:
    delay_ms_min: int = 100
    delay_ms_max: int = 500
    slippage_bps_min: float = 0.1
    slippage_bps_max: float = 1.5
    spread_slippage_factor: float = 0.15
    random_seed: int | None = None


@dataclass
class ExecutionResult:
    side: str
    signal_timestamp: str
    execution_timestamp: str
    delay_ms: int
    quantity: float
    reference_price: float
    fill_price: float
    spread: float
    slippage: float
    notional: float

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def project_root() -> Path:
    return Path(__file__).resolve().parent


def load_instrument_config(config_path: str | Path | None = None) -> list[dict[str, str]]:
    path = Path(config_path) if config_path else project_root() / "config" / "instruments.json"
    with path.open("r", encoding="utf8") as handle:
        data = json.load(handle)
    return data


def resolve_symbols(
    symbol_spec: str | Iterable[str],
    config: list[dict[str, str]] | None = None,
) -> list[dict[str, str]]:
    config = config or load_instrument_config()
    by_symbol = {entry["symbol"].upper(): entry for entry in config}
    by_instrument = {entry["instrumentId"].upper(): entry for entry in config}

    if isinstance(symbol_spec, str):
        tokens = [part.strip() for part in symbol_spec.split(",") if part.strip()]
    else:
        tokens = [str(part).strip() for part in symbol_spec if str(part).strip()]

    if not tokens or any(token.lower() == "all" for token in tokens):
        return list(config)

    resolved: dict[str, dict[str, str]] = {}
    for token in tokens:
        lower = token.lower()
        if lower in GROUP_ALIASES:
            allowed = GROUP_ALIASES[lower]
            for entry in config:
                if entry["assetClass"] in allowed:
                    resolved[entry["symbol"]] = entry
            continue

        upper = token.upper()
        if upper in by_symbol:
            resolved[upper] = by_symbol[upper]
            continue
        if upper in by_instrument:
            resolved[by_instrument[upper]["symbol"]] = by_instrument[upper]
            continue
        raise ValueError(f"Unknown symbol or group: {token}")

    return list(resolved.values())


def ensure_directory(path: str | Path) -> Path:
    target = Path(path)
    target.mkdir(parents=True, exist_ok=True)
    return target


def _timestamp_to_index(series: pd.Series) -> pd.DatetimeIndex:
    numeric = pd.to_numeric(series, errors="coerce")
    if numeric.notna().all():
        return pd.to_datetime(numeric.astype("int64"), unit="ms", utc=True)
    return pd.to_datetime(series, utc=True, errors="coerce")


def _attach_utc_index(frame: pd.DataFrame, timestamp_column: str = "timestamp") -> pd.DataFrame:
    working = frame.copy()
    working[timestamp_column] = _timestamp_to_index(working[timestamp_column])
    working = working.dropna(subset=[timestamp_column]).sort_values(timestamp_column)
    working = working.set_index(timestamp_column)
    working.index.name = "timestamp"
    return working


def _normalize_datetime_argument(value: str | pd.Timestamp | None) -> pd.Timestamp | None:
    if value is None:
        return None
    if isinstance(value, pd.Timestamp):
        return value.tz_convert("UTC") if value.tzinfo else value.tz_localize("UTC")
    parsed = pd.Timestamp(value)
    return parsed.tz_convert("UTC") if parsed.tzinfo else parsed.tz_localize("UTC")


def _filter_index_range(
    frame: pd.DataFrame,
    start: str | pd.Timestamp | None = None,
    end: str | pd.Timestamp | None = None,
) -> pd.DataFrame:
    start_ts = _normalize_datetime_argument(start)
    end_ts = _normalize_datetime_argument(end)
    if start_ts is not None:
        frame = frame.loc[frame.index >= start_ts]
    if end_ts is not None:
        frame = frame.loc[frame.index <= end_ts]
    return frame


def load_raw_ticks(
    raw_root: str | Path,
    symbol: str,
    start: str | pd.Timestamp | None = None,
    end: str | pd.Timestamp | None = None,
) -> pd.DataFrame:
    root = Path(raw_root) / symbol.upper()
    start_ts = _normalize_datetime_argument(start)
    end_ts = _normalize_datetime_argument(end)

    files = []
    for file_path in sorted(root.glob("*.csv")):
        file_day = pd.Timestamp(file_path.stem).tz_localize("UTC")
        if start_ts is not None and file_day.normalize() < start_ts.normalize():
            continue
        if end_ts is not None and file_day.normalize() > end_ts.normalize():
            continue
        files.append(file_path)
    if not files:
        raise FileNotFoundError(f"No raw tick files found for {symbol} in {root}")

    frames = []
    for file_path in files:
        frame = pd.read_csv(file_path)
        frame = frame.rename(
            columns={
                "askPrice": "ask_price",
                "bidPrice": "bid_price",
                "askVolume": "ask_volume",
                "bidVolume": "bid_volume",
            }
        )
        frame = _attach_utc_index(frame)
        frames.append(frame)

    merged = pd.concat(frames, axis=0).sort_index()
    return _filter_index_range(merged, start=start_ts, end=end_ts)


def load_processed_candles(
    processed_root: str | Path,
    symbol: str,
    timeframe: str,
    start: str | pd.Timestamp | None = None,
    end: str | pd.Timestamp | None = None,
    prefer_parquet: bool = True,
) -> pd.DataFrame:
    symbol_dir = Path(processed_root) / symbol.upper()
    parquet_path = symbol_dir / f"{timeframe}.parquet"
    csv_path = symbol_dir / f"{timeframe}.csv"

    if prefer_parquet and parquet_path.exists():
        frame = pd.read_parquet(parquet_path)
    elif csv_path.exists():
        frame = pd.read_csv(csv_path)
    elif parquet_path.exists():
        frame = pd.read_parquet(parquet_path)
    else:
        raise FileNotFoundError(
            f"Could not find processed data for {symbol} timeframe {timeframe} in {symbol_dir}"
        )

    frame = _attach_utc_index(frame)
    return _filter_index_range(frame, start=start, end=end)


def load_multi_timeframe(
    processed_root: str | Path,
    symbol: str,
    timeframes: Iterable[str],
    start: str | pd.Timestamp | None = None,
    end: str | pd.Timestamp | None = None,
    prefer_parquet: bool = True,
) -> dict[str, pd.DataFrame]:
    return {
        timeframe: load_processed_candles(
            processed_root=processed_root,
            symbol=symbol,
            timeframe=timeframe,
            start=start,
            end=end,
            prefer_parquet=prefer_parquet,
        )
        for timeframe in timeframes
    }


def align_multi_timeframe(
    frames: dict[str, pd.DataFrame],
    base_timeframe: str = "1s",
) -> pd.DataFrame:
    if base_timeframe not in frames:
        raise KeyError(f"Base timeframe {base_timeframe} is missing from frames.")

    base = frames[base_timeframe].copy().sort_index()
    aligned = base

    for timeframe, frame in frames.items():
        if timeframe == base_timeframe:
            continue
        renamed = frame.sort_index().add_prefix(f"{timeframe}_")
        aligned = pd.merge_asof(
            aligned.sort_index(),
            renamed.sort_index(),
            left_index=True,
            right_index=True,
            direction="backward",
        )

    return aligned


def fast_lookup(
    frame: pd.DataFrame,
    timestamp: str | pd.Timestamp,
    direction: str = "backward",
) -> pd.Series:
    if frame.empty:
        raise ValueError("Cannot perform fast lookup on an empty frame.")

    probe = _normalize_datetime_argument(timestamp)
    index = frame.index

    if direction == "backward":
        position = index.searchsorted(probe, side="right") - 1
    elif direction == "forward":
        position = index.searchsorted(probe, side="left")
    else:
        raise ValueError("direction must be 'backward' or 'forward'")

    if position < 0 or position >= len(frame):
        raise KeyError(f"No row found for timestamp {probe} with direction={direction}")

    return frame.iloc[position]


def _resolve_quote_columns(frame: pd.DataFrame) -> tuple[str, str]:
    if {"bid_price", "ask_price"}.issubset(frame.columns):
        return "bid_price", "ask_price"
    if {"bid_close", "ask_close"}.issubset(frame.columns):
        return "bid_close", "ask_close"
    raise KeyError("Frame does not contain bid/ask price columns.")


def simulate_execution(
    frame: pd.DataFrame,
    side: str,
    signal_timestamp: str | pd.Timestamp,
    quantity: float = 1.0,
    config: ExecutionConfig | None = None,
) -> ExecutionResult:
    if quantity <= 0:
        raise ValueError("quantity must be positive")

    side_normalized = side.lower()
    if side_normalized not in {"buy", "sell"}:
        raise ValueError("side must be 'buy' or 'sell'")

    config = config or ExecutionConfig()
    rng = random.Random(config.random_seed)

    signal_ts = _normalize_datetime_argument(signal_timestamp)
    delay_ms = rng.randint(config.delay_ms_min, config.delay_ms_max)
    execution_ts = signal_ts + pd.Timedelta(milliseconds=delay_ms)
    execution_row = fast_lookup(frame.sort_index(), execution_ts, direction="forward")

    bid_column, ask_column = _resolve_quote_columns(frame)
    bid_price = float(execution_row[bid_column])
    ask_price = float(execution_row[ask_column])
    spread = max(0.0, ask_price - bid_price)

    reference_price = ask_price if side_normalized == "buy" else bid_price
    random_bps = rng.uniform(config.slippage_bps_min, config.slippage_bps_max) / 10000.0
    slippage = reference_price * random_bps + (spread * config.spread_slippage_factor)
    fill_price = reference_price + slippage if side_normalized == "buy" else reference_price - slippage

    return ExecutionResult(
        side=side_normalized,
        signal_timestamp=signal_ts.isoformat(),
        execution_timestamp=execution_row.name.isoformat(),
        delay_ms=delay_ms,
        quantity=float(quantity),
        reference_price=reference_price,
        fill_price=fill_price,
        spread=spread,
        slippage=slippage,
        notional=fill_price * float(quantity),
    )
