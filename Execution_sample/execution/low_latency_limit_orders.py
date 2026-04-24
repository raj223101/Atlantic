"""
Minimal L1 limit-price decisions for fast option entry and exit.
"""

from __future__ import annotations

from dataclasses import dataclass
import math


@dataclass(frozen=True)
class LimitOrderPlan:
    action: str
    first_price: float
    fallback_target: str
    fallback_price_hint: float
    wait_ms: int
    poll_ms: int
    spread: float
    quote_age_ms: float
    fair_value: float
    pricing_mode: str
    state: str = ""
    skip_reason: str = ""


def build_entry_limit_plan(
    *,
    bid: float,
    ask: float,
    ltp: float,
    tick: float,
    quote_age_ms: float,
    max_spread: float = 1.0,
    max_quote_age_ms: float = 100.0,
    wait_ms: int = 40,
    poll_ms: int = 10,
) -> LimitOrderPlan:
    spread = _spread(bid, ask)
    skip_reason = _common_skip_reason(
        bid=bid,
        ask=ask,
        ltp=ltp,
        spread=spread,
        quote_age_ms=quote_age_ms,
        max_spread=max_spread,
        max_quote_age_ms=max_quote_age_ms,
    )
    if skip_reason:
        return LimitOrderPlan(
            action="ENTRY",
            first_price=0.0,
            fallback_target="ask",
            fallback_price_hint=0.0,
            wait_ms=int(wait_ms),
            poll_ms=int(poll_ms),
            spread=spread,
            quote_age_ms=float(quote_age_ms),
            fair_value=float(ltp or 0.0),
            pricing_mode="entry_l1_cap",
            skip_reason=skip_reason,
        )

    first_raw = min(float(ltp) + float(tick), _fallback_price("ask", bid=bid, ask=ask, ltp=ltp, tick=tick))
    first_price = _round_price(first_raw, tick, "BUY")
    fallback_price = _fallback_price("ask", bid=bid, ask=ask, ltp=ltp, tick=tick)
    return LimitOrderPlan(
        action="ENTRY",
        first_price=first_price,
        fallback_target="ask",
        fallback_price_hint=fallback_price,
        wait_ms=int(wait_ms),
        poll_ms=int(poll_ms),
        spread=spread,
        quote_age_ms=float(quote_age_ms),
        fair_value=float(ltp or fallback_price),
        pricing_mode="entry_l1_cap",
        state="controlled_aggression",
    )


def build_exit_limit_plan(
    *,
    entry_price: float,
    bid: float,
    ask: float,
    ltp: float,
    tick: float,
    quote_age_ms: float,
    max_spread: float = 1.0,
    max_quote_age_ms: float = 100.0,
    wait_ms: int = 40,
    poll_ms: int = 10,
) -> LimitOrderPlan:
    spread = _spread(bid, ask)
    skip_reason = _common_skip_reason(
        bid=bid,
        ask=ask,
        ltp=ltp,
        spread=spread,
        quote_age_ms=quote_age_ms,
        max_spread=max_spread,
        max_quote_age_ms=max_quote_age_ms,
    )
    if skip_reason:
        return LimitOrderPlan(
            action="EXIT",
            first_price=0.0,
            fallback_target="bid",
            fallback_price_hint=0.0,
            wait_ms=int(wait_ms),
            poll_ms=int(poll_ms),
            spread=spread,
            quote_age_ms=float(quote_age_ms),
            fair_value=float(ltp or 0.0),
            pricing_mode="exit_l1_profit_protect",
            skip_reason=skip_reason,
        )

    live_bid = _fallback_price("bid", bid=bid, ask=ask, ltp=ltp, tick=tick)
    profitable = float(entry_price or 0.0) > 0.0 and _exit_mark(bid=bid, ltp=ltp) >= float(entry_price)
    if profitable:
        first_price = live_bid
        state = "in_profit"
    else:
        first_price = _round_price(max(live_bid - float(tick), float(tick)), tick, "SELL")
        state = "neutral_or_loss"

    return LimitOrderPlan(
        action="EXIT",
        first_price=first_price,
        fallback_target="bid",
        fallback_price_hint=live_bid,
        wait_ms=int(wait_ms),
        poll_ms=int(poll_ms),
        spread=spread,
        quote_age_ms=float(quote_age_ms),
        fair_value=float(ltp or live_bid),
        pricing_mode="exit_l1_profit_protect",
        state=state,
    )


def fallback_price_from_quote(
    *,
    target: str,
    bid: float,
    ask: float,
    ltp: float,
    tick: float,
) -> float:
    return _fallback_price(target, bid=bid, ask=ask, ltp=ltp, tick=tick)


def _common_skip_reason(
    *,
    bid: float,
    ask: float,
    ltp: float,
    spread: float,
    quote_age_ms: float,
    max_spread: float,
    max_quote_age_ms: float,
) -> str:
    if max(float(ask), float(bid), float(ltp)) <= 0.0:
        return "INVALID_QUOTE"
    if float(ask) > 0.0 and float(bid) > 0.0 and float(ask) < float(bid):
        return "INVERTED_BOOK"
    if float(max_quote_age_ms) > 0.0 and float(quote_age_ms) > float(max_quote_age_ms):
        return "QUOTE_TOO_STALE"
    if float(spread) > float(max_spread):
        return "SPREAD_TOO_WIDE"
    return ""


def _spread(bid: float, ask: float) -> float:
    if float(ask) > 0.0 and float(bid) > 0.0:
        return max(float(ask) - float(bid), 0.0)
    return 0.0


def _exit_mark(*, bid: float, ltp: float) -> float:
    if float(bid) > 0.0:
        return float(bid)
    return float(ltp or 0.0)


def _fallback_price(target: str, *, bid: float, ask: float, ltp: float, tick: float) -> float:
    step = max(float(tick or 0.05), 0.01)
    if str(target).lower() == "ask":
        if float(ask) > 0.0:
            raw = float(ask)
        elif float(ltp) > 0.0:
            raw = float(ltp) + step
        elif float(bid) > 0.0:
            raw = float(bid) + step
        else:
            raw = step
        return _round_price(raw, step, "BUY")

    if float(bid) > 0.0:
        raw = float(bid)
    elif float(ltp) > 0.0:
        raw = max(float(ltp) - step, step)
    elif float(ask) > 0.0:
        raw = max(float(ask) - step, step)
    else:
        raw = step
    return _round_price(raw, step, "SELL")


def _round_price(price: float, tick: float, order_side: str) -> float:
    step = max(float(tick or 0.05), 0.01)
    value = max(float(price), step)
    steps = value / step
    if str(order_side).upper() == "BUY":
        rounded = math.ceil(steps - 1e-9) * step
    else:
        rounded = math.floor(steps + 1e-9) * step
    return round(max(rounded, step), 2)
