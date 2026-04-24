"""
Execution-native multi-strategy runtime for the five selected strategies.
"""

from __future__ import annotations

import threading
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional

from config import MAINTENANCE_MODE, SIGNAL_STABILITY_MS
from core.logger import log
from core.maintenance import log_maintenance_once
from execution.signal_primitives import NextBucketGuard, PositionState, Signal, SignalStabilizer
from execution.strategy_definitions import StrategyDefinition, get_enabled_strategies


@dataclass(frozen=True)
class StrategySignalEvent:
    strategy_name: str
    symbol: str
    signal: Signal
    price: float
    ts: datetime
    strategy_type: str
    metadata: Dict[str, Any]


class StrategyRuntime:
    def __init__(self, definition: StrategyDefinition, symbol: str) -> None:
        self.definition = definition
        self.symbol = symbol
        self.strategy_name = definition.name
        self.primary_tf = int(definition.primary_tf)
        self._calculation_aliases = dict(definition.rule_spec.get("calculation_aliases", {}))
        self._entry_conditions = dict(definition.rule_spec.get("entry_conditions", {}))
        self._exit_rules = dict(definition.rule_spec.get("runtime_exit_rules", {}))
        self._lock = threading.RLock()
        self._position_state = PositionState.FLAT
        self._entry_price = 0.0
        self._entry_ts: Optional[datetime] = None
        self._last_signal: Optional[str] = None
        self._stabilizer = SignalStabilizer(
            stability_ms=SIGNAL_STABILITY_MS,
            bucket_tf=int(definition.tf_entry),
        )
        self._reentry_guard = NextBucketGuard(reference_tf=int(definition.tf_reentry))

    def evaluate(
        self,
        *,
        price: float,
        snapshots_by_tf: Dict[int, Dict[str, Any]],
        ts: datetime,
    ) -> Optional[StrategySignalEvent]:
        if MAINTENANCE_MODE:
            log_maintenance_once("execution.multi_strategy_engine")
            return None

        with self._lock:
            if self._position_state == PositionState.FLAT:
                return self._evaluate_entry(price=price, snapshots_by_tf=snapshots_by_tf, ts=ts)
            if self._position_state == PositionState.LONG:
                return self._evaluate_exit(
                    side_key="long",
                    close_signal=Signal.CLOSE_LONG,
                    price=price,
                    snapshots_by_tf=snapshots_by_tf,
                    ts=ts,
                )
            if self._position_state == PositionState.SHORT:
                return self._evaluate_exit(
                    side_key="short",
                    close_signal=Signal.CLOSE_SHORT,
                    price=price,
                    snapshots_by_tf=snapshots_by_tf,
                    ts=ts,
                )
        return None

    def record_fill(self, signal: Signal, ts: datetime, price: float) -> None:
        with self._lock:
            if signal == Signal.OPEN_LONG:
                self._position_state = PositionState.LONG
                self._entry_ts = ts
                self._entry_price = float(price)
                self._last_signal = signal.value
                return

            if signal == Signal.OPEN_SHORT:
                self._position_state = PositionState.SHORT
                self._entry_ts = ts
                self._entry_price = float(price)
                self._last_signal = signal.value
                return

            if signal in (Signal.CLOSE_LONG, Signal.CLOSE_SHORT):
                self._position_state = PositionState.FLAT
                self._entry_ts = None
                self._entry_price = 0.0
                self._last_signal = signal.value
                self._stabilizer.reset()
                self._reentry_guard.record_exit(ts)

    def reset(self) -> None:
        with self._lock:
            self._position_state = PositionState.FLAT
            self._entry_price = 0.0
            self._entry_ts = None
            self._last_signal = None
            self._stabilizer.reset()
            self._reentry_guard.reset()

    def summary(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "strategy_name": self.strategy_name,
                "symbol": self.symbol,
                "primary_tf": self.primary_tf,
                "position_state": self._position_state.value,
                "entry_price": self._entry_price,
                "entry_ts": self._entry_ts.isoformat() if self._entry_ts else "",
                "last_signal": self._last_signal or "",
            }

    def _evaluate_entry(
        self,
        *,
        price: float,
        snapshots_by_tf: Dict[int, Dict[str, Any]],
        ts: datetime,
    ) -> Optional[StrategySignalEvent]:
        if not self._reentry_guard.can_enter(ts):
            self._stabilizer.update(Signal.NONE, ts)
            return None

        long_ready = self._conditions_match(
            self._entry_conditions.get("long", []),
            price=price,
            snapshots_by_tf=snapshots_by_tf,
            ts=ts,
        )
        short_ready = self._conditions_match(
            self._entry_conditions.get("short", []),
            price=price,
            snapshots_by_tf=snapshots_by_tf,
            ts=ts,
        )

        if long_ready and not short_ready:
            candidate = Signal.OPEN_LONG
            reason = "ENTRY_LONG_READY"
        elif short_ready and not long_ready:
            candidate = Signal.OPEN_SHORT
            reason = "ENTRY_SHORT_READY"
        else:
            candidate = Signal.NONE
            reason = ""

        fired = self._stabilizer.update(candidate, ts)
        if fired not in (Signal.OPEN_LONG, Signal.OPEN_SHORT):
            return None

        return StrategySignalEvent(
            strategy_name=self.strategy_name,
            symbol=self.symbol,
            signal=fired,
            price=float(price),
            ts=ts,
            strategy_type=self.definition.logic_profile,
            metadata={
                "reason": reason,
                "base_strategy": self.definition.base_strategy,
                "variant": self.definition.variant,
                "entry_tf": int(self.definition.tf_entry),
                "exit_tf": int(self.definition.tf_exit),
                "option_bucket": str(self.definition.option_bucket),
            },
        )

    def _evaluate_exit(
        self,
        *,
        side_key: str,
        close_signal: Signal,
        price: float,
        snapshots_by_tf: Dict[int, Dict[str, Any]],
        ts: datetime,
    ) -> Optional[StrategySignalEvent]:
        rule_name = self._match_rule_group(
            self._exit_rules.get(side_key, []),
            price=price,
            snapshots_by_tf=snapshots_by_tf,
            ts=ts,
        )
        if not rule_name:
            return None

        return StrategySignalEvent(
            strategy_name=self.strategy_name,
            symbol=self.symbol,
            signal=close_signal,
            price=float(price),
            ts=ts,
            strategy_type=self.definition.logic_profile,
            metadata={
                "reason": rule_name,
                "base_strategy": self.definition.base_strategy,
                "variant": self.definition.variant,
                "entry_tf": int(self.definition.tf_entry),
                "exit_tf": int(self.definition.tf_exit),
                "option_bucket": str(self.definition.option_bucket),
            },
        )

    def _match_rule_group(
        self,
        groups: Iterable[Dict[str, Any]],
        *,
        price: float,
        snapshots_by_tf: Dict[int, Dict[str, Any]],
        ts: datetime,
    ) -> str:
        for group in groups:
            conditions = group.get("all", [])
            if self._conditions_match(conditions, price=price, snapshots_by_tf=snapshots_by_tf, ts=ts):
                return str(group.get("name", "EXIT_RULE"))
        return ""

    def _conditions_match(
        self,
        conditions: Iterable[Dict[str, Any]],
        *,
        price: float,
        snapshots_by_tf: Dict[int, Dict[str, Any]],
        ts: datetime,
    ) -> bool:
        return all(
            self._condition_match(condition, price=price, snapshots_by_tf=snapshots_by_tf, ts=ts)
            for condition in conditions
        )

    def _condition_match(
        self,
        condition: Dict[str, Any],
        *,
        price: float,
        snapshots_by_tf: Dict[int, Dict[str, Any]],
        ts: datetime,
    ) -> bool:
        tf = int(condition.get("tf", self.definition.tf_entry))
        left = self._resolve_operand(condition.get("left"), tf=tf, price=price, snapshots_by_tf=snapshots_by_tf, ts=ts)
        right = self._resolve_operand(condition.get("right"), tf=tf, price=price, snapshots_by_tf=snapshots_by_tf, ts=ts)
        return self._compare(left, right, str(condition.get("op", "==")))

    def _resolve_operand(
        self,
        operand: Any,
        *,
        tf: int,
        price: float,
        snapshots_by_tf: Dict[int, Dict[str, Any]],
        ts: datetime,
    ) -> Any:
        if isinstance(operand, (int, float, bool)) or operand is None:
            return operand

        if not isinstance(operand, str):
            return operand

        stripped = operand.strip()
        special = self._special_value(stripped, price=price, ts=ts)
        if special is not None:
            return special

        snapshot = snapshots_by_tf.get(int(tf), {})
        key = self._calculation_aliases.get(stripped, stripped)
        if key in snapshot:
            return snapshot.get(key)

        if stripped in snapshot:
            return snapshot.get(stripped)

        if stripped.upper() in {"BULL", "BEAR", "NEUTRAL"}:
            return stripped.upper()

        try:
            return float(stripped)
        except ValueError:
            return stripped

    def _special_value(self, operand: str, *, price: float, ts: datetime) -> Any:
        if operand == "price":
            return float(price)
        if operand == "entry_price":
            return float(self._entry_price)
        if operand == "hold_secs":
            if self._entry_ts is None:
                return 0.0
            return max((ts - self._entry_ts).total_seconds(), 0.0)
        if operand == "price_minus_entry":
            return float(price) - float(self._entry_price)
        if operand == "entry_minus_price":
            return float(self._entry_price) - float(price)
        return None

    def _compare(self, left: Any, right: Any, op: str) -> bool:
        if left is None or right is None:
            return False

        if isinstance(left, str) or isinstance(right, str):
            left_text = str(left).upper()
            right_text = str(right).upper()
            if op == "==":
                return left_text == right_text
            if op == "!=":
                return left_text != right_text
            try:
                left_value = float(left)
                right_value = float(right)
            except (TypeError, ValueError):
                return False
            return self._compare_numbers(left_value, right_value, op)

        try:
            left_value = float(left)
            right_value = float(right)
        except (TypeError, ValueError):
            if op == "==":
                return left == right
            if op == "!=":
                return left != right
            return False
        return self._compare_numbers(left_value, right_value, op)

    @staticmethod
    def _compare_numbers(left: float, right: float, op: str) -> bool:
        if op == "==":
            return left == right
        if op == "!=":
            return left != right
        if op == ">":
            return left > right
        if op == ">=":
            return left >= right
        if op == "<":
            return left < right
        if op == "<=":
            return left <= right
        return False


