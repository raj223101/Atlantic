"""
Broker/instrument helpers for Angel paper trading on Indian indices.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import floor
from typing import Dict, Iterable, Optional

from config import (
    ALL_INSTRUMENTS,
    INSTRUMENTS,
    PAPER_TRADE_CAPITAL_RS,
)


@dataclass(frozen=True)
class InstrumentSpec:
    name: str
    token: str
    exchange: str
    exchange_type: int
    broker_symbol: str
    angel_symbol: str
    instrument_type: str
    asset_kind: str
    lot_size: int
    tick_size: float
    strike_step: float
    price_limit: float
    supports_options: bool
    supports_futures: bool
    derivative_root: Optional[str] = None

    @property
    def is_spot_index(self) -> bool:
        return self.asset_kind == "spot_index"

    @property
    def is_derivative(self) -> bool:
        return self.asset_kind in {"future", "option"}


def _build_registry(source: Dict[str, dict]) -> Dict[str, InstrumentSpec]:
    return {
        name: InstrumentSpec(
            name=name,
            token=str(meta["token"]),
            exchange=meta["exchange"],
            exchange_type=int(meta.get("exchange_type", 1)),
            broker_symbol=meta.get("broker_symbol", name),
            angel_symbol=meta.get("angel_symbol", meta.get("symbol", name)),
            instrument_type=meta.get("instrument_type", "INDEX"),
            asset_kind=meta.get("asset_kind", "spot_index"),
            lot_size=int(meta["lot_size"]),
            tick_size=float(meta["tick_size"]),
            strike_step=float(meta.get("strike_step", 0.0)),
            price_limit=float(meta["price_limit"]),
            supports_options=bool(meta.get("supports_options", False)),
            supports_futures=bool(meta.get("supports_futures", False)),
            derivative_root=meta.get("derivative_root"),
        )
        for name, meta in source.items()
    }


INSTRUMENT_REGISTRY = _build_registry(ALL_INSTRUMENTS)
TRADEABLE_INSTRUMENTS = _build_registry(INSTRUMENTS)
TOKEN_TO_SYMBOL = {spec.token: symbol for symbol, spec in INSTRUMENT_REGISTRY.items()}


def get_instrument(symbol: str) -> InstrumentSpec:
    return INSTRUMENT_REGISTRY[symbol]


def get_tradeable_instrument(symbol: str) -> InstrumentSpec:
    return TRADEABLE_INSTRUMENTS[symbol]


def iter_tradeable_instruments() -> Iterable[InstrumentSpec]:
    return TRADEABLE_INSTRUMENTS.values()


def resolve_symbol_from_token(token: str) -> Optional[str]:
    return TOKEN_TO_SYMBOL.get(str(token))


def contract_notional(symbol: str, price: float) -> float:
    spec = get_tradeable_instrument(symbol)
    return float(price) * spec.lot_size


def compute_order_quantity(
    symbol: str,
    price: float,
    capital_rs: float = PAPER_TRADE_CAPITAL_RS,
) -> tuple[int, int]:
    """
    Return `(quantity_units, lots)` using Indian lot-based sizing.

    qty_lots = capital / (lot_size * price)
    quantity_units = floor(qty_lots) * lot_size
    """
    spec = get_tradeable_instrument(symbol)
    notional_per_lot = contract_notional(symbol, price)
    if notional_per_lot <= 0:
        return 0, 0

    lots = floor(float(capital_rs) / notional_per_lot)
    if lots <= 0:
        return 0, 0
    return lots * spec.lot_size, lots


def format_option_symbol(
    root: str,
    expiry_code: str,
    strike: int | float,
    option_type: str,
) -> str:
    """
    Helper for future Angel option migration.

    This is intentionally generic because the current runtime only uses spot
    indices, but keeping the helper centralizes symbol construction when options
    are enabled later.
    """
    suffix = option_type.upper()
    return f"{root}{expiry_code}{int(strike)}{suffix}"
