"""
Generic strategy framework exports.
"""

from strategy.contracts import (
    MarketDataBundle,
    OrderIntent,
    PositionSide,
    PositionSnapshot,
    RiskDecision,
    SignalAction,
    SignalDecision,
    StrategyState,
    TimeframeSnapshot,
)

__all__ = [
    "BaseSignalLayer",
    "GenericStrategy",
    "MarketDataBundle",
    "OrderIntent",
    "PlaceholderScoreComposer",
    "PlaceholderSignalLayer",
    "PositionSide",
    "PositionSnapshot",
    "RiskDecision",
    "ScoreComposer",
    "SignalAction",
    "SignalDecision",
    "StrategyState",
    "TimeframeSnapshot",
]


def __getattr__(name: str):
    if name == "GenericStrategy":
        from strategy.base import GenericStrategy

        return GenericStrategy

    if name in {"BaseSignalLayer", "PlaceholderScoreComposer", "PlaceholderSignalLayer", "ScoreComposer"}:
        from strategy.signal_layer import (
            BaseSignalLayer,
            PlaceholderScoreComposer,
            PlaceholderSignalLayer,
            ScoreComposer,
        )

        exports = {
            "BaseSignalLayer": BaseSignalLayer,
            "PlaceholderScoreComposer": PlaceholderScoreComposer,
            "PlaceholderSignalLayer": PlaceholderSignalLayer,
            "ScoreComposer": ScoreComposer,
        }
        return exports[name]

    raise AttributeError(f"module 'strategy' has no attribute {name!r}")
