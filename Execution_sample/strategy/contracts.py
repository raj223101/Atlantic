"""
Shared contracts for the generic strategy framework.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Mapping, MutableMapping


class SignalAction(str, Enum):
    HOLD = "HOLD"
    BUY = "BUY"
    SELL = "SELL"
    EXIT = "EXIT"


class PositionSide(str, Enum):
    FLAT = "FLAT"
    LONG = "LONG"
    SHORT = "SHORT"


@dataclass(slots=True, frozen=True)
class TimeframeSnapshot:
    label: str
    payload: Mapping[str, Any]
    timestamp: datetime | None = None


@dataclass(slots=True)
class MarketDataBundle:
    frames: Mapping[str, TimeframeSnapshot]
    context: MutableMapping[str, Any] = field(default_factory=dict)

    def frame(self, label: str) -> TimeframeSnapshot | None:
        return self.frames.get(label)


@dataclass(slots=True)
class SignalDecision:
    action: SignalAction
    score: float
    probability: float
    components: Mapping[str, Any] = field(default_factory=dict)
    metadata: MutableMapping[str, Any] = field(default_factory=dict)

    def is_entry(self) -> bool:
        return self.action in {SignalAction.BUY, SignalAction.SELL}

    def is_exit(self) -> bool:
        return self.action == SignalAction.EXIT


@dataclass(slots=True)
class PositionSnapshot:
    side: PositionSide = PositionSide.FLAT
    quantity: float | None = None
    entry_reference: str | None = None
    metadata: MutableMapping[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class RiskDecision:
    approved: bool
    quantity: float | None = None
    stop_plan: Mapping[str, Any] = field(default_factory=dict)
    metadata: MutableMapping[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class OrderIntent:
    action: SignalAction
    quantity: float | None = None
    stop_plan: Mapping[str, Any] = field(default_factory=dict)
    metadata: MutableMapping[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class StrategyState:
    initialized_at: datetime | None = None
    position: PositionSnapshot = field(default_factory=PositionSnapshot)
    last_data: MarketDataBundle | None = None
    metadata: MutableMapping[str, Any] = field(default_factory=dict)
