from pathlib import Path
import pandas as pd
from utils import sanitize_symbol

NUMERIC_COLS = ["open", "high", "low", "close", "volume", "returns", "rolling_volatility"]

def _normalize_loaded_df(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if "datetime" in out.columns:
        out["datetime"] = pd.to_datetime(out["datetime"], utc=True, errors="coerce")
        out = out.dropna(subset=["datetime"])
    for col in NUMERIC_COLS:
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")
    if "datetime" in out.columns:
        out = out.sort_values("datetime").drop_duplicates(subset=["datetime"], keep="last")
    return out.reset_index(drop=True)

def load_symbol_tf(data_dir: Path, symbol: str, tf: str) -> pd.DataFrame:
    fp = data_dir / sanitize_symbol(symbol) / f"{tf}.csv"
    if not fp.exists():
        return pd.DataFrame()
    return _normalize_loaded_df(pd.read_csv(fp))

def load_symbol_timeframes(data_dir: Path, symbol: str, timeframes: list[str]) -> dict[str, pd.DataFrame]:
    return {tf: load_symbol_tf(data_dir, symbol, tf) for tf in timeframes}

def align_symbols_on_timestamps(data: dict[str, pd.DataFrame], col: str = "close") -> pd.DataFrame:
    """
    Create aligned matrix for backtest engine:
    index=datetime, columns=symbol, values=selected col
    """
    series_map = {}
    for sym, df in data.items():
        if df.empty or col not in df.columns:
            continue
        s = df.set_index("datetime")[col].rename(sym)
        series_map[sym] = s
    if not series_map:
        return pd.DataFrame()
    out = pd.concat(series_map.values(), axis=1).sort_index()
    return out

def build_fast_lookup(df: pd.DataFrame) -> dict:
    """
    Convert dataframe rows into dict keyed by timestamp for O(1) lookup in simulation loop.
    """
    if df.empty:
        return {}
    tmp = _normalize_loaded_df(df)
    if tmp.empty or "datetime" not in tmp.columns:
        return {}
    return tmp.set_index("datetime").to_dict(orient="index")
