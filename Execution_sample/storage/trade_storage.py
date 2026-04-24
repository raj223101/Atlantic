"""
Per-strategy detailed trade persistence.
"""

from __future__ import annotations

import csv
import os
import threading
from datetime import datetime
from typing import Dict, List

from core.logger import log
from storage.day_paths import trades_dir


class TradeStorage:
    _HEADERS = [
        "Entry_Date",
        "Entry_Time",
        "Exit_Date",
        "Exit_Time",
        "Underlying_Symbol",
        "Strategy_Direction",
        "Execution_Mode",
        "Entry_Label",
        "Exit_Label",
        "Underlying_Entry_Price",
        "Underlying_Exit_Price",
        "Option_Symbol",
        "Option_Strike",
        "Option_Type",
        "Option_Bucket",
        "Option_Entry_Price",
        "Option_Exit_Price",
        "Entry_Fair_Value",
        "Exit_Fair_Value",
        "Entry_Limit_Price",
        "Exit_Limit_Price",
        "Entry_Spread_Pct",
        "Exit_Spread_Pct",
        "Entry_Quote_Source",
        "Exit_Quote_Source",
        "Entry_Pricing_Mode",
        "Exit_Pricing_Mode",
        "Entry_Repriced",
        "Exit_Repriced",
        "Entry_Slippage_vs_Fair",
        "Exit_Slippage_vs_Fair",
        "Qty",
        "PnL",
        "Trade_ID",
    ]
    _lock = threading.RLock()

    @staticmethod
    def get_trade_log_path(strategy_name: str, value=None) -> str:
        return os.path.join(trades_dir(value), f"trades_{strategy_name}.csv")

    @classmethod
    def ensure_schema(cls, strategy_name: str, value=None) -> None:
        path = cls.get_trade_log_path(strategy_name, value)
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)

        if not os.path.isfile(path):
            with open(path, "w", newline="") as handle:
                csv.writer(handle).writerow(cls._HEADERS)
            return

        try:
            with open(path, newline="") as handle:
                existing = next(csv.reader(handle), [])
        except Exception:
            existing = []

        if existing == cls._HEADERS:
            return

        backup = f"{path}.legacy_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        os.replace(path, backup)
        with open(path, "w", newline="") as handle:
            csv.writer(handle).writerow(cls._HEADERS)

    @classmethod
    def write_trade(cls, strategy_name: str, trade: Dict) -> None:
        with cls._lock:
            try:
                entry_ts = cls._coerce_dt(trade.get("entry_ts"))
                exit_ts = cls._coerce_dt(trade.get("exit_ts"))
                cls.ensure_schema(strategy_name, exit_ts)
                path = cls.get_trade_log_path(strategy_name, exit_ts)
                with open(path, "a", newline="") as handle:
                    writer = csv.writer(handle)
                    writer.writerow(
                        [
                            entry_ts.strftime("%Y-%m-%d"),
                            entry_ts.strftime("%H:%M:%S"),
                            exit_ts.strftime("%Y-%m-%d"),
                            exit_ts.strftime("%H:%M:%S"),
                            trade.get("underlying_symbol", trade.get("symbol", "")),
                            trade.get("strategy_direction", trade.get("side", "")),
                            trade.get("execution_mode", ""),
                            trade.get("entry_label", ""),
                            trade.get("exit_label", ""),
                            round(float(trade.get("underlying_entry_price", 0.0)), 2),
                            round(float(trade.get("underlying_exit_price", 0.0)), 2),
                            trade.get("option_symbol", ""),
                            round(float(trade.get("option_strike", 0.0)), 2),
                            trade.get("option_type", ""),
                            trade.get("option_bucket", ""),
                            round(float(trade.get("option_entry_price", trade.get("entry_px", trade.get("entry_price", 0.0)))), 2),
                            round(float(trade.get("option_exit_price", trade.get("exit_px", trade.get("exit_price", 0.0)))), 2),
                            round(float(trade.get("entry_fair_value", 0.0)), 2),
                            round(float(trade.get("exit_fair_value", 0.0)), 2),
                            round(float(trade.get("entry_limit_price", 0.0)), 2),
                            round(float(trade.get("exit_limit_price", 0.0)), 2),
                            round(float(trade.get("entry_spread_pct", 0.0)), 6),
                            round(float(trade.get("exit_spread_pct", 0.0)), 6),
                            trade.get("entry_quote_source", ""),
                            trade.get("exit_quote_source", ""),
                            trade.get("entry_pricing_mode", ""),
                            trade.get("exit_pricing_mode", ""),
                            str(bool(trade.get("entry_repriced", False))),
                            str(bool(trade.get("exit_repriced", False))),
                            round(float(trade.get("entry_slippage_vs_fair", 0.0)), 4),
                            round(float(trade.get("exit_slippage_vs_fair", 0.0)), 4),
                            int(trade.get("qty", 0)),
                            round(float(trade.get("pnl", 0.0)), 2),
                            trade.get("trade_id", ""),
                        ]
                    )
            except Exception as exc:
                log.error(
                    "[TradeStorage] failed to write trade | strategy=%s error=%s",
                    strategy_name,
                    exc,
                    exc_info=True,
                )

    @classmethod
    def get_trades(cls, strategy_name: str) -> List[Dict]:
        path = cls.get_trade_log_path(strategy_name)
        if not os.path.isfile(path):
            return []

        with cls._lock:
            try:
                with open(path, newline="") as handle:
                    return list(csv.DictReader(handle))
            except Exception as exc:
                log.error("[TradeStorage] failed to read trades | strategy=%s error=%s", strategy_name, exc)
                return []

    @classmethod
    def calculate_stats(cls, strategy_name: str) -> Dict:
        trades = cls.get_trades(strategy_name)
        if not trades:
            return {
                "total_trades": 0,
                "wins": 0,
                "losses": 0,
                "win_rate": 0.0,
                "gross_profit": 0.0,
                "gross_loss": 0.0,
                "net_pnl": 0.0,
            }

        wins = sum(1 for trade in trades if float(trade.get("PnL", 0.0)) > 0)
        losses = sum(1 for trade in trades if float(trade.get("PnL", 0.0)) < 0)
        gross_profit = sum(float(trade.get("PnL", 0.0)) for trade in trades if float(trade.get("PnL", 0.0)) > 0)
        gross_loss = sum(float(trade.get("PnL", 0.0)) for trade in trades if float(trade.get("PnL", 0.0)) < 0)
        total = len(trades)
        return {
            "total_trades": total,
            "wins": wins,
            "losses": losses,
            "win_rate": (wins / total * 100.0) if total else 0.0,
            "gross_profit": gross_profit,
            "gross_loss": gross_loss,
            "net_pnl": gross_profit + gross_loss,
        }

    @staticmethod
    def _coerce_dt(value) -> datetime:
        if isinstance(value, datetime):
            return value
        if value is None:
            return datetime.now()
        if isinstance(value, str):
            return datetime.fromisoformat(value)
        return datetime.now()
