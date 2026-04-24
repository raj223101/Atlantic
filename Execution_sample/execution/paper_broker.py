"""
Unified Angel-style paper broker with ITM option execution.
"""

from __future__ import annotations

import threading
from datetime import datetime
from time import perf_counter
from typing import Dict, Optional

from config import (
    OPTION_SIGNAL_MAX_AGE_MS,
    PAPER_BROKERAGE_PER_ORDER_RS,
    PAPER_IGNORE_FEES,
    PAPER_ORDER_TYPE,
)
from core.instrument_registry import get_tradeable_instrument
from core.logger import log
from execution.angel_option_service import OptionContract, OptionQuote, angel_option_service
from execution.option_execution_engine import (
    ExecutionMode,
    ExecutionResult,
    enabled_execution_modes,
    normalize_execution_mode,
    option_execution_engine,
    virtual_strategy_name,
)
from execution.signal_primitives import Signal
from execution.strategy_position_manager import StrategyPositionManager
from execution.time_manager import TimeManager
from monitoring.performance_monitor import performance_monitor
from storage.trade_storage import TradeStorage


class PaperBroker:
    _lock = threading.RLock()
    _position_managers: Dict[str, StrategyPositionManager] = {}
    _virtual_strategies: Dict[str, tuple[str, ...]] = {}
    _position_contracts: Dict[tuple[str, str], OptionContract] = {}
    _equity_by_strategy: Dict[str, float] = {}
    _closed_trades: Dict[str, list] = {}
    _stats = {
        "total_trades": 0,
        "total_pnl": 0.0,
        "errors": 0,
        "rejections": 0,
    }

    @classmethod
    def _increment_stat(cls, key: str, amount: float = 1.0) -> None:
        with cls._lock:
            cls._stats[key] = cls._stats.get(key, 0) + amount

    @classmethod
    def init(cls) -> None:
        with cls._lock:
            cls._position_managers.clear()
            cls._virtual_strategies.clear()
            cls._position_contracts.clear()
            cls._equity_by_strategy.clear()
            cls._closed_trades.clear()
            cls._stats = {
                "total_trades": 0,
                "total_pnl": 0.0,
                "errors": 0,
                "rejections": 0,
            }
        log.info(
            "[PaperBroker] initialized | order_type=%s option_lots=%d",
            PAPER_ORDER_TYPE,
            angel_option_service.option_lots_per_trade(),
        )

    @classmethod
    def register_strategy(cls, strategy_name: str, symbols) -> None:
        with cls._lock:
            virtuals: list[str] = []
            for mode in enabled_execution_modes():
                resolved_name = virtual_strategy_name(strategy_name, mode)
                virtuals.append(resolved_name)
                manager = cls._position_managers.get(resolved_name)
                if manager is None:
                    manager = StrategyPositionManager(resolved_name)
                    cls._position_managers[resolved_name] = manager
                    cls._equity_by_strategy[resolved_name] = 0.0
                    cls._closed_trades[resolved_name] = []
                for symbol in symbols:
                    manager.initialize_symbol(symbol)
            cls._virtual_strategies[strategy_name] = tuple(virtuals)

    @classmethod
    def execute_signal(
        cls,
        strategy_name: str,
        symbol: str,
        signal: Signal | str,
        price: float,
        ts: datetime,
        metadata: Optional[Dict] = None,
    ) -> Optional[Dict]:
        metadata = metadata or {}
        normalized = cls._normalize_signal(signal)
        if normalized is None:
            return None

        targets = cls._strategy_targets(strategy_name)
        if not targets:
            cls._increment_stat("errors")
            log.error("[PaperBroker] strategy not registered: %s", strategy_name)
            return None

        results: Dict[str, Dict] = {}
        for target_name in targets:
            with cls._lock:
                manager = cls._position_managers.get(target_name)
            if manager is None:
                continue
            mode = cls._execution_mode_for_strategy(target_name)
            target_metadata = {
                **metadata,
                "base_strategy_name": strategy_name,
                "execution_mode": mode.value,
            }
            if normalized == Signal.OPEN_LONG:
                if not TimeManager.can_enter_new_trade(ts):
                    continue
                result = cls._open_position(manager, target_name, symbol, "LONG", price, ts, target_metadata, mode)
            elif normalized == Signal.OPEN_SHORT:
                if not TimeManager.can_enter_new_trade(ts):
                    continue
                result = cls._open_position(manager, target_name, symbol, "SHORT", price, ts, target_metadata, mode)
            elif normalized == Signal.CLOSE_LONG:
                result = cls._close_position(manager, target_name, symbol, "LONG", price, ts, target_metadata, mode)
            elif normalized == Signal.CLOSE_SHORT:
                result = cls._close_position(manager, target_name, symbol, "SHORT", price, ts, target_metadata, mode)
            else:
                result = None
            if result is not None:
                results[target_name] = result
        return results or None

    @classmethod
    def _open_position(
        cls,
        manager: StrategyPositionManager,
        strategy_name: str,
        symbol: str,
        side: str,
        price: float,
        ts: datetime,
        metadata: Dict,
        execution_mode: ExecutionMode,
    ) -> Optional[Dict]:
        started = perf_counter()
        performance_monitor.on_order(
            strategy_name=strategy_name,
            symbol=symbol,
            order_side=side,
            order_kind="ENTRY",
            status="attempted",
        )
        if not manager.tracks_symbol(symbol) or manager.has_position(symbol):
            performance_monitor.on_order(
                strategy_name=strategy_name,
                symbol=symbol,
                order_side=side,
                order_kind="ENTRY",
                status="rejected",
                latency_ms=(perf_counter() - started) * 1000.0,
                reason="position_exists_or_symbol_untracked",
            )
            return None

        signal_age_ms = max((datetime.now() - ts).total_seconds() * 1000.0, 0.0)
        if float(OPTION_SIGNAL_MAX_AGE_MS) > 0.0 and signal_age_ms > float(OPTION_SIGNAL_MAX_AGE_MS):
            cls._increment_stat("rejections")
            performance_monitor.on_order(
                strategy_name=strategy_name,
                symbol=symbol,
                order_side=side,
                order_kind="ENTRY",
                status="rejected",
                latency_ms=(perf_counter() - started) * 1000.0,
                reason="signal_too_stale",
            )
            log.warning(
                "[PaperBroker] signal too stale | age=%.1fms strategy=%s symbol=%s side=%s",
                signal_age_ms,
                strategy_name,
                symbol,
                side,
            )
            return None

        execution = option_execution_engine.execute_entry(
            underlying_symbol=symbol,
            signal_side=side,
            underlying_price=price,
            ts=ts,
            execution_mode=execution_mode,
            option_bucket=str(metadata.get("option_bucket", "ITM1")),
        )
        if not execution.filled or execution.contract is None:
            cls._increment_stat("rejections")
            performance_monitor.on_order(
                strategy_name=strategy_name,
                symbol=symbol,
                order_side=side,
                order_kind="ENTRY",
                status="rejected",
                latency_ms=(perf_counter() - started) * 1000.0,
                reason=execution.reason or "entry_execution_failed",
            )
            log.warning(
                "[PaperBroker] entry rejected | strategy=%s symbol=%s side=%s reason=%s",
                strategy_name,
                symbol,
                side,
                execution.reason,
            )
            return None

        contract = execution.contract
        quote = execution.quote
        quantity_units = int(execution.quantity)
        lots = angel_option_service.option_lots_per_trade()
        fill_price = float(execution.fill_price)
        fill_latency_ms = float(execution.total_elapsed_ms or ((perf_counter() - started) * 1000.0))
        slippage = abs(fill_price - float(execution.fair_value))
        trade_id = f"{strategy_name}:{symbol}:{ts.isoformat()}:{side}"
        entry_metadata = {"trade_id": trade_id, **metadata}

        position = manager.open_position(
            symbol=symbol,
            side=side,
            entry_price=fill_price,
            qty=quantity_units,
            entry_ts=ts,
            entry_reason=metadata.get("reason", side),
            pricing_model="long_option",
            metadata=cls._build_entry_metadata(
                contract,
                execution,
                symbol,
                side,
                price,
                lots,
                entry_metadata,
            ),
        )
        if position is None:
            return None

        with cls._lock:
            cls._position_contracts[(strategy_name, symbol)] = contract
        angel_option_service.pin_contract(contract)

        performance_monitor.on_stage("order_placement", fill_latency_ms, strategy_name=strategy_name)
        performance_monitor.on_stage("fill_confirmation", fill_latency_ms, strategy_name=strategy_name)
        performance_monitor.on_order(
            strategy_name=strategy_name,
            symbol=symbol,
            order_side=side,
            order_kind="ENTRY",
            status="filled",
            latency_ms=fill_latency_ms,
            fill_latency_ms=fill_latency_ms,
            slippage=slippage,
        )

        payload = {
            "strategy_name": strategy_name,
            "symbol": symbol,
            "side": side,
            "entry_price": fill_price,
            "underlying_entry_price": price,
            "qty": quantity_units,
            "lots": lots,
            "entry_ts": ts,
            "entry_reason": metadata.get("reason", side),
            "signal_price": price,
            "trade_id": position.metadata.get("trade_id", trade_id),
            "order_type": PAPER_ORDER_TYPE,
            "option_symbol": contract.symbol,
            "option_token": contract.token,
            "option_exchange": contract.exchange,
            "option_type": contract.option_type,
            "option_strike": contract.strike,
            "option_expiry": contract.expiry,
            "limit_price": execution.limit_price,
            "fair_value": execution.fair_value,
            "repriced": execution.repriced,
            "execution_mode": execution.execution_mode,
            "entry_label": execution.execution_phase,
            "option_bucket": str(metadata.get("option_bucket", "ITM1")),
            "metadata": metadata,
        }
        log.info(
            "[PaperBroker] OPEN | strategy=%s mode=%s symbol=%s dir=%s option=%s qty=%d fill=%.2f limit=%.2f fair=%.2f phase=%s underlying=%.2f",
            strategy_name,
            execution.execution_mode or execution_mode.value,
            symbol,
            side,
            contract.symbol,
            quantity_units,
            fill_price,
            execution.limit_price,
            execution.fair_value,
            execution.execution_phase,
            price,
        )
        return payload

    @classmethod
    def _close_position(
        cls,
        manager: StrategyPositionManager,
        strategy_name: str,
        symbol: str,
        expected_side: str,
        price: float,
        ts: datetime,
        metadata: Dict,
        execution_mode: ExecutionMode,
    ) -> Optional[Dict]:
        started = perf_counter()
        performance_monitor.on_order(
            strategy_name=strategy_name,
            symbol=symbol,
            order_side=expected_side,
            order_kind="EXIT",
            status="attempted",
        )
        if not manager.tracks_symbol(symbol):
            performance_monitor.on_order(
                strategy_name=strategy_name,
                symbol=symbol,
                order_side=expected_side,
                order_kind="EXIT",
                status="rejected",
                latency_ms=(perf_counter() - started) * 1000.0,
                reason="symbol_untracked",
            )
            return None
        position = manager.get_position(symbol)
        if position is None or position["side"] != expected_side:
            performance_monitor.on_order(
                strategy_name=strategy_name,
                symbol=symbol,
                order_side=expected_side,
                order_kind="EXIT",
                status="rejected",
                latency_ms=(perf_counter() - started) * 1000.0,
                reason="position_missing_or_side_mismatch",
            )
            return None

        with cls._lock:
            contract = cls._position_contracts.get((strategy_name, symbol))
        if contract is None:
            contract = cls._contract_from_position(symbol, position)
        if contract is None:
            performance_monitor.on_order(
                strategy_name=strategy_name,
                symbol=symbol,
                order_side=expected_side,
                order_kind="EXIT",
                status="rejected",
                latency_ms=(perf_counter() - started) * 1000.0,
                reason="contract_missing",
            )
            return None

        execution = option_execution_engine.execute_exit(
            contract=contract,
            quantity=int(position.get("qty", 0)),
            underlying_price=price,
            ts=ts,
            execution_mode=execution_mode,
        )
        if not execution.filled:
            cls._increment_stat("rejections")
            performance_monitor.on_order(
                strategy_name=strategy_name,
                symbol=symbol,
                order_side=expected_side,
                order_kind="EXIT",
                status="rejected",
                latency_ms=(perf_counter() - started) * 1000.0,
                reason=execution.reason or "exit_execution_failed",
            )
            log.warning(
                "[PaperBroker] exit rejected | strategy=%s symbol=%s side=%s reason=%s",
                strategy_name,
                symbol,
                expected_side,
                execution.reason,
            )
            return None

        quote = execution.quote
        fill_price = float(execution.fill_price)
        fill_latency_ms = float(execution.total_elapsed_ms or ((perf_counter() - started) * 1000.0))
        slippage = abs(fill_price - float(execution.fair_value))
        manager.update_mark_to_market(
            symbol,
            fill_price,
            ts,
            context=cls._quote_context(price, quote),
        )
        trade = manager.close_position(
            symbol=symbol,
            exit_price=fill_price,
            exit_ts=ts,
            exit_reason=metadata.get("reason", f"CLOSE_{expected_side}"),
        )
        if trade is None:
            performance_monitor.on_order(
                strategy_name=strategy_name,
                symbol=symbol,
                order_side=expected_side,
                order_kind="EXIT",
                status="rejected",
                latency_ms=fill_latency_ms,
                reason="close_position_failed",
            )
            return None

        charges = 0.0 if PAPER_IGNORE_FEES else PAPER_BROKERAGE_PER_ORDER_RS * 2.0
        gross_pnl = float(trade["pnl"])
        net_pnl = gross_pnl - charges
        with cls._lock:
            cls._position_contracts.pop((strategy_name, symbol), None)
            cls._equity_by_strategy[strategy_name] += net_pnl
            cls._closed_trades[strategy_name].append(dict(trade))
            cls._stats["total_trades"] += 1
            cls._stats["total_pnl"] += net_pnl
            equity = cls._equity_by_strategy[strategy_name]
        angel_option_service.unpin_contract(contract)

        trade_record = cls._build_trade_record(
            trade,
            execution,
            price,
            charges,
            gross_pnl,
            net_pnl,
            equity,
        )
        TradeStorage.write_trade(strategy_name, trade_record)
        performance_monitor.on_stage("order_placement", fill_latency_ms, strategy_name=strategy_name)
        performance_monitor.on_stage("fill_confirmation", fill_latency_ms, strategy_name=strategy_name)
        performance_monitor.on_order(
            strategy_name=strategy_name,
            symbol=symbol,
            order_side=expected_side,
            order_kind="EXIT",
            status="filled",
            latency_ms=fill_latency_ms,
            fill_latency_ms=fill_latency_ms,
            slippage=slippage,
        )
        performance_monitor.on_trade_closed(
            strategy_name=strategy_name,
            pnl=net_pnl,
            win=net_pnl > 0,
        )
        log.info(
            "[PaperBroker] CLOSE | strategy=%s mode=%s symbol=%s dir=%s option=%s qty=%d fill=%.2f fair=%.2f phase=%s net=%.2f",
            strategy_name,
            execution.execution_mode or execution_mode.value,
            symbol,
            trade["side"],
            trade_record.get("option_symbol", ""),
            trade["qty"],
            execution.fill_price,
            execution.fair_value,
            execution.execution_phase,
            net_pnl,
        )
        return trade_record

    @classmethod
    def _build_entry_metadata(
        cls,
        contract: OptionContract,
        execution: ExecutionResult,
        symbol: str,
        side: str,
        underlying_price: float,
        lots: int,
        metadata: Dict,
    ) -> Dict:
        trade_id = metadata.get("trade_id") or f"{symbol}:{side}:{contract.symbol}:{metadata.get('entry_ts', '')}"
        quote = execution.quote
        payload = {
            "underlying_symbol": symbol,
            "underlying_price": underlying_price,
            "underlying_entry_price": underlying_price,
            "underlying_last_price": underlying_price,
            "option_symbol": contract.symbol,
            "option_token": contract.token,
            "option_exchange": contract.exchange,
            "option_type": contract.option_type,
            "option_strike": contract.strike,
            "option_expiry": contract.expiry,
            "option_lot_size": contract.lot_size,
            "lots": lots,
            "option_entry_price": execution.fill_price,
            "entry_option_quote_ts": quote.ts.isoformat() if quote else "",
            "entry_option_bid": quote.bid if quote else 0.0,
            "entry_option_ask": quote.ask if quote else 0.0,
            "entry_fair_value": execution.fair_value,
            "entry_initial_fair_value": execution.initial_fair_value,
            "entry_limit_price": execution.limit_price,
            "entry_initial_limit_price": execution.initial_limit_price,
            "entry_spread": execution.spread,
            "entry_spread_pct": execution.spread_pct,
            "entry_quote_age_ms": execution.quote_age_ms,
            "entry_quote_source": execution.quote_source,
            "entry_pricing_mode": execution.pricing_mode,
            "entry_repriced": execution.repriced,
            "entry_slippage_vs_fair": execution.fill_price - execution.fair_value,
            "entry_order_id": execution.order_id,
            "entry_reprice_order_id": execution.reprice_order_id,
            "strategy_mode": metadata.get("mode", ""),
            "execution_mode": execution.execution_mode or metadata.get("execution_mode", ""),
            "entry_label": execution.execution_phase,
            "option_bucket": str(metadata.get("option_bucket", "ITM1")),
            "intrabar": bool(metadata.get("intrabar", True)),
            "strategy_direction": "BUY" if side == "LONG" else "SELL",
            "trade_id": trade_id,
        }
        for key, value in metadata.items():
            if key in {"reason", "mode", "intrabar"}:
                continue
            payload[key] = value
        return payload

    @classmethod
    def _build_trade_record(
        cls,
        trade: Dict,
        execution: ExecutionResult,
        underlying_exit_price: float,
        charges: float,
        gross_pnl: float,
        net_pnl: float,
        equity: float,
    ) -> Dict:
        quote = execution.quote
        return {
            "underlying_symbol": trade.get("underlying_symbol", trade.get("symbol", "")),
            "strategy_direction": trade.get("strategy_direction", "BUY" if trade.get("side") == "LONG" else "SELL"),
            "execution_mode": trade.get("execution_mode", ""),
            "entry_label": trade.get("entry_label", ""),
            "exit_label": execution.execution_phase,
            "option_symbol": trade.get("option_symbol", ""),
            "option_strike": trade.get("option_strike", 0.0),
            "option_type": trade.get("option_type", ""),
            "option_bucket": trade.get("option_bucket", ""),
            "option_entry_price": trade.get("option_entry_price", trade.get("entry_price", 0.0)),
            "option_exit_price": execution.fill_price,
            "qty": trade.get("qty", 0),
            "pnl": net_pnl,
            "trade_id": trade.get("trade_id", f"{trade.get('symbol','')}:{trade.get('exit_ts').isoformat()}"),
            "entry_ts": trade.get("entry_ts"),
            "exit_ts": trade.get("exit_ts"),
            "underlying_entry_price": trade.get("underlying_entry_price", 0.0),
            "underlying_exit_price": underlying_exit_price,
            "gross_pnl": gross_pnl,
            "charges": charges,
            "equity": equity,
            "entry_fair_value": trade.get("entry_fair_value", 0.0),
            "exit_fair_value": execution.fair_value,
            "entry_limit_price": trade.get("entry_limit_price", 0.0),
            "exit_limit_price": execution.limit_price,
            "entry_spread_pct": trade.get("entry_spread_pct", 0.0),
            "exit_spread_pct": execution.spread_pct,
            "entry_quote_source": trade.get("entry_quote_source", ""),
            "exit_quote_source": execution.quote_source,
            "entry_pricing_mode": trade.get("entry_pricing_mode", ""),
            "exit_pricing_mode": execution.pricing_mode,
            "entry_repriced": trade.get("entry_repriced", False),
            "exit_repriced": execution.repriced,
            "entry_slippage_vs_fair": trade.get("entry_slippage_vs_fair", 0.0),
            "exit_slippage_vs_fair": execution.fill_price - execution.fair_value,
            "exit_option_bid": quote.bid if quote else 0.0,
            "exit_option_ask": quote.ask if quote else 0.0,
        }

    @classmethod
    def _contract_from_position(cls, symbol: str, position: Dict):
        meta = position.get("metadata", {})
        expiry = str(meta.get("option_expiry", ""))
        try:
            expiry_date = datetime.strptime(expiry.upper(), "%d%b%Y").date()
        except Exception:
            expiry_date = datetime.now().date()
        return OptionContract(
            underlying_symbol=symbol,
            symbol=str(meta.get("option_symbol", "")),
            token=str(meta.get("option_token", "")),
            exchange=str(meta.get("option_exchange", "")),
            exchange_type=2 if str(meta.get("option_exchange", "")).upper() == "NFO" else 4,
            option_type=str(meta.get("option_type", "")),
            strike=float(meta.get("option_strike", 0.0)),
            expiry=expiry,
            expiry_date=expiry_date,
            lot_size=int(meta.get("option_lot_size", 0)),
            tick_size=float(get_tradeable_instrument(symbol).tick_size),
        )

    @classmethod
    def _quote_context(cls, underlying_price: float, quote: Optional[OptionQuote]) -> Dict:
        payload = {"underlying_price": underlying_price}
        if quote is not None:
            payload["option_last_price"] = quote.ltp
            payload["option_last_quote_ts"] = quote.ts.isoformat()
            payload["option_last_bid"] = quote.bid
            payload["option_last_ask"] = quote.ask
        return payload

    @classmethod
    def _normalize_signal(cls, signal: Signal | str) -> Optional[Signal]:
        if isinstance(signal, Signal):
            return signal
        try:
            return Signal(signal)
        except ValueError:
            return None

    @classmethod
    def _strategy_targets(cls, strategy_name: str) -> tuple[str, ...]:
        with cls._lock:
            mapped = cls._virtual_strategies.get(strategy_name)
            if mapped:
                return mapped
            if strategy_name in cls._position_managers:
                return (strategy_name,)
        return ()

    @staticmethod
    def _execution_mode_for_strategy(strategy_name: str) -> ExecutionMode:
        if "__" in str(strategy_name):
            suffix = str(strategy_name).rsplit("__", 1)[-1]
            return normalize_execution_mode(suffix)
        return ExecutionMode.TYPE_F

    @classmethod
    def mark_to_market(cls, symbol: str, price: float, ts: datetime) -> None:
        with cls._lock:
            managers = list(cls._position_managers.items())
            contract_cache = dict(cls._position_contracts)
        for strategy_name, manager in managers:
            position = manager.get_position(symbol)
            if position is None:
                continue
            contract = contract_cache.get((strategy_name, symbol))
            if contract is None:
                contract = cls._contract_from_position(symbol, position)
                if contract is not None:
                    with cls._lock:
                        cls._position_contracts[(strategy_name, symbol)] = contract
            quote = angel_option_service.cached_quote(contract) if contract else None
            option_price = quote.ltp if quote is not None else position["current_price"]
            manager.update_mark_to_market(symbol, option_price, ts, context=cls._quote_context(price, quote))

    @classmethod
    def force_exit_all(cls, price_map: Dict[str, float], ts: datetime, reason: str) -> int:
        closed = 0
        with cls._lock:
            managers = list(cls._position_managers.items())
        for strategy_name, manager in managers:
            for symbol, position in manager.get_all_positions().items():
                exit_signal = Signal.CLOSE_LONG if position["side"] == "LONG" else Signal.CLOSE_SHORT
                result = cls.execute_signal(
                    strategy_name=strategy_name,
                    symbol=symbol,
                    signal=exit_signal,
                    price=price_map.get(symbol, position["metadata"].get("underlying_last_price", 0.0)),
                    ts=ts,
                    metadata={"reason": reason},
                )
                if result is not None:
                    closed += 1
        return closed

    @classmethod
    def has_position(cls, symbol: str, strategy_name: Optional[str] = None) -> bool:
        if strategy_name is not None:
            manager = cls._position_managers.get(strategy_name)
            return manager.has_position(symbol) if manager else False
        return any(manager.has_position(symbol) for manager in cls._position_managers.values())

    @classmethod
    def get_position(cls, symbol: str, strategy_name: Optional[str] = None) -> Optional[Dict]:
        if strategy_name is not None:
            manager = cls._position_managers.get(strategy_name)
            return manager.get_position(symbol) if manager else None
        for name, manager in cls._position_managers.items():
            position = manager.get_position(symbol)
            if position is not None:
                return {"strategy_name": name, **position}
        return None

    @classmethod
    def get_equity(cls, strategy_name: Optional[str] = None) -> float:
        with cls._lock:
            if strategy_name is not None:
                return cls._equity_by_strategy.get(strategy_name, 0.0)
            return sum(cls._equity_by_strategy.values())

    @classmethod
    def get_strategy_summary(cls, strategy_name: str) -> Dict:
        manager = cls._position_managers.get(strategy_name)
        if manager is None:
            return {}
        return {
            "strategy_name": strategy_name,
            "equity": cls.get_equity(strategy_name),
            "positions": manager.summary(),
            "trade_stats": TradeStorage.calculate_stats(strategy_name),
        }

    @classmethod
    def get_summary(cls) -> Dict:
        with cls._lock:
            total_open_positions = sum(
                len(manager.get_all_positions()) for manager in cls._position_managers.values()
            )
            return {
                "strategies": len(cls._position_managers),
                "total_trades": cls._stats["total_trades"],
                "net_pnl": cls._stats["total_pnl"],
                "open_positions": total_open_positions,
                "rejections": cls._stats["rejections"],
            }

    @classmethod
    def get_all_strategy_summaries(cls) -> Dict[str, Dict]:
        return {
            strategy_name: cls.get_strategy_summary(strategy_name)
            for strategy_name in cls._position_managers
        }

    @classmethod
    def stats(cls) -> Dict:
        with cls._lock:
            return dict(cls._stats)

    @classmethod
    def print_summary(cls) -> None:
        summary = cls.get_summary()
        log.info(
            "[PaperBroker] summary | strategies=%d trades=%d open=%d rejections=%d pnl=%.2f",
            summary["strategies"],
            summary["total_trades"],
            summary["open_positions"],
            summary["rejections"],
            summary["net_pnl"],
        )
