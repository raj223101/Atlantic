"""
Per-strategy position tracking with rich option metadata.
"""

from __future__ import annotations

import threading
from datetime import datetime
from typing import Dict, Optional

from core.logger import log


class StrategyPosition:
    def __init__(
        self,
        symbol: str,
        side: str,
        entry_price: float,
        qty: int,
        entry_ts: datetime,
        entry_reason: str,
        pricing_model: str = "linear",
        metadata: Optional[Dict] = None,
    ):
        self.symbol = symbol
        self.side = side
        self.entry_price = entry_price
        self.qty = qty
        self.entry_ts = entry_ts
        self.entry_reason = entry_reason
        self.pricing_model = pricing_model
        self.metadata: Dict = dict(metadata or {})

        self.current_price = entry_price
        self.mfe = 0.0
        self.mae = 0.0
        self.last_update_ts = entry_ts

        self.metadata.setdefault("underlying_entry_price", self.metadata.get("underlying_price", 0.0))
        self.metadata.setdefault("underlying_last_price", self.metadata.get("underlying_price", 0.0))
        self.metadata.setdefault("option_entry_price", entry_price)
        self.metadata.setdefault("option_last_price", entry_price)

    def update_mark_to_market(
        self,
        price: float,
        ts: datetime,
        context: Optional[Dict] = None,
    ) -> None:
        self.current_price = price
        self.last_update_ts = ts
        context = context or {}

        underlying_price = context.get("underlying_price")
        if underlying_price is not None:
            self.metadata["underlying_last_price"] = underlying_price

        self.metadata["option_last_price"] = price

        for key, value in context.items():
            if key == "underlying_price":
                continue
            self.metadata[key] = value

    def _calc_pnl(self, price: float) -> float:
        if self.pricing_model == "long_option":
            return (price - self.entry_price) * self.qty
        if self.side == "LONG":
            return (price - self.entry_price) * self.qty
        return (self.entry_price - price) * self.qty

    @property
    def unrealized_pnl(self) -> float:
        return self._calc_pnl(self.current_price)

    @property
    def unrealized_pnl_pct(self) -> float:
        if self.entry_price == 0:
            return 0.0
        return (self.unrealized_pnl / (self.entry_price * self.qty)) * 100.0

    def to_dict(self) -> Dict:
        return {
            "symbol": self.symbol,
            "side": self.side,
            "entry_price": self.entry_price,
            "qty": self.qty,
            "entry_ts": self.entry_ts,
            "entry_reason": self.entry_reason,
            "current_price": self.current_price,
            "mfe": self.mfe,
            "mae": self.mae,
            "unrealized_pnl": self.unrealized_pnl,
            "unrealized_pnl_pct": self.unrealized_pnl_pct,
            "pricing_model": self.pricing_model,
            "metadata": dict(self.metadata),
        }


class StrategyPositionManager:
    def __init__(self, strategy_name: str):
        self.strategy_name = strategy_name
        self._positions: Dict[str, Optional[StrategyPosition]] = {}
        self._closed_positions: list = []
        self._lock = threading.Lock()

    def initialize_symbol(self, symbol: str) -> None:
        with self._lock:
            if symbol not in self._positions:
                self._positions[symbol] = None

    def open_position(
        self,
        symbol: str,
        side: str,
        entry_price: float,
        qty: int,
        entry_ts: datetime,
        entry_reason: str,
        pricing_model: str = "linear",
        metadata: Optional[Dict] = None,
    ) -> Optional[StrategyPosition]:
        with self._lock:
            if symbol not in self._positions:
                log.warning("[StrategyPositionManager] %s does not track %s", self.strategy_name, symbol)
                return None
            if self._positions.get(symbol) is not None:
                log.warning("[StrategyPositionManager] %s already has position in %s", self.strategy_name, symbol)
                return None

            pos = StrategyPosition(
                symbol=symbol,
                side=side,
                entry_price=entry_price,
                qty=qty,
                entry_ts=entry_ts,
                entry_reason=entry_reason,
                pricing_model=pricing_model,
                metadata=metadata,
            )
            self._positions[symbol] = pos
            return pos

    def close_position(
        self,
        symbol: str,
        exit_price: float,
        exit_ts: datetime,
        exit_reason: str,
    ) -> Optional[Dict]:
        with self._lock:
            if symbol not in self._positions:
                return None
            pos = self._positions.get(symbol)
            if pos is None:
                return None

            pnl = pos._calc_pnl(exit_price)
            trade = {
                "symbol": symbol,
                "side": pos.side,
                "entry_price": pos.entry_price,
                "exit_price": exit_price,
                "qty": pos.qty,
                "entry_ts": pos.entry_ts,
                "exit_ts": exit_ts,
                "entry_reason": pos.entry_reason,
                "exit_reason": exit_reason,
                "pnl": pnl,
                "mfe": pos.mfe,
                "mae": pos.mae,
                "pricing_model": pos.pricing_model,
                **dict(pos.metadata),
            }

            self._closed_positions.append(trade)
            self._positions[symbol] = None
            return trade

    def update_mark_to_market(
        self,
        symbol: str,
        price: float,
        ts: datetime,
        context: Optional[Dict] = None,
    ) -> None:
        with self._lock:
            if symbol not in self._positions:
                return
            pos = self._positions.get(symbol)
            if pos is not None:
                pos.update_mark_to_market(price, ts, context=context)

    def tracks_symbol(self, symbol: str) -> bool:
        with self._lock:
            return symbol in self._positions

    def has_position(self, symbol: str) -> bool:
        with self._lock:
            return self._positions.get(symbol) is not None

    def get_position(self, symbol: str) -> Optional[Dict]:
        with self._lock:
            pos = self._positions.get(symbol)
            return pos.to_dict() if pos else None

    def get_all_positions(self) -> Dict[str, Dict]:
        with self._lock:
            return {
                sym: pos.to_dict()
                for sym, pos in self._positions.items()
                if pos is not None
            }

    def get_closed_trades(self) -> list:
        with self._lock:
            return list(self._closed_positions)

    def reset(self, symbol: str = None) -> None:
        with self._lock:
            if symbol is None:
                self._positions.clear()
                self._closed_positions.clear()
            else:
                self._positions[symbol] = None

    def summary(self) -> Dict:
        with self._lock:
            open_positions = {
                sym: pos.to_dict()
                for sym, pos in self._positions.items()
                if pos is not None
            }
            total_unrealized = sum(pos["unrealized_pnl"] for pos in open_positions.values())

        return {
            "strategy_name": self.strategy_name,
            "open_positions": len(open_positions),
            "closed_trades": len(self._closed_positions),
            "total_unrealized_pnl": total_unrealized,
            "positions": open_positions,
        }
