from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime
from pathlib import Path

from candle_engine.candle_builder import CandleBuilder
from config import ACTIVE_CANDLE_SYMBOLS, ALL_INSTRUMENTS, LOW_LATENCY_BENCHMARK_OUTPUT
from core.logger import log
from execution.signal_router import signal_router
from execution.strategy_definitions import required_timeframes
from monitoring.performance_monitor import performance_monitor
from runtime.engine import LowLatencyTradingEngine


def _parse_time(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d %H:%M:%S.%f")


def run_benchmark(csv_path: Path, symbol: str) -> dict:
    CandleBuilder.initialize(ALL_INSTRUMENTS, required_timeframes())
    for active_symbol in ACTIVE_CANDLE_SYMBOLS:
        CandleBuilder.mark_history_loaded(active_symbol)
    signal_router.initialize()

    prices = {name: 0.0 for name in ALL_INSTRUMENTS}
    engine = LowLatencyTradingEngine(signal_router=signal_router, last_price_store=prices)
    engine.start()

    rows = 0
    with csv_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            if row.get("Symbol") != symbol:
                continue
            rows += 1
            ltp = float(row.get("LTP", 0) or 0)
            ts = _parse_time(row["Time"])
            raw = {
                "volume": int(float(row.get("Volume", 0) or 0)),
                "token": row.get("Token", ""),
                "exchange_type": int(float(row.get("Exchange_Type", 0) or 0)),
                "angel_symbol": row.get("Angel_Symbol", ""),
                "subscription_mode": int(float(row.get("Subscription_Mode", 0) or 0)),
                "sequence_number": int(float(row.get("Sequence_Number", 0) or 0)),
                "last_traded_quantity": int(float(row.get("Last_Traded_Qty", 0) or 0)),
                "average_traded_price": float(row.get("Average_Traded_Price", 0) or 0),
                "total_buy_quantity": float(row.get("Total_Buy_Qty", 0) or 0),
                "total_sell_quantity": float(row.get("Total_Sell_Qty", 0) or 0),
                "open_interest": int(float(row.get("Open_Interest", 0) or 0)),
                "open_interest_change_percentage": float(row.get("OI_Change_Pct", 0) or 0),
                "best_bid_price": float(row.get("Best_Bid_Price", 0) or 0),
                "best_bid_qty": int(float(row.get("Best_Bid_Qty", 0) or 0)),
                "best_ask_price": float(row.get("Best_Ask_Price", 0) or 0),
                "best_ask_qty": int(float(row.get("Best_Ask_Qty", 0) or 0)),
                "spread": float(row.get("Spread", 0) or 0),
                "open_price_of_the_day": float(row.get("Day_Open", 0) or 0),
                "high_price_of_the_day": float(row.get("Day_High", 0) or 0),
                "low_price_of_the_day": float(row.get("Day_Low", 0) or 0),
                "closed_price": float(row.get("Prev_Close", 0) or 0),
                "upper_circuit_limit": float(row.get("Upper_Circuit", 0) or 0),
                "lower_circuit_limit": float(row.get("Lower_Circuit", 0) or 0),
                "last_traded_timestamp": int(float(row.get("Last_Traded_Timestamp", 0) or 0)),
            }
            engine.enqueue(symbol, ltp, ts, raw)

    engine.wait_for_idle(timeout_s=30.0)
    result = {
        "rows_processed": rows,
        "engine": engine.stats(),
        "monitor": performance_monitor.summary(),
    }
    engine.stop()
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Replay benchmark for the low-latency engine.")
    parser.add_argument("--csv", required=True, help="Absolute or relative path to a tick CSV file.")
    parser.add_argument("--symbol", required=True, help="Symbol to replay, e.g. NIFTY.")
    args = parser.parse_args()

    csv_path = Path(args.csv).expanduser().resolve()
    result = run_benchmark(csv_path, args.symbol)
    output_path = Path(LOW_LATENCY_BENCHMARK_OUTPUT).resolve()
    output_path.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    log.info("[LowLatencyBenchmark] completed | output=%s", output_path)
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