class MultiStrategyEngine:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._runtimes: List[StrategyRuntime] = []
        self._runtimes_by_symbol: Dict[str, List[StrategyRuntime]] = defaultdict(list)
        self._runtimes_by_key: Dict[tuple[str, str], StrategyRuntime] = {}

    def initialize(self) -> int:
        strategies = get_enabled_strategies()
        runtimes: List[StrategyRuntime] = []
        runtimes_by_symbol: Dict[str, List[StrategyRuntime]] = defaultdict(list)
        runtimes_by_key: Dict[tuple[str, str], StrategyRuntime] = {}

        for definition in strategies:
            for symbol in definition.symbols:
                runtime = StrategyRuntime(definition, symbol)
                runtimes.append(runtime)
                runtimes_by_symbol[symbol].append(runtime)
                runtimes_by_key[(definition.name, symbol)] = runtime

        with self._lock:
            self._runtimes = runtimes
            self._runtimes_by_symbol = dict(runtimes_by_symbol)
            self._runtimes_by_key = runtimes_by_key

        log.info(
            "[MultiStrategyEngine] initialized | runtimes=%d strategies=%d",
            len(runtimes),
            len(strategies),
        )
        return len(runtimes)

    def runtimes(self) -> List[StrategyRuntime]:
        with self._lock:
            return list(self._runtimes)

    def evaluate_symbol(
        self,
        symbol: str,
        price: float,
        snapshots_by_tf: Dict[int, Dict[str, Any]],
        ts: datetime,
    ) -> List[StrategySignalEvent]:
        with self._lock:
            runtimes = list(self._runtimes_by_symbol.get(symbol, []))
        return self.evaluate_runtimes(
            runtimes=runtimes,
            symbol=symbol,
            price=price,
            snapshots_by_tf=snapshots_by_tf,
            ts=ts,
        )

    def evaluate_runtimes(
        self,
        *,
        runtimes: Iterable[StrategyRuntime],
        symbol: str,
        price: float,
        snapshots_by_tf: Dict[int, Dict[str, Any]],
        ts: datetime,
    ) -> List[StrategySignalEvent]:
        events: List[StrategySignalEvent] = []
        for runtime in runtimes:
            if runtime.symbol != symbol:
                continue
            event = runtime.evaluate(price=price, snapshots_by_tf=snapshots_by_tf, ts=ts)
            if event is not None:
                events.append(event)
        return events

    def record_fill(
        self,
        *,
        strategy_name: str,
        symbol: str,
        signal: Signal,
        ts: datetime,
        price: float,
    ) -> None:
        with self._lock:
            runtime = self._runtimes_by_key.get((strategy_name, symbol))
        if runtime is None:
            log.warning(
                "[MultiStrategyEngine] missing runtime for fill | strategy=%s symbol=%s",
                strategy_name,
                symbol,
            )
            return
        runtime.record_fill(signal, ts, price)

    def reset_all(self) -> None:
        with self._lock:
            runtimes = list(self._runtimes)
        for runtime in runtimes:
            runtime.reset()

    def summary(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "runtimes": len(self._runtimes),
                "by_symbol": {
                    symbol: [runtime.summary() for runtime in runtimes]
                    for symbol, runtimes in self._runtimes_by_symbol.items()
                },
            }


multi_strategy_engine = MultiStrategyEngine()
