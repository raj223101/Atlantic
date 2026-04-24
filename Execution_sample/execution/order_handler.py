"""
Execution layer abstractions for backtest and live adapters.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from strategy.contracts import (
    MarketDataBundle,
    OrderIntent,
    PositionSnapshot,
    RiskDecision,
    SignalAction,
    SignalDecision,
)


@dataclass(slots=True)
class ExecutionReport:
    accepted: bool
    order_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class ExecutionGateway(Protocol):
    def submit(self, order: OrderIntent) -> ExecutionReport:
        ...

    def sync_position(self, position: PositionSnapshot) -> None:
        ...


class NullExecutionGateway:
    def submit(self, order: OrderIntent) -> ExecutionReport:
        return ExecutionReport(
            accepted=True,
            order_id="PLACEHOLDER_ORDER",
            metadata={
                "mode": "placeholder",
                "action": order.action.value,
            },
        )

    def sync_position(self, position: PositionSnapshot) -> None:
        del position


class ExecutionLayer:
    """
    Order-handling layer.

    Swap the gateway to connect the same strategy shell to a broker, simulator,
    or replay engine.
    """

    def __init__(self, gateway: ExecutionGateway | None = None) -> None:
        self.gateway = gateway or NullExecutionGateway()

    def build_entry_order(
        self,
        signal: SignalDecision,
        risk: RiskDecision,
        data: MarketDataBundle,
    ) -> OrderIntent:
        return OrderIntent(
            action=signal.action,
            quantity=risk.quantity,
            stop_plan=dict(risk.stop_plan),
            metadata={
                "timeframes": tuple(data.frames),
                "score": signal.score,
                "probability": signal.probability,
            },
        )

    def build_exit_order(
        self,
        position: PositionSnapshot,
        signal: SignalDecision,
        risk: RiskDecision,
        data: MarketDataBundle,
    ) -> OrderIntent:
        return OrderIntent(
            action=SignalAction.EXIT,
            quantity=position.quantity,
            stop_plan=dict(risk.stop_plan),
            metadata={
                "timeframes": tuple(data.frames),
                "exit_source": signal.action.value,
            },
        )

    def handle_entry(
        self,
        signal: SignalDecision,
        risk: RiskDecision,
        data: MarketDataBundle,
    ) -> ExecutionReport | None:
        if not risk.approved:
            return None
        order = self.build_entry_order(signal, risk, data)
        return self.gateway.submit(order)

    def handle_exit(
        self,
        position: PositionSnapshot,
        signal: SignalDecision,
        risk: RiskDecision,
        data: MarketDataBundle,
    ) -> ExecutionReport | None:
        if not risk.approved:
            return None
        order = self.build_exit_order(position, signal, risk, data)
        return self.gateway.submit(order)

    def sync_position(self, position: PositionSnapshot) -> None:
        self.gateway.sync_position(position)
