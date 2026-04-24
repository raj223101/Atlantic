"""
Option execution with live limit-IOC routing and configurable paper fills.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from time import perf_counter, sleep
from typing import Any, Dict, Iterable, Optional
import math
import uuid

from config import (
    ACTIVE_EXECUTION_MODES,
    AB_TEST_ENTRY_DEADLINE_MS,
    AB_TEST_EXIT_DEADLINE_MS,
    AB_TEST_MAX_SPREAD_RS,
    AB_TEST_QUOTE_MAX_AGE_MS,
    AB_TEST_TARGET_LOTS,
    LOW_LATENCY_LIMIT_REPRICE_WAIT_MS,
    LOW_LATENCY_MAX_ABS_SPREAD_RS,
    LOW_LATENCY_MAX_QUOTE_AGE_MS,
    LOW_LATENCY_ORDER_POLL_MS,
    PAPER_MODE,
    PAPER_SLIPPAGE_TICKS,
    OPTION_BOOK_MAX_SLIPPAGE_RS,
    OPTION_BOOK_MAX_SPREAD_RS,
    OPTION_BOOK_PRICE_STEP_RS,
    OPTION_ENTRY_MAX_EXECUTION_MS,
    OPTION_ENTRY_STEP_WAIT_MS,
    OPTION_EXIT_MAX_EXECUTION_MS,
    OPTION_EXIT_STEP_WAIT_MS,
    OPTION_LIVE_ORDER_MAX_POLLS,
    OPTION_LIVE_ORDER_SETTLE_MS,
    OPTION_ORDER_POLL_MS,
    OPTION_ORDER_PRODUCT_TYPE,
    OPTION_ORDER_TIF,
    OPTION_ORDER_VARIETY,
)
from core.api_context import get_trading_api
from execution.angel_option_service import OptionContract, OptionQuote, angel_option_service
from execution.low_latency_limit_orders import (
    build_entry_limit_plan,
    build_exit_limit_plan,
    fallback_price_from_quote,
)
from monitoring.performance_monitor import performance_monitor


class ExecutionMode(Enum):
    TYPE_A = "TYPE_A"
    TYPE_B = "TYPE_B"
    TYPE_C = "TYPE_C"
    TYPE_D = "TYPE_D"
    TYPE_E = "TYPE_E"
    TYPE_F = "TYPE_F"

    @property
    def profile_name(self) -> str:
        if self == ExecutionMode.TYPE_A:
            return "MODERATE"
        if self == ExecutionMode.TYPE_B:
            return "AGGRESSIVE"
        if self == ExecutionMode.TYPE_C:
            return "HYBRID_ADAPTIVE"
        if self == ExecutionMode.TYPE_D:
            return "LIMIT_ORDER"
        if self == ExecutionMode.TYPE_E:
            return "ADAPTIVE_LIMIT_ORDER"
        return "BOOK_LADDER"


@dataclass(frozen=True)
class ExecutionParams:
    mode: ExecutionMode
    profile_name: str
    passive_end_ms: int
    controlled_end_ms: int
    ladder_end_ms: int
    force_end_ms: int
    ladder_depth: int
    passive_bias: float
    controlled_bias: float
    adaptive: bool
    skip_wide_spread: bool


@dataclass(frozen=True)
class ExecutionLevel:
    phase_name: str
    price: float
    wait_time_ms: int
    reason: str = ""


@dataclass(frozen=True)
class PricingSnapshot:
    quote: OptionQuote
    fair_value: float
    limit_price: float
    spread: float
    spread_pct: float
    quote_age_ms: float
    pricing_mode: str
    quote_source: str
    phase_name: str = ""


@dataclass(frozen=True)
class PendingOrder:
    order_id: str
    contract: OptionContract
    order_side: str
    quantity: int
    limit_price: float
    placed_at: datetime
    order_type: str = "LIMIT"
    variety: str = OPTION_ORDER_VARIETY


@dataclass(frozen=True)
class FillState:
    filled: bool
    fill_price: float = 0.0
    status: str = ""
    reason: str = ""
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ExecutionResult:
    filled: bool
    reason: str
    contract: Optional[OptionContract] = None
    quantity: int = 0
    order_side: str = ""
    fill_price: float = 0.0
    fair_value: float = 0.0
    initial_fair_value: float = 0.0
    limit_price: float = 0.0
    initial_limit_price: float = 0.0
    spread: float = 0.0
    spread_pct: float = 0.0
    quote_age_ms: float = 0.0
    pricing_mode: str = ""
    quote_source: str = ""
    quote: Optional[OptionQuote] = None
    total_elapsed_ms: float = 0.0
    order_id: str = ""
    reprice_order_id: str = ""
    repriced: bool = False
    execution_mode: str = ""
    execution_phase: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


def normalize_execution_mode(value: str | ExecutionMode | None) -> ExecutionMode:
    if isinstance(value, ExecutionMode):
        return value
    if isinstance(value, str):
        try:
            return ExecutionMode(str(value).upper())
        except ValueError:
            return ExecutionMode.TYPE_F
    return ExecutionMode.TYPE_F


def enabled_execution_modes() -> tuple[ExecutionMode, ...]:
    configured: list[ExecutionMode] = []
    for value in ACTIVE_EXECUTION_MODES:
        mode = normalize_execution_mode(value)
        if mode not in configured:
            configured.append(mode)
    return tuple(configured) if configured else (ExecutionMode.TYPE_B,)


def virtual_strategy_name(base_strategy_name: str, mode: str | ExecutionMode) -> str:
    resolved = normalize_execution_mode(mode)
    return f"{base_strategy_name}__{resolved.value}"


def execution_params_for_mode(mode: ExecutionMode) -> ExecutionParams:
    if mode == ExecutionMode.TYPE_A:
        return ExecutionParams(
            mode=ExecutionMode.TYPE_A,
            profile_name=ExecutionMode.TYPE_A.profile_name,
            passive_end_ms=8,
            controlled_end_ms=16,
            ladder_end_ms=28,
            force_end_ms=int(AB_TEST_ENTRY_DEADLINE_MS),
            ladder_depth=2,
            passive_bias=-0.15,
            controlled_bias=0.10,
            adaptive=False,
            skip_wide_spread=False,
        )
    if mode == ExecutionMode.TYPE_B:
        return ExecutionParams(
            mode=ExecutionMode.TYPE_B,
            profile_name=ExecutionMode.TYPE_B.profile_name,
            passive_end_ms=6,
            controlled_end_ms=16,
            ladder_end_ms=28,
            force_end_ms=int(AB_TEST_ENTRY_DEADLINE_MS),
            ladder_depth=4,
            passive_bias=0.25,
            controlled_bias=0.35,
            adaptive=False,
            skip_wide_spread=False,
        )
    if mode == ExecutionMode.TYPE_C:
        return ExecutionParams(
            mode=ExecutionMode.TYPE_C,
            profile_name=ExecutionMode.TYPE_C.profile_name,
            passive_end_ms=8,
            controlled_end_ms=18,
            ladder_end_ms=30,
            force_end_ms=int(AB_TEST_ENTRY_DEADLINE_MS),
            ladder_depth=3,
            passive_bias=0.05,
            controlled_bias=0.20,
            adaptive=True,
            skip_wide_spread=False,
        )
    if mode == ExecutionMode.TYPE_D:
        return ExecutionParams(
            mode=ExecutionMode.TYPE_D,
            profile_name=ExecutionMode.TYPE_D.profile_name,
            passive_end_ms=int(LOW_LATENCY_LIMIT_REPRICE_WAIT_MS),
            controlled_end_ms=int(LOW_LATENCY_LIMIT_REPRICE_WAIT_MS),
            ladder_end_ms=int(LOW_LATENCY_LIMIT_REPRICE_WAIT_MS),
            force_end_ms=int(AB_TEST_ENTRY_DEADLINE_MS),
            ladder_depth=2,
            passive_bias=0.0,
            controlled_bias=0.0,
            adaptive=False,
            skip_wide_spread=False,
        )
    if mode == ExecutionMode.TYPE_E:
        return ExecutionParams(
            mode=ExecutionMode.TYPE_E,
            profile_name=ExecutionMode.TYPE_E.profile_name,
            passive_end_ms=5,
            controlled_end_ms=13,
            ladder_end_ms=23,
            force_end_ms=int(AB_TEST_ENTRY_DEADLINE_MS),
            ladder_depth=7,
            passive_bias=0.0,
            controlled_bias=0.0,
            adaptive=True,
            skip_wide_spread=False,
        )
    return ExecutionParams(
        mode=ExecutionMode.TYPE_F,
        profile_name=ExecutionMode.TYPE_F.profile_name,
        passive_end_ms=int(OPTION_ENTRY_STEP_WAIT_MS),
        controlled_end_ms=int(OPTION_ENTRY_STEP_WAIT_MS) * 2,
        ladder_end_ms=int(OPTION_ENTRY_MAX_EXECUTION_MS),
        force_end_ms=int(OPTION_ENTRY_MAX_EXECUTION_MS),
        ladder_depth=4,
        passive_bias=0.0,
        controlled_bias=0.0,
        adaptive=False,
        skip_wide_spread=False,
    )


class _PaperOrderGateway:
    def place_limit_ioc(
        self,
        *,
        contract: OptionContract,
        order_side: str,
        quantity: int,
        limit_price: float,
        ts: datetime,
    ) -> PendingOrder:
        order_id = f"paper:{contract.token}:{uuid.uuid4().hex[:10]}"
        return PendingOrder(
            order_id=order_id,
            contract=contract,
            order_side=order_side,
            quantity=int(quantity),
            limit_price=float(limit_price),
            placed_at=ts,
            order_type="LIMIT",
        )

    def place_market(
        self,
        *,
        contract: OptionContract,
        order_side: str,
        quantity: int,
        ts: datetime,
    ) -> PendingOrder:
        order_id = f"paper:{contract.token}:{uuid.uuid4().hex[:10]}"
        return PendingOrder(
            order_id=order_id,
            contract=contract,
            order_side=order_side,
            quantity=int(quantity),
            limit_price=0.0,
            placed_at=ts,
            order_type="MARKET",
        )

    def wait_for_fill(self, order: PendingOrder, timeout_ms: int, poll_ms: int) -> FillState:
        deadline = perf_counter() + max(float(timeout_ms), 0.0) / 1000.0
        while perf_counter() < deadline:
            quote = angel_option_service.cached_quote(order.contract, max_age_ms=None)
            if quote is not None:
                if str(order.order_type).upper() == "MARKET":
                    fill_price = self._market_price(order, quote)
                else:
                    fill_price = self._cross_price(order, quote)
                if fill_price is not None:
                    return FillState(
                        filled=True,
                        fill_price=fill_price,
                        status="FILLED",
                        raw={"quote_ts": quote.ts.isoformat(), "source": quote.source},
                    )
            sleep(max(float(poll_ms), 1.0) / 1000.0)
        return FillState(filled=False, status="NO_FILL", reason="TIMEOUT")

    def cancel(self, order: PendingOrder) -> None:
        del order

    @staticmethod
    def _market_price(order: PendingOrder, quote: OptionQuote) -> Optional[float]:
        slip = max(int(PAPER_SLIPPAGE_TICKS), 0) * float(order.contract.tick_size or 0.05)

        if order.order_side == "BUY":
            reference = float(quote.ask or 0.0)
            if reference <= 0.0:
                return None
            return round(reference + slip, 2)

        reference = float(quote.bid or 0.0)
        if reference <= 0.0:
            return None
        return round(max(reference - slip, 0.0), 2)

    @staticmethod
    def _cross_price(order: PendingOrder, quote: OptionQuote) -> Optional[float]:
        if order.order_side == "BUY":
            ask = float(quote.ask or 0.0)
            if ask > 0.0 and float(order.limit_price) >= ask:
                return round(ask, 2)
            return None

        bid = float(quote.bid or 0.0)
        if bid > 0.0 and float(order.limit_price) <= bid:
            return round(bid, 2)
        return None


class _LiveAngelOrderGateway:
    def place_limit_ioc(
        self,
        *,
        contract: OptionContract,
        order_side: str,
        quantity: int,
        limit_price: float,
        ts: datetime,
    ) -> PendingOrder:
        del ts
        api = get_trading_api()
        if api is None:
            return PendingOrder("", contract, order_side, quantity, limit_price, datetime.now())

        payload = {
            "variety": OPTION_ORDER_VARIETY,
            "tradingsymbol": contract.symbol,
            "symboltoken": contract.token,
            "transactiontype": order_side,
            "exchange": contract.exchange,
            "ordertype": "LIMIT",
            "producttype": OPTION_ORDER_PRODUCT_TYPE,
            "duration": OPTION_ORDER_TIF,
            "price": f"{float(limit_price):.2f}",
            "quantity": str(int(quantity)),
        }
        started = perf_counter()
        order_id = api.placeOrder(payload)
        performance_monitor.on_api_call(
            service="angel",
            operation="place_limit_ioc",
            success=bool(order_id),
            elapsed_ms=(perf_counter() - started) * 1000.0,
            error="" if order_id else "place_order_failed",
        )
        return PendingOrder(
            order_id=str(order_id or ""),
            contract=contract,
            order_side=order_side,
            quantity=int(quantity),
            limit_price=float(limit_price),
            placed_at=datetime.now(),
        )

    def place_market(
        self,
        *,
        contract: OptionContract,
        order_side: str,
        quantity: int,
        ts: datetime,
    ) -> PendingOrder:
        del ts
        api = get_trading_api()
        if api is None:
            return PendingOrder("", contract, order_side, quantity, 0.0, datetime.now(), "MARKET")

        payload = {
            "variety": OPTION_ORDER_VARIETY,
            "tradingsymbol": contract.symbol,
            "symboltoken": contract.token,
            "transactiontype": order_side,
            "exchange": contract.exchange,
            "ordertype": "MARKET",
            "producttype": OPTION_ORDER_PRODUCT_TYPE,
            "duration": OPTION_ORDER_TIF,
            "quantity": str(int(quantity)),
        }
        started = perf_counter()
        order_id = api.placeOrder(payload)
        performance_monitor.on_api_call(
            service="angel",
            operation="place_market_order",
            success=bool(order_id),
            elapsed_ms=(perf_counter() - started) * 1000.0,
            error="" if order_id else "place_order_failed",
        )
        return PendingOrder(
            order_id=str(order_id or ""),
            contract=contract,
            order_side=order_side,
            quantity=int(quantity),
            limit_price=0.0,
            placed_at=datetime.now(),
            order_type="MARKET",
        )

    def wait_for_fill(self, order: PendingOrder, timeout_ms: int, poll_ms: int) -> FillState:
        if not order.order_id:
            return FillState(filled=False, status="REJECTED", reason="ORDER_ID_MISSING")

        del poll_ms
        deadline = perf_counter() + max(float(timeout_ms), 0.0) / 1000.0
        max_polls = max(int(OPTION_LIVE_ORDER_MAX_POLLS), 1)
        settle_s = max(float(OPTION_LIVE_ORDER_SETTLE_MS), 0.0) / 1000.0
        polls = 0

        while perf_counter() < deadline and polls < max_polls:
            remaining = max(deadline - perf_counter(), 0.0)
            if remaining <= 0.0:
                break
            sleep(max(min(settle_s, remaining), 0.001))
            snapshot = self._fetch_order_snapshot(order.order_id)
            polls += 1
            if snapshot:
                status = str(
                    snapshot.get("status")
                    or snapshot.get("orderstatus")
                    or snapshot.get("order_status")
                    or ""
                ).upper()
                filled_qty = self._filled_qty(snapshot)
                avg_price = self._avg_price(snapshot)
                if status in {"COMPLETE", "FILLED", "EXECUTED"} or filled_qty >= int(order.quantity):
                    return FillState(
                        filled=True,
                        fill_price=avg_price or float(order.limit_price),
                        status=status or "FILLED",
                        raw=dict(snapshot),
                    )
                if status in {"REJECTED", "CANCELLED", "CANCELED"}:
                    return FillState(
                        filled=False,
                        status=status,
                        reason=status,
                        raw=dict(snapshot),
                    )

        return FillState(filled=False, status="NO_FILL", reason="TIMEOUT")

    def cancel(self, order: PendingOrder) -> None:
        if not order.order_id:
            return
        api = get_trading_api()
        if api is None:
            return
        started = perf_counter()
        try:
            api.cancelOrder(order.order_id, order.variety)
            performance_monitor.on_api_call(
                service="angel",
                operation="cancel_order",
                success=True,
                elapsed_ms=(perf_counter() - started) * 1000.0,
            )
        except Exception as exc:
            performance_monitor.on_api_call(
                service="angel",
                operation="cancel_order",
                success=False,
                elapsed_ms=(perf_counter() - started) * 1000.0,
                error=str(exc),
            )

    def _fetch_order_snapshot(self, order_id: str) -> Dict[str, Any]:
        api = get_trading_api()
        if api is None:
            return {}

        started = perf_counter()
        try:
            response = api.individual_order_details(f"?orderid={order_id}")
            performance_monitor.on_api_call(
                service="angel",
                operation="individual_order_details",
                success=bool(response),
                elapsed_ms=(perf_counter() - started) * 1000.0,
            )
            snapshot = self._extract_order_snapshot(response, order_id)
            if snapshot:
                return snapshot
        except Exception as exc:
            performance_monitor.on_api_call(
                service="angel",
                operation="individual_order_details",
                success=False,
                elapsed_ms=(perf_counter() - started) * 1000.0,
                error=str(exc),
            )
            return {}
        return {}

    def _extract_order_snapshot(self, response: Any, order_id: str) -> Dict[str, Any]:
        if not isinstance(response, dict):
            return {}
        data = response.get("data")
        if isinstance(data, dict):
            candidate_id = str(data.get("orderid") or data.get("order_id") or "")
            if candidate_id == str(order_id):
                return dict(data)
        if isinstance(data, list):
            for item in data:
                candidate_id = str(item.get("orderid") or item.get("order_id") or "")
                if candidate_id == str(order_id):
                    return dict(item)
        return {}

    @staticmethod
    def _filled_qty(snapshot: Dict[str, Any]) -> int:
        for key in ("filledshares", "filled_qty", "filledsharesquantity", "filledquantity"):
            value = snapshot.get(key)
            if value is not None:
                try:
                    return int(float(value))
                except (TypeError, ValueError):
                    continue
        return 0

    @staticmethod
    def _avg_price(snapshot: Dict[str, Any]) -> float:
        for key in ("averageprice", "average_price", "avgprice", "avg_price", "price"):
            value = snapshot.get(key)
            if value is not None:
                try:
                    price = float(value)
                except (TypeError, ValueError):
                    continue
                if not math.isnan(price) and not math.isinf(price):
                    return price
        return 0.0


class OptionExecutionEngine:
    def __init__(self) -> None:
        self._paper_gateway = _PaperOrderGateway()
        self._live_gateway = _LiveAngelOrderGateway()

    def execute_entry(
        self,
        *,
        underlying_symbol: str,
        signal_side: str,
        underlying_price: float,
        ts: datetime,
        execution_mode: str | ExecutionMode | None = None,
        option_bucket: str = "ITM1",
    ) -> ExecutionResult:
        contract = angel_option_service.resolve_option_contract(
            underlying_symbol,
            signal_side,
            underlying_price,
            ts,
            option_bucket=option_bucket,
        )
        if contract is None:
            return ExecutionResult(
                filled=False,
                reason="OPTION_RESOLVE_FAILED",
                total_elapsed_ms=0.0,
            )
        quantity = int(contract.lot_size) * int(angel_option_service.option_lots_per_trade())
        return self._execute(
            contract=contract,
            order_side="BUY",
            quantity=quantity,
            underlying_price=underlying_price,
            ts=ts,
            reason_prefix="ENTRY",
            execution_mode=execution_mode,
        )

    def execute_exit(
        self,
        *,
        contract: OptionContract,
        quantity: int,
        underlying_price: float,
        ts: datetime,
        execution_mode: str | ExecutionMode | None = None,
    ) -> ExecutionResult:
        return self._execute(
            contract=contract,
            order_side="SELL",
            quantity=int(quantity),
            underlying_price=underlying_price,
            ts=ts,
            reason_prefix="EXIT",
            execution_mode=execution_mode,
        )

    def _execute(
        self,
        *,
        contract: OptionContract,
        order_side: str,
        quantity: int,
        underlying_price: float,
        ts: datetime,
        reason_prefix: str,
        execution_mode: str | ExecutionMode | None,
    ) -> ExecutionResult:
        mode = normalize_execution_mode(execution_mode)
        if mode == ExecutionMode.TYPE_F:
            return self._execute_type_f(
                contract=contract,
                order_side=order_side,
                quantity=quantity,
                underlying_price=underlying_price,
                ts=ts,
                reason_prefix=reason_prefix,
                execution_mode=mode,
            )
        if mode == ExecutionMode.TYPE_D:
            return self._execute_type_d(
                contract=contract,
                order_side=order_side,
                quantity=quantity,
                ts=ts,
                execution_mode=mode,
            )
        if mode == ExecutionMode.TYPE_E:
            return self._execute_type_e(
                contract=contract,
                order_side=order_side,
                quantity=quantity,
                ts=ts,
                execution_mode=mode,
            )
        return self._execute_type_abc(
            contract=contract,
            order_side=order_side,
            quantity=quantity,
            ts=ts,
            execution_mode=mode,
        )

    def _execute_type_f(
        self,
        *,
        contract: OptionContract,
        order_side: str,
        quantity: int,
        underlying_price: float,
        ts: datetime,
        reason_prefix: str,
        execution_mode: ExecutionMode,
    ) -> ExecutionResult:
        del underlying_price
        started = perf_counter()
        gateway = self._paper_gateway if PAPER_MODE else self._live_gateway
        pricing_started = perf_counter()
        initial_book = self._book_snapshot(contract=contract, ts=ts)
        performance_monitor.on_stage("option_pricing", (perf_counter() - pricing_started) * 1000.0)
        if initial_book is None:
            return ExecutionResult(
                filled=False,
                reason=f"{reason_prefix}_BOOK_UNAVAILABLE",
                contract=contract,
                quantity=quantity,
                order_side=order_side,
                total_elapsed_ms=(perf_counter() - started) * 1000.0,
            )

        initial_pricing = self._pricing_for_step(
            book=initial_book,
            contract=contract,
            order_side=order_side,
            step_index=0,
        )
        if initial_pricing is None:
            return ExecutionResult(
                filled=False,
                reason=f"{reason_prefix}_BOOK_UNAVAILABLE",
                contract=contract,
                quantity=quantity,
                order_side=order_side,
                total_elapsed_ms=(perf_counter() - started) * 1000.0,
            )

        is_entry = reason_prefix == "ENTRY"
        if is_entry and initial_pricing.spread > float(OPTION_BOOK_MAX_SPREAD_RS):
            return ExecutionResult(
                filled=False,
                reason="SPREAD_TOO_WIDE",
                contract=contract,
                quantity=quantity,
                order_side=order_side,
                fair_value=initial_pricing.fair_value,
                initial_fair_value=initial_pricing.fair_value,
                limit_price=initial_pricing.limit_price,
                initial_limit_price=initial_pricing.limit_price,
                spread=initial_pricing.spread,
                spread_pct=initial_pricing.spread_pct,
                quote_age_ms=initial_pricing.quote_age_ms,
                pricing_mode=initial_pricing.pricing_mode,
                quote_source=initial_pricing.quote_source,
                quote=initial_pricing.quote,
                total_elapsed_ms=(perf_counter() - started) * 1000.0,
            )

        if is_entry and not self._book_has_depth(initial_book, order_side):
            return ExecutionResult(
                filled=False,
                reason="THIN_ORDER_BOOK",
                contract=contract,
                quantity=quantity,
                order_side=order_side,
                fair_value=initial_pricing.fair_value,
                initial_fair_value=initial_pricing.fair_value,
                limit_price=initial_pricing.limit_price,
                initial_limit_price=initial_pricing.limit_price,
                spread=initial_pricing.spread,
                spread_pct=initial_pricing.spread_pct,
                quote_age_ms=initial_pricing.quote_age_ms,
                pricing_mode=initial_pricing.pricing_mode,
                quote_source=initial_pricing.quote_source,
                quote=initial_pricing.quote,
                total_elapsed_ms=(perf_counter() - started) * 1000.0,
            )

        step_wait_ms = int(OPTION_ENTRY_STEP_WAIT_MS if is_entry else OPTION_EXIT_STEP_WAIT_MS)
        total_budget_ms = int(OPTION_ENTRY_MAX_EXECUTION_MS if is_entry else OPTION_EXIT_MAX_EXECUTION_MS)
        max_steps = 4 if order_side == "BUY" else 3
        deadline = started + (max(float(total_budget_ms), 1.0) / 1000.0)
        expected_price = float(initial_pricing.fair_value)
        first_order_id = ""
        last_pricing = initial_pricing
        step_index = 0

        while step_index < max_steps:
            if is_entry and perf_counter() >= deadline and step_index < (max_steps - 1):
                step_index = max_steps - 1

            if step_index == 0:
                current_book = initial_book
                current_pricing = initial_pricing
            else:
                pricing_started = perf_counter()
                current_book = self._book_snapshot(contract=contract, ts=datetime.now())
                performance_monitor.on_stage("option_pricing", (perf_counter() - pricing_started) * 1000.0)
                if current_book is None:
                    break
                if is_entry and current_book.spread > float(OPTION_BOOK_MAX_SPREAD_RS):
                    return ExecutionResult(
                        filled=False,
                        reason="SPREAD_TOO_WIDE",
                        contract=contract,
                        quantity=quantity,
                        order_side=order_side,
                        fair_value=expected_price,
                        initial_fair_value=expected_price,
                        limit_price=last_pricing.limit_price,
                        initial_limit_price=initial_pricing.limit_price,
                        spread=current_book.spread,
                        spread_pct=current_book.spread_pct,
                        quote_age_ms=current_book.quote_age_ms,
                        pricing_mode=current_book.pricing_mode,
                        quote_source=current_book.quote_source,
                        quote=current_book.quote,
                        total_elapsed_ms=(perf_counter() - started) * 1000.0,
                    )
                current_pricing = self._pricing_for_step(
                    book=current_book,
                    contract=contract,
                    order_side=order_side,
                    step_index=step_index,
                    expected_price=expected_price,
                )
                if current_pricing is None:
                    break
                last_pricing = current_pricing

            if is_entry and self._slippage_exceeded(order_side, current_pricing.limit_price, expected_price):
                return ExecutionResult(
                    filled=False,
                    reason="SLIPPAGE_LIMIT_EXCEEDED",
                    contract=contract,
                    quantity=quantity,
                    order_side=order_side,
                    fair_value=expected_price,
                    initial_fair_value=expected_price,
                    limit_price=current_pricing.limit_price,
                    initial_limit_price=initial_pricing.limit_price,
                    spread=current_pricing.spread,
                    spread_pct=current_pricing.spread_pct,
                    quote_age_ms=current_pricing.quote_age_ms,
                    pricing_mode=current_pricing.pricing_mode,
                    quote_source=current_pricing.quote_source,
                    quote=current_pricing.quote,
                    total_elapsed_ms=(perf_counter() - started) * 1000.0,
                )

            order_started = perf_counter()
            order = gateway.place_limit_ioc(
                contract=contract,
                order_side=order_side,
                quantity=quantity,
                limit_price=current_pricing.limit_price,
                ts=datetime.now(),
            )
            if not first_order_id:
                first_order_id = order.order_id
            fill = gateway.wait_for_fill(
                order,
                timeout_ms=self._step_timeout_ms(deadline, step_wait_ms),
                poll_ms=int(OPTION_ORDER_POLL_MS),
            )
            performance_monitor.on_stage("option_order_monitoring", (perf_counter() - order_started) * 1000.0)
            if fill.filled:
                return self._filled_result(
                    contract=contract,
                    quantity=quantity,
                    order_side=order_side,
                    pricing=current_pricing,
                    fill=fill,
                    total_elapsed_ms=(perf_counter() - started) * 1000.0,
                    order_id=first_order_id or order.order_id,
                    repriced=step_index > 0,
                    initial_pricing=initial_pricing,
                    reprice_order_id=order.order_id if step_index > 0 else "",
                    execution_mode=execution_mode,
                )
            step_index += 1

        if not is_entry:
            pricing_started = perf_counter()
            market_book = self._book_snapshot(contract=contract, ts=datetime.now()) or initial_book
            performance_monitor.on_stage("option_pricing", (perf_counter() - pricing_started) * 1000.0)
            market_pricing = self._pricing_for_market(
                book=market_book,
                contract=contract,
                order_side=order_side,
                expected_price=expected_price,
            )
            market_order = gateway.place_market(
                contract=contract,
                order_side=order_side,
                quantity=quantity,
                ts=datetime.now(),
            )
            market_fill = gateway.wait_for_fill(
                market_order,
                timeout_ms=max(step_wait_ms, 1),
                poll_ms=int(OPTION_ORDER_POLL_MS),
            )
            if market_fill.filled:
                return self._filled_result(
                    contract=contract,
                    quantity=quantity,
                    order_side=order_side,
                    pricing=market_pricing,
                    fill=market_fill,
                    total_elapsed_ms=(perf_counter() - started) * 1000.0,
                    order_id=first_order_id or market_order.order_id,
                    repriced=True,
                    initial_pricing=initial_pricing,
                    reprice_order_id=market_order.order_id,
                    execution_mode=execution_mode,
                )
            return ExecutionResult(
                filled=False,
                reason="FORCED_EXIT_MARKET_FAILED",
                contract=contract,
                quantity=quantity,
                order_side=order_side,
                fair_value=market_pricing.fair_value,
                initial_fair_value=initial_pricing.fair_value,
                limit_price=market_pricing.limit_price,
                initial_limit_price=initial_pricing.limit_price,
                spread=market_pricing.spread,
                spread_pct=market_pricing.spread_pct,
                quote_age_ms=market_pricing.quote_age_ms,
                pricing_mode=market_pricing.pricing_mode,
                quote_source=market_pricing.quote_source,
                quote=market_pricing.quote,
                total_elapsed_ms=(perf_counter() - started) * 1000.0,
                order_id=first_order_id or market_order.order_id,
            )

        return ExecutionResult(
            filled=False,
            reason="NO_FILL_AFTER_FINAL_STEP",
            contract=contract,
            quantity=quantity,
            order_side=order_side,
            fair_value=expected_price,
            initial_fair_value=initial_pricing.fair_value,
            limit_price=last_pricing.limit_price,
            initial_limit_price=initial_pricing.limit_price,
            spread=last_pricing.spread,
            spread_pct=last_pricing.spread_pct,
            quote_age_ms=last_pricing.quote_age_ms,
            pricing_mode=last_pricing.pricing_mode,
            quote_source=last_pricing.quote_source,
            quote=last_pricing.quote,
            total_elapsed_ms=(perf_counter() - started) * 1000.0,
            order_id=first_order_id,
        )

    def _execute_type_abc(
        self,
        *,
        contract: OptionContract,
        order_side: str,
        quantity: int,
        ts: datetime,
        execution_mode: ExecutionMode,
    ) -> ExecutionResult:
        started = perf_counter()
        params = execution_params_for_mode(execution_mode)
        quote = self._quote_for_execution(contract, ts, max_age_ms=float(AB_TEST_QUOTE_MAX_AGE_MS))
        if quote is None:
            return self._empty_result(
                contract=contract,
                quantity=quantity,
                order_side=order_side,
                reason="QUOTE_UNAVAILABLE",
                total_elapsed_ms=(perf_counter() - started) * 1000.0,
                execution_mode=execution_mode,
            )

        metrics = self._microstructure_snapshot(quote, contract)
        spread = float(metrics["spread"])
        quote_age_ms = max((datetime.now() - quote.ts).total_seconds() * 1000.0, 0.0)
        if float(AB_TEST_MAX_SPREAD_RS or 0.0) > 0.0 and spread > float(AB_TEST_MAX_SPREAD_RS):
            return self._empty_result(
                contract=contract,
                quantity=quantity,
                order_side=order_side,
                reason="SPREAD_TOO_WIDE",
                fair_value=float(metrics["fair_price"]),
                initial_fair_value=float(metrics["fair_price"]),
                spread=spread,
                spread_pct=(spread / float(metrics["mid"])) if float(metrics["mid"]) > 0.0 else 0.0,
                quote_age_ms=quote_age_ms,
                pricing_mode=f"{execution_mode.value.lower()}_ladder",
                quote_source=quote.source,
                quote=quote,
                total_elapsed_ms=(perf_counter() - started) * 1000.0,
                execution_mode=execution_mode,
            )
        if float(AB_TEST_QUOTE_MAX_AGE_MS) > 0.0 and quote_age_ms > float(AB_TEST_QUOTE_MAX_AGE_MS):
            return self._empty_result(
                contract=contract,
                quantity=quantity,
                order_side=order_side,
                reason="QUOTE_TOO_STALE",
                fair_value=float(metrics["fair_price"]),
                initial_fair_value=float(metrics["fair_price"]),
                spread=spread,
                spread_pct=(spread / float(metrics["mid"])) if float(metrics["mid"]) > 0.0 else 0.0,
                quote_age_ms=quote_age_ms,
                pricing_mode=f"{execution_mode.value.lower()}_ladder",
                quote_source=quote.source,
                quote=quote,
                total_elapsed_ms=(perf_counter() - started) * 1000.0,
                execution_mode=execution_mode,
            )

        ladder = self._build_execution_ladder(
            contract=contract,
            quantity=quantity,
            params=params,
            order_side=order_side,
            metrics=metrics,
        )
        last_quote = quote
        orders: list[dict[str, Any]] = []
        last_phase = "NONE"
        filled_qty = 0
        filled_value = 0.0

        for index, level in enumerate(ladder, start=1):
            fill = self._attempt_level(
                contract=contract,
                order_side=order_side,
                level=level,
                quantity=quantity,
                max_quote_age_ms=float(AB_TEST_QUOTE_MAX_AGE_MS),
                poll_ms=int(LOW_LATENCY_ORDER_POLL_MS),
            )
            observed_quote = fill.get("quote")
            if isinstance(observed_quote, OptionQuote):
                last_quote = observed_quote
            fill_qty = int(fill.get("fill_qty", 0) or 0)
            fill_price = float(fill.get("fill_price", 0.0) or 0.0)
            last_phase = level.phase_name
            orders.append(
                {
                    "level": index,
                    "phase": level.phase_name,
                    "price": round(float(level.price), 2),
                    "quantity": int(quantity),
                    "fill_qty": fill_qty,
                    "fill_price": round(fill_price, 2),
                    "wait_time_ms": int(level.wait_time_ms),
                    "status": str(fill.get("status", "")),
                    "reason": level.reason,
                }
            )
            if fill_qty >= int(quantity):
                filled_qty = fill_qty
                filled_value = fill_qty * fill_price
                break

        return self._result_from_ladder(
            contract=contract,
            quantity=quantity,
            order_side=order_side,
            quote=last_quote,
            filled_qty=filled_qty,
            filled_value=filled_value,
            orders=orders,
            last_phase=last_phase,
            pricing_mode=f"{execution_mode.value.lower()}_ladder",
            total_elapsed_ms=(perf_counter() - started) * 1000.0,
            execution_mode=execution_mode,
            reason="FILLED" if filled_qty >= int(quantity) else "NO_FILL",
        )

    def _execute_type_d(
        self,
        *,
        contract: OptionContract,
        order_side: str,
        quantity: int,
        ts: datetime,
        execution_mode: ExecutionMode,
    ) -> ExecutionResult:
        started = perf_counter()
        quote = self._quote_for_execution(contract, ts, max_age_ms=float(LOW_LATENCY_MAX_QUOTE_AGE_MS))
        if quote is None:
            return self._empty_result(
                contract=contract,
                quantity=quantity,
                order_side=order_side,
                reason="QUOTE_UNAVAILABLE",
                total_elapsed_ms=(perf_counter() - started) * 1000.0,
                execution_mode=execution_mode,
            )

        metrics = self._microstructure_snapshot(quote, contract)
        quote_age_ms = max((datetime.now() - quote.ts).total_seconds() * 1000.0, 0.0)
        tick = float(metrics["tick"])
        if order_side == "BUY":
            plan = build_entry_limit_plan(
                bid=float(metrics["bid"]),
                ask=float(metrics["ask"]),
                ltp=float(metrics["ltp"]),
                tick=tick,
                quote_age_ms=quote_age_ms,
                max_spread=float(LOW_LATENCY_MAX_ABS_SPREAD_RS),
                max_quote_age_ms=float(LOW_LATENCY_MAX_QUOTE_AGE_MS),
                wait_ms=int(LOW_LATENCY_LIMIT_REPRICE_WAIT_MS),
                poll_ms=int(LOW_LATENCY_ORDER_POLL_MS),
            )
            first_phase = "LIMIT_ENTRY"
            fallback_phase = "ASK_FALLBACK"
        else:
            plan = build_exit_limit_plan(
                entry_price=float(metrics["ltp"]),
                bid=float(metrics["bid"]),
                ask=float(metrics["ask"]),
                ltp=float(metrics["ltp"]),
                tick=tick,
                quote_age_ms=quote_age_ms,
                max_spread=float(LOW_LATENCY_MAX_ABS_SPREAD_RS),
                max_quote_age_ms=float(LOW_LATENCY_MAX_QUOTE_AGE_MS),
                wait_ms=int(LOW_LATENCY_LIMIT_REPRICE_WAIT_MS),
                poll_ms=int(LOW_LATENCY_ORDER_POLL_MS),
            )
            first_phase = "LIMIT_EXIT"
            fallback_phase = "BID_FALLBACK"

        if plan.skip_reason:
            return self._empty_result(
                contract=contract,
                quantity=quantity,
                order_side=order_side,
                reason=plan.skip_reason,
                fair_value=float(plan.fair_value),
                initial_fair_value=float(plan.fair_value),
                spread=float(plan.spread),
                spread_pct=(float(plan.spread) / float(metrics["mid"])) if float(metrics["mid"]) > 0.0 else 0.0,
                quote_age_ms=quote_age_ms,
                pricing_mode=plan.pricing_mode,
                quote_source=quote.source,
                quote=quote,
                total_elapsed_ms=(perf_counter() - started) * 1000.0,
                execution_mode=execution_mode,
                execution_phase=first_phase,
            )

        levels = [
            ExecutionLevel(
                phase_name=first_phase,
                price=self._round_price(float(plan.first_price), tick, order_side),
                wait_time_ms=int(plan.wait_ms),
                reason=f"{execution_mode.value} {order_side} {first_phase}",
            ),
            ExecutionLevel(
                phase_name=fallback_phase,
                price=self._round_price(
                    float(
                        fallback_price_from_quote(
                            target=plan.fallback_target,
                            bid=float(metrics["bid"]),
                            ask=float(metrics["ask"]),
                            ltp=float(metrics["ltp"]),
                            tick=tick,
                        )
                    ),
                    tick,
                    order_side,
                ),
                wait_time_ms=int(plan.wait_ms),
                reason=f"{execution_mode.value} {order_side} {fallback_phase}",
            ),
        ]
        last_quote = quote
        orders: list[dict[str, Any]] = []
        last_phase = first_phase
        filled_qty = 0
        filled_value = 0.0

        for index, level in enumerate(levels, start=1):
            fill = self._attempt_level(
                contract=contract,
                order_side=order_side,
                level=level,
                quantity=quantity,
                max_quote_age_ms=float(LOW_LATENCY_MAX_QUOTE_AGE_MS),
                poll_ms=int(LOW_LATENCY_ORDER_POLL_MS),
            )
            observed_quote = fill.get("quote")
            if isinstance(observed_quote, OptionQuote):
                last_quote = observed_quote
            fill_qty = int(fill.get("fill_qty", 0) or 0)
            fill_price = float(fill.get("fill_price", 0.0) or 0.0)
            last_phase = level.phase_name
            orders.append(
                {
                    "level": index,
                    "phase": level.phase_name,
                    "price": round(float(level.price), 2),
                    "quantity": int(quantity),
                    "fill_qty": fill_qty,
                    "fill_price": round(fill_price, 2),
                    "wait_time_ms": int(level.wait_time_ms),
                    "status": str(fill.get("status", "")),
                    "reason": level.reason,
                }
            )
            if fill_qty >= int(quantity):
                filled_qty = fill_qty
                filled_value = fill_qty * fill_price
                break

        return self._result_from_ladder(
            contract=contract,
            quantity=quantity,
            order_side=order_side,
            quote=last_quote,
            filled_qty=filled_qty,
            filled_value=filled_value,
            orders=orders,
            last_phase=last_phase,
            pricing_mode=plan.pricing_mode,
            total_elapsed_ms=(perf_counter() - started) * 1000.0,
            execution_mode=execution_mode,
            reason="FILLED" if filled_qty >= int(quantity) else "NO_FILL_AFTER_FALLBACK",
        )

    def _execute_type_e(
        self,
        *,
        contract: OptionContract,
        order_side: str,
        quantity: int,
        ts: datetime,
        execution_mode: ExecutionMode,
    ) -> ExecutionResult:
        started = perf_counter()
        quote = self._quote_for_execution(contract, ts, max_age_ms=float(LOW_LATENCY_MAX_QUOTE_AGE_MS))
        if quote is None:
            return self._empty_result(
                contract=contract,
                quantity=quantity,
                order_side=order_side,
                reason="QUOTE_UNAVAILABLE",
                total_elapsed_ms=(perf_counter() - started) * 1000.0,
                execution_mode=execution_mode,
            )

        tick = max(float(contract.tick_size or 0.05), 0.05)
        metrics = self._microstructure_snapshot(quote, contract)
        fair = float(metrics["mid"] or metrics["fair_price"] or metrics["ltp"])
        spread = float(metrics["spread"])
        spread_pct = (spread / fair) if fair > 0.0 else 0.0
        if (float(LOW_LATENCY_MAX_ABS_SPREAD_RS or 0.0) > 0.0 and spread > float(LOW_LATENCY_MAX_ABS_SPREAD_RS)) or spread_pct > 0.005:
            return self._empty_result(
                contract=contract,
                quantity=quantity,
                order_side=order_side,
                reason="SPREAD_TOO_WIDE",
                fair_value=fair,
                initial_fair_value=fair,
                spread=spread,
                spread_pct=spread_pct,
                quote_age_ms=max((datetime.now() - quote.ts).total_seconds() * 1000.0, 0.0),
                pricing_mode="adaptive_limit_order",
                quote_source=quote.source,
                quote=quote,
                total_elapsed_ms=(perf_counter() - started) * 1000.0,
                execution_mode=execution_mode,
                execution_phase="SKIP",
            )

        if order_side == "BUY":
            controlled = min(max(float(metrics["microprice"]), float(metrics["bid"]) + tick), float(metrics["ask"]))
            raw_levels = [
                ("MID_ENTRY", fair + tick, 5),
                ("MID_PLUS_25", fair + (0.25 * spread), 8),
                ("CONTROLLED", controlled, 10),
                ("MID_PLUS_75", fair + (0.75 * spread), 10),
                ("LADDER", float(metrics["ask"]) + tick, 12),
                ("ASK_FALLBACK", float(metrics["ask"]), 12),
                ("ASK_ENTRY", float(metrics["ask"]), 15),
            ]
        else:
            raw_levels = [
                ("MICROPRICE_EXIT", float(metrics["microprice"]), 3),
                ("HIT_BID", float(metrics["bid"]), 5),
                ("BID_EXIT_STAGE1", float(metrics["bid"]), 5),
                ("BID_MINUS_1TICK", max(float(metrics["bid"]) - tick, tick), 5),
                ("CONTROLLED_EXIT", max(float(metrics["bid"]) - tick, tick), 5),
                ("FORCED_EXIT", max(float(metrics["bid"]) - (4.0 * tick), tick), 10),
            ]

        levels = [
            ExecutionLevel(
                phase_name=label,
                price=self._round_price(float(price), tick, order_side),
                wait_time_ms=int(wait_ms),
                reason=f"{execution_mode.value} {order_side} {label}",
            )
            for label, price, wait_ms in raw_levels
        ]

        last_quote = quote
        orders: list[dict[str, Any]] = []
        last_phase = "NONE"
        filled_qty = 0
        filled_value = 0.0

        for index, level in enumerate(levels, start=1):
            fill = self._attempt_level(
                contract=contract,
                order_side=order_side,
                level=level,
                quantity=quantity,
                max_quote_age_ms=float(LOW_LATENCY_MAX_QUOTE_AGE_MS),
                poll_ms=int(LOW_LATENCY_ORDER_POLL_MS),
            )
            observed_quote = fill.get("quote")
            if isinstance(observed_quote, OptionQuote):
                last_quote = observed_quote
            fill_qty = int(fill.get("fill_qty", 0) or 0)
            fill_price = float(fill.get("fill_price", 0.0) or 0.0)
            last_phase = level.phase_name
            orders.append(
                {
                    "level": index,
                    "phase": level.phase_name,
                    "price": round(float(level.price), 2),
                    "quantity": int(quantity),
                    "fill_qty": fill_qty,
                    "fill_price": round(fill_price, 2),
                    "wait_time_ms": int(level.wait_time_ms),
                    "status": str(fill.get("status", "")),
                    "reason": level.reason,
                }
            )
            if fill_qty >= int(quantity):
                filled_qty = fill_qty
                filled_value = fill_qty * fill_price
                break

        return self._result_from_ladder(
            contract=contract,
            quantity=quantity,
            order_side=order_side,
            quote=last_quote,
            filled_qty=filled_qty,
            filled_value=filled_value,
            orders=orders,
            last_phase=last_phase,
            pricing_mode="adaptive_limit_order",
            total_elapsed_ms=(perf_counter() - started) * 1000.0,
            execution_mode=execution_mode,
            reason="FILLED" if filled_qty >= int(quantity) else (f"NO_FILL_AFTER_{last_phase}" if last_phase != "NONE" else "NO_FILL"),
        )

    def _filled_result(
        self,
        *,
        contract: OptionContract,
        quantity: int,
        order_side: str,
        pricing: PricingSnapshot,
        fill: FillState,
        total_elapsed_ms: float,
        order_id: str,
        repriced: bool,
        initial_pricing: PricingSnapshot,
        reprice_order_id: str = "",
        execution_mode: ExecutionMode = ExecutionMode.TYPE_F,
    ) -> ExecutionResult:
        return ExecutionResult(
            filled=True,
            reason=fill.status or "FILLED",
            contract=contract,
            quantity=quantity,
            order_side=order_side,
            fill_price=float(fill.fill_price),
            fair_value=pricing.fair_value,
            initial_fair_value=initial_pricing.fair_value,
            limit_price=pricing.limit_price,
            initial_limit_price=initial_pricing.limit_price,
            spread=pricing.spread,
            spread_pct=pricing.spread_pct,
            quote_age_ms=pricing.quote_age_ms,
            pricing_mode=pricing.pricing_mode,
            quote_source=pricing.quote_source,
            quote=pricing.quote,
            total_elapsed_ms=total_elapsed_ms,
            order_id=order_id,
            reprice_order_id=reprice_order_id,
            repriced=repriced,
            execution_mode=execution_mode.value,
            execution_phase=pricing.phase_name,
            metadata={
                "fill_status": fill.status,
                "fill_raw": dict(fill.raw),
                "profile_name": execution_mode.profile_name,
            },
        )

    def _result_from_ladder(
        self,
        *,
        contract: OptionContract,
        quantity: int,
        order_side: str,
        quote: OptionQuote,
        filled_qty: int,
        filled_value: float,
        orders: list[dict[str, Any]],
        last_phase: str,
        pricing_mode: str,
        total_elapsed_ms: float,
        execution_mode: ExecutionMode,
        reason: str,
    ) -> ExecutionResult:
        metrics = self._microstructure_snapshot(quote, contract)
        average_fill_price = (filled_value / filled_qty) if filled_qty > 0 else 0.0
        fair_value = float(metrics["fair_price"])
        spread = float(metrics["spread"])
        mid = float(metrics["mid"])
        return ExecutionResult(
            filled=int(filled_qty) >= int(quantity),
            reason=reason,
            contract=contract,
            quantity=int(quantity),
            order_side=order_side,
            fill_price=round(float(average_fill_price), 2),
            fair_value=fair_value,
            initial_fair_value=fair_value,
            limit_price=float(orders[-1]["price"]) if orders else 0.0,
            initial_limit_price=float(orders[0]["price"]) if orders else 0.0,
            spread=spread,
            spread_pct=(spread / mid) if mid > 0.0 else 0.0,
            quote_age_ms=max((datetime.now() - quote.ts).total_seconds() * 1000.0, 0.0),
            pricing_mode=pricing_mode,
            quote_source=quote.source,
            quote=quote,
            total_elapsed_ms=total_elapsed_ms,
            repriced=len(orders) > 1,
            execution_mode=execution_mode.value,
            execution_phase=last_phase,
            metadata={
                "orders": list(orders),
                "filled_qty": int(filled_qty),
                "target_qty": int(quantity),
                "profile_name": execution_mode.profile_name,
                "partial_fill": int(filled_qty) > 0 and int(filled_qty) < int(quantity),
            },
        )

    def _empty_result(
        self,
        *,
        contract: Optional[OptionContract],
        quantity: int,
        order_side: str,
        reason: str,
        fair_value: float = 0.0,
        initial_fair_value: float = 0.0,
        limit_price: float = 0.0,
        initial_limit_price: float = 0.0,
        spread: float = 0.0,
        spread_pct: float = 0.0,
        quote_age_ms: float = 0.0,
        pricing_mode: str = "",
        quote_source: str = "",
        quote: Optional[OptionQuote] = None,
        total_elapsed_ms: float = 0.0,
        order_id: str = "",
        execution_mode: ExecutionMode = ExecutionMode.TYPE_F,
        execution_phase: str = "",
    ) -> ExecutionResult:
        return ExecutionResult(
            filled=False,
            reason=reason,
            contract=contract,
            quantity=int(quantity),
            order_side=order_side,
            fair_value=float(fair_value),
            initial_fair_value=float(initial_fair_value or fair_value),
            limit_price=float(limit_price),
            initial_limit_price=float(initial_limit_price or limit_price),
            spread=float(spread),
            spread_pct=float(spread_pct),
            quote_age_ms=float(quote_age_ms),
            pricing_mode=pricing_mode,
            quote_source=quote_source,
            quote=quote,
            total_elapsed_ms=float(total_elapsed_ms),
            order_id=order_id,
            execution_mode=execution_mode.value,
            execution_phase=execution_phase,
            metadata={"profile_name": execution_mode.profile_name},
        )

    def _book_snapshot(
        self,
        *,
        contract: OptionContract,
        ts: datetime,
    ) -> Optional[PricingSnapshot]:
        quote = angel_option_service.quote_contract(contract, ts, force_refresh=False)
        if quote is None:
            return None

        bid = float(quote.bid or 0.0)
        ask = float(quote.ask or 0.0)
        if bid <= 0.0 or ask <= 0.0 or ask < bid:
            return None

        mid_price = (bid + ask) / 2.0
        spread = max(ask - bid, 0.0)
        quote_age_ms = max((datetime.now() - quote.ts).total_seconds() * 1000.0, 0.0)
        spread_pct = (spread / mid_price) if mid_price > 0.0 else float("inf")
        return PricingSnapshot(
            quote=quote,
            fair_value=mid_price,
            limit_price=mid_price,
            spread=spread,
            spread_pct=spread_pct,
            quote_age_ms=quote_age_ms,
            pricing_mode="order_book",
            quote_source=quote.source,
            phase_name="BOOK_ENTRY_1",
        )

    def _pricing_for_step(
        self,
        *,
        book: PricingSnapshot,
        contract: OptionContract,
        order_side: str,
        step_index: int,
        expected_price: Optional[float] = None,
    ) -> Optional[PricingSnapshot]:
        price_levels = (
            self._entry_price_levels(book, float(contract.tick_size or 0.05))
            if order_side == "BUY"
            else self._exit_price_levels(book, float(contract.tick_size or 0.05))
        )
        if not price_levels or step_index >= len(price_levels):
            return None

        expected = float(expected_price if expected_price is not None else price_levels[0])
        phase_name = f"BOOK_ENTRY_{step_index + 1}" if order_side == "BUY" else f"BOOK_EXIT_{step_index + 1}"
        return PricingSnapshot(
            quote=book.quote,
            fair_value=expected,
            limit_price=float(price_levels[step_index]),
            spread=book.spread,
            spread_pct=book.spread_pct,
            quote_age_ms=book.quote_age_ms,
            pricing_mode="book_ladder",
            quote_source=book.quote_source,
            phase_name=phase_name,
        )

    def _pricing_for_market(
        self,
        *,
        book: PricingSnapshot,
        contract: OptionContract,
        order_side: str,
        expected_price: float,
    ) -> PricingSnapshot:
        del contract
        final_price = float(book.quote.ask if order_side == "BUY" else book.quote.bid)
        return PricingSnapshot(
            quote=book.quote,
            fair_value=float(expected_price),
            limit_price=final_price,
            spread=book.spread,
            spread_pct=book.spread_pct,
            quote_age_ms=book.quote_age_ms,
            pricing_mode="forced_market",
            quote_source=book.quote_source,
            phase_name="FORCED_MARKET_EXIT",
        )

    def _quote_for_execution(
        self,
        contract: OptionContract,
        ts: datetime,
        *,
        max_age_ms: Optional[float] = None,
    ) -> Optional[OptionQuote]:
        del ts
        if max_age_ms is None or float(max_age_ms) <= 0.0:
            return angel_option_service.cached_quote(contract, max_age_ms=None)
        quote = angel_option_service.cached_quote(contract, max_age_ms=float(max_age_ms))
        if quote is not None:
            return quote
        return angel_option_service.cached_quote(contract, max_age_ms=None)

    @staticmethod
    def _microstructure_snapshot(quote: OptionQuote, contract: OptionContract) -> Dict[str, float]:
        tick = max(float(contract.tick_size or 0.05), 0.05)
        bid = float(quote.bid or max(float(quote.ltp) - tick, tick))
        ask = float(quote.ask or max(float(quote.ltp), bid + tick))
        ltp = float(quote.ltp or ((bid + ask) / 2.0))
        mid = ((bid + ask) / 2.0) if bid > 0.0 and ask > 0.0 else ltp
        microprice = float(quote.microprice() or mid or ltp)
        total_size = max(int(quote.bid_size or 0) + int(quote.ask_size or 0), 0)
        imbalance = (
            ((int(quote.bid_size or 0) - int(quote.ask_size or 0)) / float(total_size))
            if total_size > 0
            else 0.0
        )
        spread = max(ask - bid, tick)
        return {
            "tick": tick,
            "bid": bid,
            "ask": ask,
            "ltp": ltp,
            "mid": mid,
            "microprice": microprice,
            "imbalance": imbalance,
            "spread": spread,
            "spread_ticks": (spread / tick) if tick > 0.0 else 0.0,
            "bid_size": float(max(int(quote.bid_size or 0), 0)),
            "ask_size": float(max(int(quote.ask_size or 0), 0)),
            "lot_size": float(max(int(contract.lot_size or 1), 1)),
            "fair_price": microprice if microprice > 0.0 else mid,
        }

    def _build_execution_ladder(
        self,
        *,
        contract: OptionContract,
        quantity: int,
        params: ExecutionParams,
        order_side: str,
        metrics: Dict[str, float],
    ) -> list[ExecutionLevel]:
        phase_specs = self._phase_specs(
            params=params,
            order_side=order_side,
            metrics=metrics,
            target_qty=quantity,
        )
        tick = float(metrics["tick"])
        return [
            ExecutionLevel(
                phase_name=str(item["name"]),
                price=self._round_price(float(item["price"]), tick, order_side),
                wait_time_ms=int(item["wait_ms"]),
                reason=f"{params.mode.value} {order_side} {item['name']}",
            )
            for item in phase_specs
        ]

    def _phase_specs(
        self,
        *,
        params: ExecutionParams,
        order_side: str,
        metrics: Dict[str, float],
        target_qty: int,
    ) -> list[dict[str, float | str]]:
        tick = float(metrics["tick"])
        bid = float(metrics["bid"])
        ask = float(metrics["ask"])
        ltp = float(metrics["ltp"])
        microprice = float(metrics["microprice"])
        mid = float(metrics["mid"])
        imbalance = float(metrics["imbalance"])
        ask_thin = float(metrics["ask_size"]) <= float(metrics["lot_size"])
        bullish_pressure = microprice > mid or imbalance > 0.15
        bearish_pressure = microprice < mid or imbalance < -0.15

        if params.mode == ExecutionMode.TYPE_A:
            return self._phase_specs_type_a(
                order_side=order_side,
                bid=bid,
                ask=ask,
                tick=tick,
                mid=mid,
                microprice=microprice,
                spread=float(metrics["spread"]),
                bid_size=float(metrics["bid_size"]),
                target_qty=int(target_qty),
            )

        if order_side == "BUY":
            phase1 = bid if bearish_pressure else min(bid + tick, ask)
            if params.mode == ExecutionMode.TYPE_B:
                phase1 = min(max(microprice, bid + tick), ask)
            elif params.mode == ExecutionMode.TYPE_C and bullish_pressure:
                phase1 = min(max(microprice, bid + tick), ask)
            phase2 = min(ltp + tick, ask)
            if params.mode == ExecutionMode.TYPE_B or (params.adaptive and (bullish_pressure or ask_thin)):
                phase2 = ask
            phase3 = ask + tick
            phase4 = ask + (2.0 * tick if params.mode == ExecutionMode.TYPE_B else tick)
            return [
                {"name": "PASSIVE", "price": phase1, "wait_ms": params.passive_end_ms},
                {"name": "CONTROLLED", "price": phase2, "wait_ms": max(params.controlled_end_ms - params.passive_end_ms, 1)},
                {"name": "LADDER", "price": phase3, "wait_ms": max(params.ladder_end_ms - params.controlled_end_ms, 1)},
                {"name": "FORCED", "price": phase4, "wait_ms": max(params.force_end_ms - params.ladder_end_ms, 1)},
            ]

        phase1 = bid
        phase2 = max(bid - tick, tick)
        phase3 = max(bid - (2.0 * tick), tick)
        if params.mode == ExecutionMode.TYPE_B or (params.adaptive and bearish_pressure):
            phase3 = max(bid - (3.0 * tick), tick)
        phase4 = max(bid - (4.0 * tick), tick)
        return [
            {"name": "HIT_BID", "price": phase1, "wait_ms": 5},
            {"name": "CONTROLLED_EXIT", "price": phase2, "wait_ms": 10},
            {"name": "EXIT_LADDER", "price": phase3, "wait_ms": 15},
            {"name": "FORCED_EXIT", "price": phase4, "wait_ms": max(int(AB_TEST_EXIT_DEADLINE_MS) - 30, 1)},
        ]

    def _phase_specs_type_a(
        self,
        *,
        order_side: str,
        bid: float,
        ask: float,
        tick: float,
        mid: float,
        microprice: float,
        spread: float,
        bid_size: float,
        target_qty: int,
    ) -> list[dict[str, float | str]]:
        step = max(float(tick or 0.05), 0.05)
        live_spread = max(float(spread), step)
        book_micro = min(max(float(microprice or mid or bid), float(bid)), float(ask if ask > 0.0 else bid))
        book_mid = float(mid or ((bid + ask) / 2.0) or bid or ask or step)
        low_liquidity = float(bid_size or 0.0) < float(max(int(target_qty), 1))
        tight_spread = live_spread < (2.0 * step)
        fast_market = live_spread > (5.0 * step) or abs(book_micro - book_mid) >= (0.25 * live_spread)

        if order_side == "BUY":
            if low_liquidity:
                prices = [book_mid + (0.25 * live_spread), book_mid + (0.75 * live_spread), float(ask or (book_mid + live_spread))]
                names = ["MID_PLUS_25_ENTRY", "MID_PLUS_75_ENTRY", "ASK_ENTRY"]
            elif tight_spread:
                prices = [book_mid, book_mid + (0.25 * live_spread), book_mid + (0.75 * live_spread), float(ask or (book_mid + live_spread))]
                names = ["MID_ENTRY", "MID_PLUS_25_ENTRY", "MID_PLUS_75_ENTRY", "ASK_ENTRY"]
            else:
                prices = [book_micro, book_mid, book_mid + (0.25 * live_spread), book_mid + (0.75 * live_spread), float(ask or (book_mid + live_spread))]
                names = ["MICROPRICE_ENTRY", "MID_ENTRY", "MID_PLUS_25_ENTRY", "MID_PLUS_75_ENTRY", "ASK_ENTRY"]
            waits = [5] * len(prices) if fast_market else [8, 8, 8, 10, 10][: len(prices)]
            return [{"name": name, "price": price, "wait_ms": max(int(wait_ms), 1)} for name, price, wait_ms in zip(names, prices, waits)]

        deep_offset = max(3.0 * step, 0.002 * max(float(bid), step))
        deep_price = max(float(bid) - deep_offset, step)
        if low_liquidity:
            prices = [float(bid), max(float(bid) - step, step), deep_price]
            names = ["BID_EXIT_STAGE1", "BID_MINUS_1TICK_EXIT", "DEEP_EXIT"]
        else:
            prices = [book_micro, float(bid), float(bid), max(float(bid) - step, step), deep_price]
            names = ["MICROPRICE_EXIT", "BID_EXIT_STAGE1", "BID_EXIT_STAGE2", "BID_MINUS_1TICK_EXIT", "DEEP_EXIT"]
        waits = [5] * len(prices)
        return [{"name": name, "price": price, "wait_ms": max(int(wait_ms), 1)} for name, price, wait_ms in zip(names, prices, waits)]

    def _attempt_level(
        self,
        *,
        contract: OptionContract,
        order_side: str,
        level: ExecutionLevel,
        quantity: int,
        max_quote_age_ms: float,
        poll_ms: int,
        quote_guard: Optional[Any] = None,
    ) -> Dict[str, Any]:
        if not PAPER_MODE:
            gateway = self._live_gateway
            if level.phase_name in {"FORCED", "FORCED_EXIT"}:
                order = gateway.place_market(
                    contract=contract,
                    order_side=order_side,
                    quantity=quantity,
                    ts=datetime.now(),
                )
            else:
                order = gateway.place_limit_ioc(
                    contract=contract,
                    order_side=order_side,
                    quantity=quantity,
                    limit_price=level.price,
                    ts=datetime.now(),
                )
            fill = gateway.wait_for_fill(order, timeout_ms=int(level.wait_time_ms), poll_ms=max(int(poll_ms), 1))
            live_quote = angel_option_service.cached_quote(contract, max_age_ms=None)
            return {
                "fill_qty": int(quantity) if fill.filled else 0,
                "fill_price": float(fill.fill_price if fill.filled else 0.0),
                "elapsed_ms": max(float(level.wait_time_ms), 1.0),
                "status": fill.status or fill.reason or "NO_FILL",
                "quote": live_quote,
            }

        started = perf_counter()
        deadline = started + max(float(level.wait_time_ms), 1.0) / 1000.0
        last_quote: Optional[OptionQuote] = None
        tick = max(float(contract.tick_size or 0.05), 0.05)

        if level.phase_name in {"FORCED", "FORCED_EXIT"}:
            quote = self._quote_for_execution(contract, datetime.now(), max_age_ms=max_quote_age_ms)
            if quote is None:
                return {"fill_qty": 0, "fill_price": 0.0, "elapsed_ms": max(float(level.wait_time_ms), 1.0), "status": "NO_FILL", "quote": None}
            price = float(quote.ask if order_side == "BUY" else quote.bid)
            if price <= 0.0:
                price = float(quote.ltp or tick)
            return {
                "fill_qty": int(quantity),
                "fill_price": round(price, 2),
                "elapsed_ms": max((perf_counter() - started) * 1000.0, 1.0),
                "status": "FORCED_MARKET_FILL",
                "quote": quote,
            }

        while perf_counter() < deadline:
            quote = self._quote_for_execution(contract, datetime.now(), max_age_ms=max_quote_age_ms)
            if quote is None:
                sleep(max(int(poll_ms), 1) / 1000.0)
                continue
            last_quote = quote
            if quote_guard is not None and not bool(quote_guard(quote)):
                return {
                    "fill_qty": 0,
                    "fill_price": 0.0,
                    "elapsed_ms": max((perf_counter() - started) * 1000.0, 1.0),
                    "status": "GUARD_CANCELLED",
                    "quote": quote,
                }
            bid = float(quote.bid or 0.0)
            ask = float(quote.ask or 0.0)
            if order_side == "BUY" and ask > 0.0 and float(level.price) >= ask:
                visible = int(quote.ask_size or quantity)
                if self._book_fill_qty(int(quantity), visible, int(contract.lot_size)) >= int(quantity):
                    return {
                        "fill_qty": int(quantity),
                        "fill_price": round(ask, 2),
                        "elapsed_ms": max((perf_counter() - started) * 1000.0, 1.0),
                        "status": "FULL_CROSS_FILL",
                        "quote": quote,
                    }
            elif order_side == "SELL" and bid > 0.0 and float(level.price) <= bid:
                visible = int(quote.bid_size or quantity)
                if self._book_fill_qty(int(quantity), visible, int(contract.lot_size)) >= int(quantity):
                    return {
                        "fill_qty": int(quantity),
                        "fill_price": round(bid, 2),
                        "elapsed_ms": max((perf_counter() - started) * 1000.0, 1.0),
                        "status": "FULL_CROSS_FILL",
                        "quote": quote,
                    }
            sleep(max(int(poll_ms), 1) / 1000.0)

        return {
            "fill_qty": 0,
            "fill_price": 0.0,
            "elapsed_ms": max((perf_counter() - started) * 1000.0, 1.0),
            "status": "NO_FILL" if last_quote is not None else "QUOTE_TOO_STALE",
            "quote": last_quote,
        }

    @staticmethod
    def _book_fill_qty(quantity: int, displayed_size: int, lot_size: int) -> int:
        lot = max(int(lot_size or 1), 1)
        visible = max(int(displayed_size or 0), 0)
        if visible <= 0:
            return 0
        visible_lots = max(visible // lot, 0)
        if visible_lots <= 0:
            return 0
        return min(int(quantity), visible_lots * lot)

    def _book_has_depth(self, book: PricingSnapshot, order_side: str) -> bool:
        if order_side == "BUY":
            return int(book.quote.ask_size or 0) > 0
        return int(book.quote.bid_size or 0) > 0

    def _slippage_exceeded(self, order_side: str, candidate_price: float, expected_price: float) -> bool:
        max_slippage = float(OPTION_BOOK_MAX_SLIPPAGE_RS)
        if max_slippage <= 0.0:
            return False
        if order_side == "BUY":
            return (float(candidate_price) - float(expected_price)) > max_slippage
        return (float(expected_price) - float(candidate_price)) > max_slippage

    def _step_timeout_ms(self, deadline: float, step_wait_ms: int) -> int:
        remaining_ms = max((deadline - perf_counter()) * 1000.0, 0.0)
        if remaining_ms <= 0.0:
            return max(int(step_wait_ms), 1)
        return max(min(int(step_wait_ms), int(math.ceil(remaining_ms))), 1)

    def _entry_price_levels(self, book: PricingSnapshot, tick_size: float) -> list[float]:
        bid = float(book.quote.bid)
        ask = float(book.quote.ask)
        mid = float(book.fair_value)
        step = float(OPTION_BOOK_PRICE_STEP_RS)
        levels = [
            min(max(bid + step, mid - step), ask),
            min(max(mid, bid), ask),
            min(max(ask - step, bid), ask),
            ask,
        ]
        return self._normalize_levels(levels, tick_size=tick_size, order_side="BUY")

    def _exit_price_levels(self, book: PricingSnapshot, tick_size: float) -> list[float]:
        bid = float(book.quote.bid)
        mid = float(book.fair_value)
        step = float(OPTION_BOOK_PRICE_STEP_RS)
        levels = [
            max(mid - step, bid),
            bid,
            max(bid - step, tick_size),
        ]
        return self._normalize_levels(levels, tick_size=tick_size, order_side="SELL")

    def _normalize_levels(self, levels: list[float], *, tick_size: float, order_side: str) -> list[float]:
        normalized: list[float] = []
        for price in levels:
            rounded = self._round_price(float(price), tick_size, order_side)
            if normalized and math.isclose(rounded, normalized[-1], rel_tol=0.0, abs_tol=1e-9):
                continue
            normalized.append(rounded)
        return normalized

    def _round_price(self, price: float, tick_size: float, order_side: str) -> float:
        tick = max(float(tick_size), 0.01)
        value = max(float(price), tick)
        steps = value / tick
        if order_side == "BUY":
            rounded = math.ceil(steps - 1e-9) * tick
        else:
            rounded = math.floor(steps + 1e-9) * tick
        return round(max(rounded, tick), 2)


option_execution_engine = OptionExecutionEngine()
