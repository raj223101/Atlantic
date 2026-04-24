"""
Reusable strategy orchestration layer.
"""

from __future__ import annotations

from datetime import datetime, timezone

from execution.order_handler import ExecutionLayer, ExecutionReport
from risk.manager import RiskLayer
from strategy.contracts import (
    MarketDataBundle,
    PositionSnapshot,
    RiskDecision,
    SignalDecision,
    StrategyState,
)
from strategy.signal_layer import BaseSignalLayer, PlaceholderSignalLayer


class GenericStrategy:
    """
    Production-ready shell for plugging custom signal, execution, and risk logic
    into the same strategy lifecycle.
    """

    def __init__(
        self,
        *,
        signal_layer: BaseSignalLayer | None = None,
        execution_layer: ExecutionLayer | None = None,
        risk_layer: RiskLayer | None = None,
    ) -> None:
        self.signal_layer = signal_layer or PlaceholderSignalLayer()
        self.execution_layer = execution_layer or ExecutionLayer()
        self.risk_layer = risk_layer or RiskLayer()
        self.state = StrategyState()
        self.initialize()

    def initialize(self) -> StrategyState:
        self.state.initialized_at = datetime.now(timezone.utc)
        self.state.metadata["supports_multi_timeframe"] = True
        self.state.metadata["framework"] = self.__class__.__name__
        return self.state

    def generate_signal(self, data: MarketDataBundle) -> SignalDecision:
        self.state.last_data = data
        signal = self.signal_layer.generate(data)
        self.state.metadata["last_signal"] = signal.action.value
        return signal

    def validate_entry(self, signal: SignalDecision) -> RiskDecision:
        if self.state.last_data is None:
            raise RuntimeError("generate_signal(data) must run before validate_entry(signal).")
        return self.risk_layer.evaluate_entry(
            signal=signal,
            data=self.state.last_data,
            position=self.state.position,
        )

    def validate_exit(self, position: PositionSnapshot, data: MarketDataBundle) -> RiskDecision:
        return self.risk_layer.evaluate_exit(position=position, data=data)

    def process(self, data: MarketDataBundle, position: PositionSnapshot | None = None) -> ExecutionReport | None:
        if position is not None:
            self.state.position = position

        signal = self.generate_signal(data)
        if signal.is_entry():
            risk_decision = self.validate_entry(signal)
            return self.execution_layer.handle_entry(signal, risk_decision, data)

        if signal.is_exit():
            risk_decision = self.validate_exit(self.state.position, data)
            return self.execution_layer.handle_exit(self.state.position, signal, risk_decision, data)

        return None
