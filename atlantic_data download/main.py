import argparse
from pathlib import Path
import sys

import pandas as pd

from config import CFG
from downloader import (
    TwelveDataAPIError,
    TwelveDataAuthError,
    TwelveDataConfigurationError,
    TwelveDataDownloader,
)
from processor import add_optional_features, validate_timeseries
from resampler import generate_synthetic_timeframe
from utils import normalize_path_for_compare, sanitize_symbol, setup_logger, symbol_dir


def parse_args():
    p = argparse.ArgumentParser(description="Twelve Data multi-asset downloader + synthetic TF generator")
    p.add_argument("--symbols", nargs="+", default=["all"], help='Symbol list, comma-separated list, or "all"')
    p.add_argument("--days", type=int, default=CFG.default_days, help="How many days back to download")
    p.add_argument("--force-refresh", action="store_true", help="Ignore local cache and redownload range")
    p.add_argument("--add-features", action="store_true", help="Add returns/rolling_volatility to 1min file")
    p.add_argument("--skip-auth-preflight", action="store_true", help="Skip the startup auth test call")
    p.add_argument("--preflight-only", action="store_true", help="Run interpreter/.env/auth checks and exit")
    return p.parse_args()


def resolve_symbols(raw_symbols):
    expanded = []
    for item in raw_symbols:
        expanded.extend(part.strip() for part in str(item).split(",") if part.strip())

    if len(expanded) == 1 and expanded[0].lower() == "all":
        return CFG.all_symbols()

    lookup = {sanitize_symbol(symbol): symbol for symbol in CFG.all_symbols()}
    resolved = []
    unknown = []
    for symbol in expanded:
        canonical = lookup.get(sanitize_symbol(symbol))
        if canonical:
            resolved.append(canonical)
        else:
            unknown.append(symbol)

    if unknown:
        raise ValueError(f"Unsupported symbol(s): {', '.join(unknown)}")
    return list(dict.fromkeys(resolved))


def save_df(df: pd.DataFrame, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    out = df.copy()
    if "datetime" in out.columns:
        out["datetime"] = pd.to_datetime(out["datetime"], utc=True, errors="coerce")
        out = out.dropna(subset=["datetime"]).sort_values("datetime")
        out = out.drop_duplicates(subset=["datetime"], keep="last")
    out.to_csv(path, index=False)


def run_startup_preflight(logger, skip_auth_preflight: bool = False) -> TwelveDataDownloader:
    expected_python = CFG.expected_venv_python()
    current_python = Path(sys.executable)
    logger.info(f"Project root: {CFG.project_root}")
    logger.info(f"Interpreter: {current_python}")
    logger.info(f"Env file: {CFG.env_file}")

    if not expected_python.exists():
        raise TwelveDataConfigurationError(
            f"Expected local virtualenv interpreter was not found at {expected_python}. "
            "Recreate .venv before running the downloader."
        )

    if normalize_path_for_compare(current_python) != normalize_path_for_compare(expected_python):
        raise TwelveDataConfigurationError(
            f"This project must be run with {expected_python}. Current interpreter: {current_python}. "
            "In VS Code, select the workspace .venv interpreter or use the launch profile in .vscode/launch.json."
        )

    if not CFG.env_file.exists():
        raise TwelveDataConfigurationError(
            f"Missing env file at {CFG.env_file}. Create it with {CFG.api_key_env_var}=<rotated_key>."
        )

    if not CFG.load_environment():
        raise TwelveDataConfigurationError(
            f"{CFG.api_key_env_var} is empty. Update {CFG.env_file} with a valid rotated Twelve Data key."
        )

    downloader = TwelveDataDownloader(logger)
    if not skip_auth_preflight:
        downloader.verify_api_access()
    return downloader


def run():
    args = parse_args()
    logger = setup_logger()
    CFG.data_dir.mkdir(parents=True, exist_ok=True)

    try:
        downloader = run_startup_preflight(logger, skip_auth_preflight=args.skip_auth_preflight)
        if args.preflight_only:
            logger.info("Preflight checks passed. Exiting because --preflight-only was set.")
            return
        symbols = resolve_symbols(args.symbols)
    except (TwelveDataAPIError, TwelveDataAuthError, TwelveDataConfigurationError, ValueError) as exc:
        logger.error(str(exc))
        raise SystemExit(2) from exc

    total_symbols = len(symbols)
    for index, symbol in enumerate(symbols, start=1):
        try:
            logger.info(f"[{index}/{total_symbols}] Processing {symbol}")
            df_1m = downloader.download_symbol(symbol=symbol, days=args.days, force_refresh=args.force_refresh)
            if df_1m.empty:
                logger.warning(f"{symbol}: empty 1min data after download")
                continue

            if args.add_features:
                df_1m = add_optional_features(df_1m)

            sdir = symbol_dir(CFG.data_dir, symbol)
            save_df(df_1m, sdir / "1min.csv")

            checks = validate_timeseries(df_1m[["datetime", "open", "high", "low", "close", "volume"]], freq="1min")
            logger.info(f"{symbol} validation: {checks}")

            base = df_1m[["datetime", "open", "high", "low", "close", "volume"]].copy()
            for tf in CFG.synthetic_timeframes:
                syn = generate_synthetic_timeframe(base, tf)
                save_df(syn, sdir / f"{tf}.csv")
                logger.info(f"{symbol} synthetic {tf}: rows={len(syn)}")

        except Exception as e:
            logger.exception(f"Failed symbol {symbol}: {e}")


if __name__ == "__main__":
    run()
