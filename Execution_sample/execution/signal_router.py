"""Routes live tick snapshots through the unified multi-strategy runtime and broker."""

from __future__ import annotations

from datetime import datetime
from time import perf_counter
from typing import Any, Dict, List

from config import FAST_ITM1_EXECUTION_MODE, MAINTENANCE_CONTACT_MESSAGE, MAINTENANCE_MODE
from core.logger import log
from core.maintenance import log_maintenance_once
from core.state_memory import memory
from execution.multi_strategy_engine import (
    StrategySignalEvent,
    multi_strategy_engine,
)
from execution.paper_broker import PaperBroker
from execution.signal_primitives import Signal
from execution.strategy_definitions import get_enabled_strategies, validate_config
from monitoring.performance_monitor import performance_monitor


class SignalRouter:
    def __init__(self) -> None:
        self._initialized = False
        self._stats = {
            "signals_received": 0,
            "signals_routed": 0,
            "errors": 0,
        }

    def initialize(self) -> int:
        if MAINTENANCE_MODE:
            self._initialized = True
            log_maintenance_once("execution.signal_router.initialize")
            performance_monitor.on_heartbeat(
                "maintenance_mode",
                {"message": MAINTENANCE_CONTACT_MESSAGE},
            )
            return 0

        if not validate_config():
            return 0

        PaperBroker.init()
        for definition in get_enabled_strategies():
            PaperBroker.register_strategy(definition.name, definition.symbols)

        count = multi_strategy_engine.initialize()
        self._initialized = True
        log.info("[SignalRouter] initialized | runtimes=%d", count)
        performance_monitor.on_heartbeat("signal_router.initialize", {"runtimes": count})
        return count

    def route_tick(
        self,
        symbol: str,
        price: float,
        ts: datetime,
        snapshots_by_tf: Dict[int, Dict[str, Any]],
    ) -> List[StrategySignalEvent]:
        if not self._initialized:
            return []
        if MAINTENANCE_MODE:
            log_maintenance_once("execution.signal_router.route_tick")
            return []

        try:
            evaluation_started = perf_counter()
            events = multi_strategy_engine.evaluate_symbol(symbol, price, snapshots_by_tf, ts)
            performance_monitor.on_stage("signal_generation", (perf_counter() - evaluation_started) * 1000.0)
            self.route_events(events)
            PaperBroker.mark_to_market(symbol, price, ts)
            return events
        except Exception as exc:
            self._stats["errors"] += 1
            log.error("[SignalRouter] route failure | symbol=%s error=%s", symbol, exc, exc_info=True)
            return []

    def route_events(self, events: List[StrategySignalEvent]) -> int:
        routed = 0
        for event in events:
            signal_age_ms = max((datetime.now() - event.ts).total_seconds() * 1000.0, 0.0)
            if self.handle_signal_event(event, signal_age_ms=signal_age_ms):
                routed += 1
        return routed

    def handle_signal_event(
        self,
        event: StrategySignalEvent,
        *,
        signal_age_ms: float | None = None,
    ) -> bool:
        if not self._initialized:
            return False
        if MAINTENANCE_MODE:
            log_maintenance_once("execution.signal_router.handle_signal_event")
            performance_monitor.on_signal(
                strategy_name=event.strategy_name,
                symbol=event.symbol,
                signal_name=MAINTENANCE_CONTACT_MESSAGE,
                status="rejected",
                ts=event.ts,
            )
            return False
        self._stats["signals_received"] += 1
        performance_monitor.on_signal(
            strategy_name=event.strategy_name,
            symbol=event.symbol,
            signal_name=event.signal.value,
            status="generated",
            ts=event.ts,
        )
        if signal_age_ms is not None:
            performance_monitor.on_stage(
                "signal_age_before_execution",
                signal_age_ms,
                strategy_name=event.strategy_name,
            )
        if bool(memory.get_value("warmup_required", False)) and event.signal in {
            Signal.OPEN_LONG,
            Signal.OPEN_SHORT,
        }:
            log.info(
                "[SignalRouter] warmup suppress | strategy=%s symbol=%s signal=%s",
                event.strategy_name,
                event.symbol,
                event.signal.value,
            )
            performance_monitor.on_signal(
                strategy_name=event.strategy_name,
                symbol=event.symbol,
                signal_name=event.signal.value,
                status="rejected",
                ts=event.ts,
            )
            return False
        if not FAST_ITM1_EXECUTION_MODE:
            log.info(
                "[SignalRouter] signal | strategy=%s symbol=%s signal=%s mode=%s price=%.2f",
                event.strategy_name,
                event.symbol,
                event.signal.value,
                event.strategy_type,
                event.price,
            )
        trade = PaperBroker.execute_signal(
            strategy_name=event.strategy_name,
            symbol=event.symbol,
            signal=event.signal,
            price=event.price,
            ts=event.ts,
            metadata={
                "reason": event.metadata.get("reason", event.signal.value),
                "mode": event.strategy_type,
                "intrabar": True,
                **event.metadata,
            },
        )
        if trade is not None:
            multi_strategy_engine.record_fill(
                strategy_name=event.strategy_name,
                symbol=event.symbol,
                signal=event.signal,
                ts=event.ts,
                price=event.price,
            )
            self._stats["signals_routed"] += 1
            return True

        performance_monitor.on_signal(
            strategy_name=event.strategy_name,
            symbol=event.symbol,
            signal_name=event.signal.value,
            status="rejected",
            ts=event.ts,
        )
        if not FAST_ITM1_EXECUTION_MODE:
            log.info(
                "[SignalRouter] signal not filled | strategy=%s symbol=%s signal=%s",
                event.strategy_name,
                event.symbol,
                event.signal.value,
            )
        return False

    def reset(self) -> None:
        multi_strategy_engine.reset_all()

    def summary(self) -> Dict:
        return {
            "initialized": self._initialized,
            "stats": dict(self._stats),
            "strategies": multi_strategy_engine.summary(),
        }


signal_router = SignalRouter()
