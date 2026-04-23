import pandas as pd
import numpy as np

REQUIRED_COLS = ["datetime", "open", "high", "low", "close", "volume"]

def json_to_df(values: list) -> pd.DataFrame:
    """
    Convert Twelve Data 'values' payload into clean 1-min OHLCV dataframe in UTC.
    """
    if not values:
        return pd.DataFrame(columns=REQUIRED_COLS)

    df = pd.DataFrame(values).copy()
    for c in REQUIRED_COLS:
        if c not in df.columns:
            df[c] = np.nan

    df["datetime"] = pd.to_datetime(df["datetime"], utc=True, errors="coerce")
    for c in ["open", "high", "low", "close", "volume"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")

    df = df.dropna(subset=["datetime", "open", "high", "low", "close"])
    df = df.sort_values("datetime").drop_duplicates(subset=["datetime"], keep="last")
    df = df.reset_index(drop=True)
    return df[REQUIRED_COLS]

def add_optional_features(df: pd.DataFrame, vol_window: int = 30) -> pd.DataFrame:
    out = df.copy()
    out["returns"] = out["close"].pct_change()
    out["rolling_volatility"] = out["returns"].rolling(vol_window).std() * np.sqrt(vol_window)
    return out

def validate_timeseries(df: pd.DataFrame, freq: str = "1min") -> dict:
    issues = {
        "duplicate_rows": int(df.duplicated(subset=["datetime"]).sum()),
        "missing_timestamps": 0,
        "continuity_gaps": []
    }
    if df.empty:
        return issues

    ordered = df[["datetime"]].dropna().sort_values("datetime")
    if ordered.empty:
        return issues

    expected_step = pd.to_timedelta(freq)
    dti = pd.DatetimeIndex(ordered["datetime"])
    gaps = dti.to_series().diff().dropna()
    discontinuities = gaps[gaps > expected_step]

    if not discontinuities.empty:
        missing_total = 0
        continuity_gaps = []
        for ts, gap in discontinuities.iloc[:50].items():
            missing_bars = int((gap / expected_step) - 1)
            missing_total += missing_bars
            continuity_gaps.append({
                "previous": (ts - gap).isoformat(),
                "current": ts.isoformat(),
                "missing_bars": missing_bars,
            })
        remaining = discontinuities.iloc[50:]
        if not remaining.empty:
            missing_total += int(sum((gap / expected_step) - 1 for gap in remaining))
        issues["missing_timestamps"] = missing_total
        issues["continuity_gaps"] = continuity_gaps
    return issues
