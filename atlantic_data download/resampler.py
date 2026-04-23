import pandas as pd
import numpy as np

SYNTHETIC_COLS = ["datetime", "open", "high", "low", "close", "volume", "synthetic_timeframe"]

def _synthetic_from_1min_row(row: pd.Series, sec: int) -> list[dict]:
    """
    Interpolation-based synthetic OHLCV generation inside one minute candle.
    """
    start_ts = row["datetime"]
    steps = 60 // sec
    if steps < 1:
        return []

    o, h, l, c, v = row["open"], row["high"], row["low"], row["close"], row["volume"]
    close_path = np.linspace(o, c, steps + 1)  # step endpoints
    vol_per = (v / steps) if pd.notna(v) else np.nan

    chunks = []
    for i in range(steps):
        t0 = start_ts + pd.Timedelta(seconds=i * sec)
        so = float(close_path[i])
        sc = float(close_path[i + 1])

        # Put wick extremes proportionally in segment if segment spans midpoint-ish;
        # this is heuristic but better than equal split.
        seg_high = max(so, sc)
        seg_low = min(so, sc)

        # small chance to inject minute high/low in plausible segments
        if i == steps // 3:
            seg_high = max(seg_high, float(h))
        if i == (2 * steps) // 3:
            seg_low = min(seg_low, float(l))

        chunks.append({
            "datetime": t0,
            "open": so,
            "high": seg_high,
            "low": seg_low,
            "close": sc,
            "volume": float(vol_per) if pd.notna(vol_per) else np.nan,
            "synthetic_timeframe": True
        })
    return chunks

def generate_synthetic_timeframe(df_1m: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    sec = int(timeframe.replace("s", ""))
    if 60 % sec != 0:
        raise ValueError(f"Unsupported timeframe {timeframe}; must divide 60.")

    rows = []
    for _, row in df_1m.iterrows():
        rows.extend(_synthetic_from_1min_row(row, sec))

    out = pd.DataFrame(rows)
    if out.empty:
        return pd.DataFrame(columns=SYNTHETIC_COLS)

    out["datetime"] = pd.to_datetime(out["datetime"], utc=True, errors="coerce")
    out = out.sort_values("datetime").drop_duplicates(subset=["datetime"], keep="last")
    out = out.reset_index(drop=True)
    return out[SYNTHETIC_COLS]
