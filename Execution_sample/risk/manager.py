"""
Risk-layer abstractions for stop planning and position sizing.
"""

from __future__ import annotations

from typing import Any, Mapping, Protocol

from strategy.contracts import (
    MarketDataBundle,
    PositionSide,
    PositionSnapshot,
    RiskDecision,
    SignalAction,
    SignalDecision,
)


class PositionSizer(Protocol):
    def size(self, signal: SignalDecision, data: MarketDataBundle, position: PositionSnapshot) -> float | None:
        ...


class StopPlanBuilder(Protocol):
    def entry_plan(
        self,
        signal: SignalDecision,
        data: MarketDataBundle,
        position: PositionSnapshot,
    ) -> Mapping[str, Any]:
        ...

    def exit_plan(self, position: PositionSnapshot, data: MarketDataBundle) -> Mapping[str, Any]:
        ...


class EntryPolicy(Protocol):
    def allow(self, signal: SignalDecision, data: MarketDataBundle, position: PositionSnapshot) -> bool:
        ...


class ExitPolicy(Protocol):
    def allow(self, position: PositionSnapshot, data: MarketDataBundle) -> bool:
        ...


class PlaceholderPositionSizer:
    def size(self, signal: SignalDecision, data: MarketDataBundle, position: PositionSnapshot) -> float | None:
        del data
        del position
        return signal.metadata.get("size_hint")


class PlaceholderStopPlanBuilder:
    def entry_plan(
        self,
        signal: SignalDecision,
        data: MarketDataBundle,
        position: PositionSnapshot,
    ) -> Mapping[str, Any]:
        del signal
        del data
        del position
        return {
            "stop_loss": "Attach custom stop-loss or trailing logic here.",
            "hedge": "Attach portfolio-level hedge or exposure rules here.",
        }

    def exit_plan(self, position: PositionSnapshot, data: MarketDataBundle) -> Mapping[str, Any]:
        del position
        del data
        return {
            "exit_risk": "Attach custom exit-risk annotations here.",
        }


class FlatOnlyEntryPolicy:
    def allow(self, signal: SignalDecision, data: MarketDataBundle, position: PositionSnapshot) -> bool:
        del data
        return signal.action in {SignalAction.BUY, SignalAction.SELL} and position.side == PositionSide.FLAT


class ActivePositionExitPolicy:
    def allow(self, position: PositionSnapshot, data: MarketDataBundle) -> bool:
        del data
        return position.side != PositionSide.FLAT


class RiskLayer:
    """
    Generic risk layer for SL planning, sizing, and entry/exit approval.
    """

    def __init__(
        self,
        *,
        position_sizer: PositionSizer | None = None,
        stop_plan_builder: StopPlanBuilder | None = None,
        entry_policy: EntryPolicy | None = None,
        exit_policy: ExitPolicy | None = None,
    ) -> None:
        self.position_sizer = position_sizer or PlaceholderPositionSizer()
        self.stop_plan_builder = stop_plan_builder or PlaceholderStopPlanBuilder()
        self.entry_policy = entry_policy or FlatOnlyEntryPolicy()
        self.exit_policy = exit_policy or ActivePositionExitPolicy()

    def evaluate_entry(
        self,
        *,
        signal: SignalDecision,
        data: MarketDataBundle,
        position: PositionSnapshot,
    ) -> RiskDecision:
        approved = self.entry_policy.allow(signal, data, position)
        return RiskDecision(
            approved=approved,
            quantity=self.position_sizer.size(signal, data, position),
            stop_plan=self.stop_plan_builder.entry_plan(signal, data, position),
            metadata={"layer": self.__class__.__name__},
        )

    def evaluate_exit(self, *, position: PositionSnapshot, data: MarketDataBundle) -> RiskDecision:
        approved = self.exit_policy.allow(position, data)
        return RiskDecision(
            approved=approved,
            quantity=position.quantity,
            stop_plan=self.stop_plan_builder.exit_plan(position, data),
            metadata={"layer": self.__class__.__name__},
        )
