from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from resampler import (
    TIMEFRAME_RULES,
    build_base_timeframe,
    ensure_continuous_seconds,
    resample_from_base,
    to_storage_frame,
)
from utils import DEFAULT_TIMEFRAMES, ensure_directory, load_instrument_config, resolve_symbols


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Process Dukascopy tick CSV files into continuous multi-timeframe datasets."
    )
    parser.add_argument("--symbols", default="all", help="all or comma-separated symbols/groups")
    parser.add_argument("--raw-dir", default="data/raw", help="Root folder of raw tick CSV files")
    parser.add_argument(
        "--processed-dir",
        default="data/processed",
        help="Root folder for processed candle outputs",
    )
    parser.add_argument("--log-dir", default="logs/processing", help="Folder for processing logs")
    parser.add_argument(
        "--timeframes",
        default=",".join(DEFAULT_TIMEFRAMES),
        help="Comma-separated list of timeframes (1s,5s,10s,15s,30s,1min)",
    )
    parser.add_argument(
        "--output-format",
        default="csv",
        choices=["csv", "parquet", "both"],
        help="Persist outputs as csv, parquet, or both",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=1_000_000,
        help="CSV chunk size used during raw tick parsing",
    )
    parser.add_argument(
        "--max-spread-ratio",
        type=float,
        default=0.10,
        help="Filter ticks whose spread exceeds this fraction of mid price",
    )
    parser.add_argument(
        "--continuous",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Forward-fill 1-second gaps to create a continuous timeline",
    )
    parser.add_argument("--start", help="Optional YYYY-MM-DD lower file filter")
    parser.add_argument("--end", help="Optional YYYY-MM-DD upper file filter")
    return parser.parse_args()


def utc_now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def parse_date_token(value: str | None) -> str | None:
    if not value:
        return None
    datetime.strptime(value, "%Y-%m-%d")
    return value


def list_symbol_files(symbol_dir: Path, start: str | None, end: str | None) -> list[Path]:
    files: list[Path] = []
    for file_path in sorted(symbol_dir.glob("*.csv")):
        day = file_path.stem
        if start and day < start:
            continue
        if end and day > end:
            continue
        files.append(file_path)
    return files


def write_log(log_file: Path, message: str) -> None:
    line = f"{utc_now()} {message}\n"
    with log_file.open("a", encoding="utf8") as handle:
        handle.write(line)
    print(line, end="")


def persist_frame(frame, symbol_dir: Path, timeframe: str, output_format: str) -> dict[str, str]:
    storage_frame = to_storage_frame(frame)
    outputs: dict[str, str] = {}

    if output_format in {"csv", "both"}:
        csv_path = symbol_dir / f"{timeframe}.csv"
        storage_frame.to_csv(csv_path, index=False, float_format="%.10f")
        outputs["csv"] = str(csv_path)

    if output_format in {"parquet", "both"}:
        parquet_path = symbol_dir / f"{timeframe}.parquet"
        storage_frame.to_parquet(parquet_path, index=False)
        outputs["parquet"] = str(parquet_path)

    return outputs


def main() -> None:
    args = parse_args()
    raw_root = Path(args.raw_dir)
    processed_root = ensure_directory(args.processed_dir)
    log_root = ensure_directory(args.log_dir)

    requested_timeframes = [item.strip() for item in args.timeframes.split(",") if item.strip()]
    invalid = [item for item in requested_timeframes if item not in TIMEFRAME_RULES]
    if invalid:
        raise ValueError(f"Unsupported timeframes: {invalid}")

    if "1s" not in requested_timeframes:
        requested_timeframes = ["1s", *requested_timeframes]

    start = parse_date_token(args.start)
    end = parse_date_token(args.end)
    if start and end and start > end:
        raise ValueError("--start cannot be later than --end")

    config = load_instrument_config()
    symbols = resolve_symbols(args.symbols, config=config)

    run_stamp = datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    log_file = log_root / f"process-{run_stamp}.log"
    summary = {
        "startedAt": utc_now(),
        "symbols": [item["symbol"] for item in symbols],
        "timeframes": requested_timeframes,
        "outputFormat": args.output_format,
        "continuous": args.continuous,
        "chunkSize": args.chunk_size,
        "maxSpreadRatio": args.max_spread_ratio,
        "results": {},
    }

    for entry in symbols:
        symbol = entry["symbol"]
        symbol_dir = raw_root / symbol
        files = list_symbol_files(symbol_dir, start=start, end=end)
        if not files:
            write_log(log_file, f"[WARN] No raw CSV files found for {symbol} in {symbol_dir}")
            summary["results"][symbol] = {"status": "missing_raw_files"}
            continue

        write_log(log_file, f"[INFO] Processing {symbol} from {len(files)} daily raw file(s)")
        base_frame, stats = build_base_timeframe(
            files=files,
            chunk_size=args.chunk_size,
            max_spread_ratio=args.max_spread_ratio,
        )
        if base_frame.empty:
            write_log(log_file, f"[WARN] {symbol} produced no valid candles after cleaning")
            summary["results"][symbol] = {
                "status": "empty_after_cleaning",
                "stats": stats.to_dict(),
            }
            continue

        if args.continuous:
            base_frame = ensure_continuous_seconds(base_frame)

        output_dir = ensure_directory(processed_root / symbol)
        symbol_summary = {
            "status": "ok",
            "stats": stats.to_dict(),
            "outputs": {},
        }

        for timeframe in requested_timeframes:
            frame = base_frame if timeframe == "1s" else resample_from_base(base_frame, timeframe)
            outputs = persist_frame(frame, output_dir, timeframe, args.output_format)
            symbol_summary["outputs"][timeframe] = {
                "rows": int(len(frame)),
                "paths": outputs,
            }
            write_log(
                log_file,
                f"[INFO] {symbol} {timeframe} -> {len(frame)} row(s) written to {outputs}",
            )

        manifest_path = output_dir / "manifest.json"
        manifest_payload = {
            "generatedAt": utc_now(),
            "symbol": symbol,
            "instrumentId": entry["instrumentId"],
            "assetClass": entry["assetClass"],
            "continuous": args.continuous,
            "timeframes": requested_timeframes,
            "stats": stats.to_dict(),
            "rawFiles": [str(file_path) for file_path in files],
        }
        manifest_path.write_text(f"{json.dumps(manifest_payload, indent=2)}\n", encoding="utf8")
        symbol_summary["manifest"] = str(manifest_path)
        summary["results"][symbol] = symbol_summary

    summary["finishedAt"] = utc_now()
    summary_path = log_root / f"process-{run_stamp}.summary.json"
    summary_path.write_text(f"{json.dumps(summary, indent=2)}\n", encoding="utf8")
    write_log(log_file, f"[INFO] Processing completed. Summary written to {summary_path}")


if __name__ == "__main__":
    main()

