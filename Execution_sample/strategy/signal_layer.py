"""
Pure signal-layer primitives for the generic strategy framework.
"""

from __future__ import annotations

import math
from typing import Any, Mapping, Protocol

from strategy.contracts import MarketDataBundle, SignalAction, SignalDecision


class ScoreComposer(Protocol):
    def __call__(self, components: Mapping[str, Any], data: MarketDataBundle) -> float:
        ...


class PlaceholderScoreComposer:
    """
    Placeholder score model.

    Replace this with any custom formula that transforms the generic X_C_* inputs
    into a single Score value.
    """

    def __call__(self, components: Mapping[str, Any], data: MarketDataBundle) -> float:
        score = 0.0
        for name, value in components.items():
            if not name.startswith("X_C_"):
                continue
            score += self._to_numeric(value)
        return score

    @staticmethod
    def _to_numeric(value: Any) -> float:
        if isinstance(value, bool):
            return 1.0 if value else 0.0
        if isinstance(value, (int, float)):
            return float(value)
        return 0.0


class BaseSignalLayer:
    def generate(self, data: MarketDataBundle) -> SignalDecision:
        components = self.extract_components(data)
        score = float(self.compose_score(components, data))
        probability = self.to_probability(score)
        action = self.decide_action(
            components=components,
            score=score,
            probability=probability,
            data=data,
        )
        return SignalDecision(
            action=action,
            score=score,
            probability=probability,
            components=dict(components),
            metadata={
                "layer": self.__class__.__name__,
                "formula": "P(win) = 1 / (1 + exp(-Score))",
            },
        )

    def extract_components(self, data: MarketDataBundle) -> Mapping[str, Any]:
        raise NotImplementedError

    def compose_score(self, components: Mapping[str, Any], data: MarketDataBundle) -> float:
        raise NotImplementedError

    def decide_action(
        self,
        *,
        components: Mapping[str, Any],
        score: float,
        probability: float,
        data: MarketDataBundle,
    ) -> SignalAction:
        raise NotImplementedError

    @staticmethod
    def to_probability(score: float) -> float:
        if score >= 0.0:
            scaled = math.exp(-score)
            return 1.0 / (1.0 + scaled)
        scaled = math.exp(score)
        return scaled / (1.0 + scaled)


class PlaceholderSignalLayer(BaseSignalLayer):
    """
    Generic signal layer that exposes only neutral placeholder conditions.
    """

    def __init__(self, score_composer: ScoreComposer | None = None) -> None:
        self.score_composer = score_composer or PlaceholderScoreComposer()

    def extract_components(self, data: MarketDataBundle) -> Mapping[str, Any]:
        raw_components = data.context.get("components", {})
        components = dict(raw_components) if isinstance(raw_components, Mapping) else {}
        components.setdefault("X_C_1", False)
        components.setdefault("X_C_2", False)
        components.setdefault("X_C_3", False)
        components.setdefault("X_C_4", False)
        components.setdefault("E_C", False)
        return components

    def compose_score(self, components: Mapping[str, Any], data: MarketDataBundle) -> float:
        return self.score_composer(components, data)

    def decide_action(
        self,
        *,
        components: Mapping[str, Any],
        score: float,
        probability: float,
        data: MarketDataBundle,
    ) -> SignalAction:
        del score
        del probability
        del data

        X_C_1 = bool(components.get("X_C_1"))
        X_C_2 = bool(components.get("X_C_2"))
        X_C_3 = bool(components.get("X_C_3"))
        X_C_4 = bool(components.get("X_C_4"))
        E_C = bool(components.get("E_C"))

        if X_C_1 and X_C_2:
            return SignalAction.BUY
        if X_C_3 and X_C_4:
            return SignalAction.SELL
        if E_C:
            return SignalAction.EXIT
        return SignalAction.HOLD
