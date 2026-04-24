"""
Angel option contract resolution and live L1 quote cache.
"""

from __future__ import annotations

from collections import defaultdict
import json
import math
import os
import threading
from dataclasses import dataclass
from datetime import date, datetime
from time import perf_counter, sleep
from typing import Any, Dict, Iterable, List, Optional
from urllib.request import urlopen

from config import (
    ANGEL_MARKETDATA_MODE,
    ANGEL_SCRIP_MASTER_CACHE,
    ANGEL_SCRIP_MASTER_URL,
    OPTION_LOG_BUCKETS,
    OPTION_LOTS_PER_TRADE,
    OPTION_LADDER_STRIKES_EACH_SIDE,
    OPTION_LADDER_RETRY_COOLDOWN_S,
    OPTION_FEED_HEALTH_CHECK_S,
    OPTION_FEED_HEALTH_STALE_MS,
    OPTION_ORDER_PRODUCT_TYPE,
    OPTION_QUOTE_CACHE_MS,
    OPTION_QUOTE_STALENESS_LIMIT_MS,
)
from core.api_context import get_trading_api
from core.instrument_registry import get_tradeable_instrument, iter_tradeable_instruments
from core.logger import log
from monitoring.performance_monitor import performance_monitor
from storage.option_quote_saver import option_quote_saver


@dataclass(frozen=True)
class OptionContract:
    underlying_symbol: str
    symbol: str
    token: str
    exchange: str
    exchange_type: int
    option_type: str
    strike: float
    expiry: str
    expiry_date: date
    lot_size: int
    tick_size: float


@dataclass(frozen=True)
class OptionQuote:
    ltp: float
    ts: datetime
    raw: Dict[str, Any]
    bid: float = 0.0
    ask: float = 0.0
    bid_size: int = 0
    ask_size: int = 0
    source: str = "cache"

    @property
    def spread(self) -> float:
        if self.bid > 0.0 and self.ask > 0.0:
            return max(self.ask - self.bid, 0.0)
        return 0.0

    def microprice(self) -> float:
        if self.bid > 0.0 and self.ask > 0.0:
            total_qty = self.bid_size + self.ask_size
            if total_qty > 0:
                return ((self.ask * self.bid_size) + (self.bid * self.ask_size)) / float(total_qty)
            return (self.bid + self.ask) / 2.0
        if self.ask > 0.0:
            return self.ask
        if self.bid > 0.0:
            return self.bid
        return self.ltp

INITIAL_QUOTE_FETCH_WAIT_S = 0.35


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return default
    if math.isnan(numeric) or math.isinf(numeric):
        return default
    return numeric


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _parse_expiry(raw: Any) -> Optional[date]:
    if raw is None:
        return None
    text = str(raw).strip().upper()
    if not text:
        return None
    for fmt in ("%d%b%Y", "%d%b%y", "%Y-%m-%d", "%d-%b-%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


class AngelOptionService:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._master: Optional[List[Dict[str, Any]]] = None
        self._master_loaded_at = 0.0
        self._contracts_by_bucket: Dict[tuple[str, date, str], Dict[float, OptionContract]] = {}
        self._contracts_by_token: Dict[str, OptionContract] = {}
        self._expiries_by_underlying: Dict[str, List[date]] = {}
        self._nearest_expiry_cache: Dict[tuple[str, date], Optional[date]] = {}
        self._quote_cache: Dict[tuple[str, str], OptionQuote] = {}
        self._quote_fetch_events: Dict[tuple[str, str], threading.Event] = {}
        self._underlying_quotes: Dict[str, Dict[str, Any]] = {}
        self._pending_ladder_depth: Dict[str, int] = {}
        self._ladder_retry_after: Dict[str, float] = {}
        self._ladder_seeded: set[str] = set()
        self._watched_option_contracts: Dict[tuple[str, str, str], OptionContract] = {}
        self._pinned_contract_counts: Dict[tuple[str, str], int] = {}
        self._feed = None
        self._feed_health_thread: Optional[threading.Thread] = None
        self._feed_health_started = False
        self._feed_health_warned = False
        root_pairs = [
            ((spec.derivative_root or spec.name).upper(), spec.name)
            for spec in iter_tradeable_instruments()
            if spec.supports_options
        ]
        self._root_to_symbol = dict(root_pairs)
        self._root_matches = sorted(
            root_pairs,
            key=lambda item: len(item[0]),
            reverse=True,
        )

    def bind_feed(self, feed: Any) -> None:
        pending: List[tuple[str, float, int]] = []
        with self._lock:
            self._feed = feed
            for symbol, depth in self._pending_ladder_depth.items():
                snapshot = self._underlying_quotes.get(symbol, {})
                spot = float(snapshot.get("price", 0.0) or 0.0)
                if spot > 0.0 and symbol not in self._ladder_seeded:
                    pending.append((symbol, spot, int(depth)))
        self._start_feed_health_monitor()
        for symbol, spot, depth in pending:
            self.pre_subscribe_ladder(symbol, spot, num_strikes=depth)

    def option_lots_per_trade(self) -> int:
        return int(OPTION_LOTS_PER_TRADE)

    def order_product_type(self) -> str:
        return str(OPTION_ORDER_PRODUCT_TYPE)

    def prepare_contract_master(self) -> None:
        self._load_master()

    def request_ladder_subscription(
        self,
        underlying_symbol: str,
        num_strikes: int = OPTION_LADDER_STRIKES_EACH_SIDE,
    ) -> None:
        depth = max(int(num_strikes), 0)
        if depth <= 0:
            return
        with self._lock:
            self._pending_ladder_depth[underlying_symbol] = depth
            self._ladder_seeded.discard(underlying_symbol)
            self._ladder_retry_after.pop(underlying_symbol, None)

    def update_underlying_price(self, symbol: str, price: float, ts: datetime) -> None:
        subscribe_depth = 0
        should_attempt = False
        now_monotonic = perf_counter()
        with self._lock:
            self._underlying_quotes[symbol] = {
                "price": float(price),
                "ts": ts,
            }
            if symbol not in self._ladder_seeded:
                subscribe_depth = int(self._pending_ladder_depth.get(symbol, 0) or 0)
                retry_after = float(self._ladder_retry_after.get(symbol, 0.0) or 0.0)
                should_attempt = subscribe_depth > 0 and now_monotonic >= retry_after

        if float(price) > 0.0:
            self._sync_option_watch(symbol, float(price), ts)
        if should_attempt and float(price) > 0.0:
            self.pre_subscribe_ladder(symbol, float(price), num_strikes=subscribe_depth)

    def latest_underlying_price(self, symbol: str, fallback: float = 0.0) -> float:
        current = self._current_underlying_price(symbol)
        if current > 0.0:
            return current
        return float(fallback)

    def latest_underlying_snapshot(self, symbol: str) -> Dict[str, Any]:
        with self._lock:
            return dict(self._underlying_quotes.get(symbol, {}))

    def _sync_option_watch(self, underlying_symbol: str, spot_price: float, ts: datetime) -> None:
        if float(spot_price) <= 0.0:
            return
        expiry = self._nearest_expiry(underlying_symbol, ts.date())
        if expiry is None:
            return

        base = get_tradeable_instrument(underlying_symbol)
        step = float(base.strike_step or 50.0)
        desired: Dict[tuple[str, str, str], OptionContract] = {}

        for option_type in ("CE", "PE"):
            bucket_key = (underlying_symbol, expiry, option_type)
            strikes_map = self._contracts_by_bucket.get(bucket_key, {})
            if not strikes_map:
                continue
            for watch_bucket in OPTION_LOG_BUCKETS:
                target_strike = self._target_strike_for_bucket(
                    float(spot_price),
                    option_type,
                    step,
                    str(watch_bucket),
                )
                contract = self._contract_for_watch_bucket(
                    strikes_map,
                    float(spot_price),
                    float(target_strike),
                    option_type,
                    str(watch_bucket),
                )
                if contract is not None:
                    desired[(underlying_symbol, option_type, str(watch_bucket))] = contract

        subscribe: Dict[tuple[str, str], OptionContract] = {}
        unsubscribe: Dict[tuple[str, str], OptionContract] = {}
        with self._lock:
            existing_keys = [
                key
                for key in self._watched_option_contracts
                if key[0] == underlying_symbol
            ]
            old_contracts = {
                (contract.exchange, contract.token): contract
                for key, contract in self._watched_option_contracts.items()
                if key in existing_keys
            }
            for key in existing_keys:
                self._watched_option_contracts.pop(key, None)
            self._watched_option_contracts.update(desired)
            new_contracts = {
                (contract.exchange, contract.token): contract
                for key, contract in self._watched_option_contracts.items()
                if key[0] == underlying_symbol
            }
            for cache_key, contract in new_contracts.items():
                if cache_key not in old_contracts:
                    subscribe[cache_key] = contract
            for cache_key, contract in old_contracts.items():
                if cache_key in new_contracts:
                    continue
                if not self._is_pinned_locked(contract) and not self._is_watched_locked(contract):
                    unsubscribe[cache_key] = contract

        for contract in subscribe.values():
            self.ensure_live_subscription(contract)
        for cache_key, contract in unsubscribe.items():
            if cache_key not in subscribe:
                self.ensure_live_unsubscription(contract)

    def _is_watched_locked(self, contract: OptionContract) -> bool:
        for watched in self._watched_option_contracts.values():
            if watched.exchange == contract.exchange and watched.token == contract.token:
                return True
        return False

    def _is_pinned_locked(self, contract: OptionContract) -> bool:
        cache_key = (contract.exchange, contract.token)
        return int(self._pinned_contract_counts.get(cache_key, 0) or 0) > 0

    def pre_subscribe_ladder(
        self,
        underlying_symbol: str,
        spot_price: float,
        num_strikes: int = OPTION_LADDER_STRIKES_EACH_SIDE,
    ) -> int:
        attempt_started = perf_counter()
        self._load_master()
        today = datetime.now().date()
        expiry = self._nearest_expiry(underlying_symbol, today)
        if expiry is None:
            retry_after = attempt_started + float(OPTION_LADDER_RETRY_COOLDOWN_S)
            with self._lock:
                previous_retry_after = float(self._ladder_retry_after.get(underlying_symbol, 0.0) or 0.0)
                self._ladder_retry_after[underlying_symbol] = retry_after
            if attempt_started >= previous_retry_after:
                log.warning(
                    "[AngelOptionService] no expiry found | symbol=%s retry_in_s=%.1f",
                    underlying_symbol,
                    float(OPTION_LADDER_RETRY_COOLDOWN_S),
                )
            return 0

        base = get_tradeable_instrument(underlying_symbol)
        step = float(base.strike_step or 50.0)
        width = max(int(num_strikes), 0)
        subscribed = 0

        for option_type in ("CE", "PE"):
            bucket_key = (underlying_symbol, expiry, option_type)
            strikes_map = self._contracts_by_bucket.get(bucket_key, {})
            if not strikes_map:
                continue

            itm_strike = self._direct_itm_strike(float(spot_price), option_type, step)
            all_strikes = sorted(strikes_map.keys())
            if not all_strikes:
                continue

            anchor_idx = min(
                range(len(all_strikes)),
                key=lambda index: abs(float(all_strikes[index]) - float(itm_strike)),
            )
            lo = max(0, anchor_idx - width)
            hi = min(len(all_strikes), anchor_idx + width + 1)

            for strike in all_strikes[lo:hi]:
                contract = strikes_map.get(float(strike))
                if contract is not None and self.ensure_live_subscription(contract):
                    subscribed += 1

        if subscribed > 0:
            with self._lock:
                self._pending_ladder_depth.pop(underlying_symbol, None)
                self._ladder_seeded.add(underlying_symbol)
                self._ladder_retry_after.pop(underlying_symbol, None)
        else:
            with self._lock:
                self._ladder_retry_after[underlying_symbol] = (
                    perf_counter() + float(OPTION_LADDER_RETRY_COOLDOWN_S)
                )

        log.info(
            "[AngelOptionService] ladder pre-subscribe | symbol=%s spot=%.2f expiry=%s strikes_each_side=%d subscribed=%d",
            underlying_symbol,
            float(spot_price),
            expiry,
            width,
            subscribed,
        )
        return subscribed

    def resolve_option_contract(
        self,
        underlying_symbol: str,
        signal_side: str,
        underlying_price: float,
        ts: datetime,
        option_bucket: str = "ITM1",
    ) -> Optional[OptionContract]:
        option_type = "CE" if signal_side == "LONG" else "PE"
        self._sync_option_watch(underlying_symbol, float(underlying_price), ts)
        normalized_bucket = str(option_bucket or "ITM1").upper()
        with self._lock:
            watched = self._watched_option_contracts.get((underlying_symbol, option_type, normalized_bucket))
        if watched is not None:
            self.ensure_live_subscription(watched)
            return watched

        expiry = self._nearest_expiry(underlying_symbol, ts.date())
        if expiry is None:
            return None
        bucket_key = (underlying_symbol, expiry, option_type)
        strikes_map = self._contracts_by_bucket.get(bucket_key, {})
        if not strikes_map:
            return None

        base = get_tradeable_instrument(underlying_symbol)
        step = float(base.strike_step or 0.0)
        target_strike = self._target_strike_for_bucket(
            float(underlying_price),
            option_type,
            step,
            normalized_bucket,
        )
        selected = self._contract_for_watch_bucket(
            strikes_map,
            float(underlying_price),
            float(target_strike),
            option_type,
            normalized_bucket,
        )
        if selected is not None:
            self.ensure_live_subscription(selected)
            return selected

        return selected

    def resolve_itm_contract(
        self,
        underlying_symbol: str,
        signal_side: str,
        underlying_price: float,
        ts: datetime,
    ) -> Optional[OptionContract]:
        return self.resolve_option_contract(
            underlying_symbol=underlying_symbol,
            signal_side=signal_side,
            underlying_price=underlying_price,
            ts=ts,
            option_bucket="ITM1",
        )

    def ensure_live_subscription(self, contract: OptionContract) -> bool:
        with self._lock:
            feed = self._feed
        if feed is None:
            return False
        try:
            feed.subscribe_option_contract(contract)
            return True
        except Exception as exc:
            log.warning(
                "[AngelOptionService] option subscription failed | symbol=%s token=%s error=%s",
                contract.symbol,
                contract.token,
                exc,
            )
            return False

    def ensure_live_unsubscription(self, contract: OptionContract) -> bool:
        with self._lock:
            feed = self._feed
        if feed is None:
            return False
        try:
            feed.unsubscribe_option_contract(contract)
            return True
        except Exception as exc:
            log.warning(
                "[AngelOptionService] option unsubscribe failed | symbol=%s token=%s error=%s",
                contract.symbol,
                contract.token,
                exc,
            )
            return False

    def pin_contract(self, contract: OptionContract) -> None:
        cache_key = (contract.exchange, contract.token)
        with self._lock:
            self._pinned_contract_counts[cache_key] = self._pinned_contract_counts.get(cache_key, 0) + 1
        self.ensure_live_subscription(contract)

    def unpin_contract(self, contract: OptionContract) -> None:
        should_unsubscribe = False
        cache_key = (contract.exchange, contract.token)
        with self._lock:
            count = int(self._pinned_contract_counts.get(cache_key, 0))
            if count <= 1:
                self._pinned_contract_counts.pop(cache_key, None)
                should_unsubscribe = not self._is_watched_locked(contract)
            else:
                self._pinned_contract_counts[cache_key] = count - 1
        if should_unsubscribe:
            self.ensure_live_unsubscription(contract)

    def handles_token(self, token: str) -> bool:
        with self._lock:
            return str(token) in self._contracts_by_token

    def ingest_ws_quote(self, message: Dict[str, Any], ts: Optional[datetime] = None) -> bool:
        token = str(message.get("token", ""))
        if not token:
            return False

        with self._lock:
            contract = self._contracts_by_token.get(token)
        if contract is None:
            return False

        quote_ts = ts or self._parse_quote_timestamp(message)
        quote = self._build_quote(contract, message, quote_ts, source="ws")
        self._store_quote(contract, quote)
        return True

    def quote_contract(
        self,
        contract: OptionContract,
        ts: Optional[datetime] = None,
        *,
        force_refresh: bool = False,
    ) -> Optional[OptionQuote]:
        del ts, force_refresh
        self.ensure_live_subscription(contract)
        return self.cached_quote(contract, max_age_ms=None)

    def cached_quote(
        self,
        contract: OptionContract,
        max_age_ms: Optional[float] = OPTION_QUOTE_CACHE_MS,
    ) -> Optional[OptionQuote]:
        cache_key = (contract.exchange, contract.token)
        with self._lock:
            quote = self._quote_cache.get(cache_key)
        if quote is None:
            return None

        if max_age_ms is None:
            return quote

        age_ms = max((datetime.now() - quote.ts).total_seconds() * 1000.0, 0.0)
        if age_ms > float(max_age_ms):
            return None
        return quote

    def quote_age_ms(self, quote: OptionQuote, now: datetime) -> float:
        return max((now - quote.ts).total_seconds() * 1000.0, 0.0)

    def quote_stale_for_execution(self, quote: OptionQuote, now: datetime) -> bool:
        return self.quote_age_ms(quote, now) > float(OPTION_QUOTE_STALENESS_LIMIT_MS)

    def _load_master(self) -> List[Dict[str, Any]]:
        with self._lock:
            if self._master is not None:
                return self._master

        rows = self._load_master_from_cache()
        if not rows:
            rows = self._fetch_master_remote()
        with self._lock:
            self._master = rows or []
            self._master_loaded_at = perf_counter()
            self._rebuild_contract_index(self._master)
            return self._master

    def _load_master_from_cache(self) -> List[Dict[str, Any]]:
        if not os.path.isfile(ANGEL_SCRIP_MASTER_CACHE):
            return []
        try:
            with open(ANGEL_SCRIP_MASTER_CACHE, "r", encoding="utf-8") as handle:
                return json.load(handle)
        except Exception:
            return []

    def _fetch_master_remote(self) -> List[Dict[str, Any]]:
        started = perf_counter()
        try:
            with urlopen(ANGEL_SCRIP_MASTER_URL, timeout=20) as response:
                rows = json.loads(response.read().decode("utf-8"))
            os.makedirs(os.path.dirname(ANGEL_SCRIP_MASTER_CACHE) or ".", exist_ok=True)
            with open(ANGEL_SCRIP_MASTER_CACHE, "w", encoding="utf-8") as handle:
                json.dump(rows, handle)
            performance_monitor.on_api_call(
                service="angel",
                operation="scrip_master_fetch",
                success=True,
                elapsed_ms=(perf_counter() - started) * 1000.0,
            )
            return rows
        except Exception as exc:
            performance_monitor.on_api_call(
                service="angel",
                operation="scrip_master_fetch",
                success=False,
                elapsed_ms=(perf_counter() - started) * 1000.0,
                timeout="timeout" in str(exc).lower(),
                error=str(exc),
            )
            log.warning("[AngelOptionService] scrip master fetch failed | error=%s", exc)
            return []

    def _rebuild_contract_index(self, rows: List[Dict[str, Any]]) -> None:
        contracts_by_bucket: Dict[tuple[str, date, str], Dict[float, OptionContract]] = defaultdict(dict)
        contracts_by_token: Dict[str, OptionContract] = {}
        expiries_by_underlying: Dict[str, set[date]] = defaultdict(set)
        for record in rows:
            contract = self._contract_from_record(record)
            if contract is None:
                continue
            bucket_key = (contract.underlying_symbol, contract.expiry_date, contract.option_type)
            contracts_by_bucket[bucket_key][float(contract.strike)] = contract
            contracts_by_token[str(contract.token)] = contract
            expiries_by_underlying[contract.underlying_symbol].add(contract.expiry_date)
        self._contracts_by_bucket = dict(contracts_by_bucket)
        self._contracts_by_token = contracts_by_token
        self._expiries_by_underlying = {
            symbol: sorted(expiries)
            for symbol, expiries in expiries_by_underlying.items()
        }
        self._nearest_expiry_cache.clear()

    def _contract_from_record(self, record: Dict[str, Any]) -> Optional[OptionContract]:
        exch = str(record.get("exch_seg") or record.get("exchange") or "").upper()
        instrument_type = str(record.get("instrumenttype") or record.get("instrument_type") or "").upper()
        if "OPT" not in instrument_type:
            return None

        symbol_text = str(record.get("symbol") or record.get("tradingsymbol") or "")
        symbol_upper = symbol_text.upper()
        name = str(record.get("name") or "").upper()
        underlying_symbol = self._match_underlying_symbol(symbol_upper, name)
        if underlying_symbol is None:
            return None

        base = get_tradeable_instrument(underlying_symbol)
        exchange = "BFO" if base.exchange.lower().startswith("bse") else "NFO"
        if exch != exchange:
            return None

        expiry_date = _parse_expiry(record.get("expiry"))
        if expiry_date is None:
            return None

        option_type = symbol_upper[-2:]
        if option_type not in {"CE", "PE"}:
            option_type = str(record.get("optiontype") or record.get("option_type") or "").upper()
        if option_type not in {"CE", "PE"}:
            return None

        strike = self._normalize_strike(record.get("strike"))
        return OptionContract(
            underlying_symbol=underlying_symbol,
            symbol=symbol_text,
            token=str(record.get("token") or record.get("symboltoken") or ""),
            exchange=exchange,
            exchange_type=4 if exchange == "BFO" else 2,
            option_type=option_type,
            strike=float(strike),
            expiry=str(record.get("expiry") or ""),
            expiry_date=expiry_date,
            lot_size=_to_int(record.get("lotsize") or base.lot_size, base.lot_size),
            tick_size=_to_float(record.get("tick_size") or record.get("ticksize") or base.tick_size, base.tick_size),
        )

    def _match_underlying_symbol(self, symbol_upper: str, name: str) -> Optional[str]:
        normalized_name = str(name or "").strip().upper()
        for root, symbol in self._root_matches:
            if normalized_name == root:
                return symbol
        for root, symbol in self._root_matches:
            if symbol_upper.startswith(root) or root in symbol_upper:
                return symbol
        return None

    def _nearest_expiry(self, underlying_symbol: str, today: date) -> Optional[date]:
        cache_key = (underlying_symbol, today)
        with self._lock:
            if cache_key in self._nearest_expiry_cache:
                return self._nearest_expiry_cache[cache_key]
            master_loaded = self._master is not None
        if not master_loaded:
            self._load_master()
        with self._lock:
            expiries = list(self._expiries_by_underlying.get(underlying_symbol, []))
        if not expiries:
            resolved = None
        else:
            valid = [expiry for expiry in expiries if expiry >= today]
            resolved = valid[0] if valid else expiries[0]
        with self._lock:
            self._nearest_expiry_cache[cache_key] = resolved
        return resolved

    def _fetch_rest_quote_coalesced(
        self,
        contract: OptionContract,
        ts: datetime,
    ) -> Optional[OptionQuote]:
        cache_key = (contract.exchange, contract.token)
        with self._lock:
            cached = self._quote_cache.get(cache_key)
            if cached is not None:
                return cached
            wait_event = self._quote_fetch_events.get(cache_key)
            if wait_event is None:
                wait_event = threading.Event()
                self._quote_fetch_events[cache_key] = wait_event
                owner = True
            else:
                owner = False

        if not owner:
            wait_event.wait(timeout=INITIAL_QUOTE_FETCH_WAIT_S)
            return self.cached_quote(contract, max_age_ms=None)

        try:
            return self._fetch_rest_quote(contract, ts)
        finally:
            with self._lock:
                event = self._quote_fetch_events.pop(cache_key, None)
            if event is not None:
                event.set()

    def _fetch_rest_quote(self, contract: OptionContract, ts: datetime) -> Optional[OptionQuote]:
        api = get_trading_api()
        if api is None:
            return None

        payload = None
        started = perf_counter()
        try:
            response = api.getMarketData(ANGEL_MARKETDATA_MODE, {contract.exchange: [contract.token]})
            payload = self._extract_market_payload(response, contract.token)
        except Exception as exc:
            performance_monitor.on_api_call(
                service="angel",
                operation="get_market_data",
                success=False,
                elapsed_ms=(perf_counter() - started) * 1000.0,
                timeout="timeout" in str(exc).lower(),
                error=str(exc),
            )
            log.warning("[AngelOptionService] quote fetch failed | symbol=%s error=%s", contract.symbol, exc)
            return None

        performance_monitor.on_api_call(
            service="angel",
            operation="get_market_data",
            success=bool(payload),
            elapsed_ms=(perf_counter() - started) * 1000.0,
            error="" if payload else "empty_payload",
        )
        if not payload:
            return None

        quote = self._build_quote(contract, payload, ts, source="rest")
        self._store_quote(contract, quote)
        return quote

    def _start_feed_health_monitor(self) -> None:
        with self._lock:
            if self._feed_health_started:
                return
            self._feed_health_started = True
            thread = threading.Thread(
                target=self._feed_health_loop,
                name="OptionFeedHealth",
                daemon=True,
            )
            self._feed_health_thread = thread
        thread.start()

    def _feed_health_loop(self) -> None:
        check_interval_s = max(float(OPTION_FEED_HEALTH_CHECK_S), 0.5)
        stale_threshold_ms = max(float(OPTION_FEED_HEALTH_STALE_MS), 0.0)

        while True:
            now = datetime.now()
            with self._lock:
                quotes = list(self._quote_cache.values())
                warned = self._feed_health_warned

            if quotes:
                max_age_ms = max(
                    max((now - quote.ts).total_seconds() * 1000.0, 0.0)
                    for quote in quotes
                )
                if max_age_ms > stale_threshold_ms:
                    if not warned:
                        log.warning(
                            "[FeedHealth] option quotes stale | max_age_ms=%.0f threshold_ms=%.0f",
                            max_age_ms,
                            stale_threshold_ms,
                        )
                    with self._lock:
                        self._feed_health_warned = True
                elif warned:
                    log.info(
                        "[FeedHealth] option quotes healthy | max_age_ms=%.0f threshold_ms=%.0f",
                        max_age_ms,
                        stale_threshold_ms,
                    )
                    with self._lock:
                        self._feed_health_warned = False

            sleep(check_interval_s)

    def _direct_itm_strike(self, spot: float, option_type: str, strike_step: float) -> float:
        if strike_step <= 0:
            return float(round(spot))
        steps = math.floor(spot / strike_step)
        if option_type == "CE":
            target = steps * strike_step
            if math.isclose(target, spot, rel_tol=0.0, abs_tol=1e-9):
                target -= strike_step
            return float(target)
        target = math.ceil(spot / strike_step) * strike_step
        if math.isclose(target, spot, rel_tol=0.0, abs_tol=1e-9):
            target += strike_step
        return float(target)

    def _atm_strike(self, spot: float, strike_step: float) -> float:
        if strike_step <= 0:
            return float(round(spot))
        return float(math.floor((spot / strike_step) + 0.5) * strike_step)

    def _target_strike_for_bucket(
        self,
        spot: float,
        option_type: str,
        strike_step: float,
        watch_bucket: str,
    ) -> float:
        bucket = str(watch_bucket).upper()
        if bucket == "ATM":
            return self._atm_strike(spot, strike_step)
        itm1 = self._direct_itm_strike(spot, option_type, strike_step)
        if bucket == "ITM2":
            if option_type == "CE":
                return float(itm1 - strike_step)
            return float(itm1 + strike_step)
        return float(itm1)

    def _contract_for_watch_bucket(
        self,
        strikes_map: Dict[float, OptionContract],
        spot: float,
        target_strike: float,
        option_type: str,
        watch_bucket: str,
    ) -> Optional[OptionContract]:
        contract = strikes_map.get(float(target_strike))
        if contract is not None:
            return contract
        if str(watch_bucket).upper() == "ATM":
            if not strikes_map:
                return None
            ordered = sorted(strikes_map)
            chosen = min(
                ordered,
                key=lambda strike: (abs(float(strike) - float(target_strike)), abs(float(strike) - float(spot))),
            )
            return strikes_map.get(float(chosen))
        return self._nearest_contract(strikes_map, float(spot), float(target_strike), option_type)

    def _watch_labels_for_contract(self, contract: OptionContract) -> List[str]:
        labels: List[str] = []
        cache_key = (contract.exchange, contract.token)
        with self._lock:
            for (_, option_type, watch_bucket), watched in self._watched_option_contracts.items():
                watched_key = (watched.exchange, watched.token)
                if watched_key != cache_key:
                    continue
                labels.append(f"{option_type}_{str(watch_bucket).upper()}")
        return labels

    def _nearest_contract(
        self,
        strikes_map: Dict[float, OptionContract],
        spot: float,
        target_strike: float,
        option_type: str,
    ) -> Optional[OptionContract]:
        if not strikes_map:
            return None
        ordered = sorted(strikes_map)
        if option_type == "CE":
            preferred = [strike for strike in ordered if strike < spot]
        else:
            preferred = [strike for strike in ordered if strike > spot]
        candidates = preferred or ordered
        chosen = min(candidates, key=lambda strike: abs(float(strike) - float(target_strike)))
        return strikes_map.get(float(chosen))

    def _normalize_strike(self, raw: Any) -> float:
        strike = _to_float(raw)
        if strike > 100000:
            strike /= 100.0
        return strike

    def _extract_market_payload(self, response: Any, token: str) -> Dict[str, Any]:
        if not isinstance(response, dict):
            return {}

        data = response.get("data")
        if isinstance(data, dict):
            fetched = data.get("fetched")
            if isinstance(fetched, list):
                for item in fetched:
                    item_token = str(item.get("symbolToken") or item.get("symboltoken") or item.get("token") or "")
                    if item_token == str(token):
                        return dict(item)
            item_token = str(data.get("symbolToken") or data.get("symboltoken") or data.get("token") or "")
            if item_token == str(token):
                return dict(data)
        return {}

    def _store_quote(self, contract: OptionContract, quote: OptionQuote) -> None:
        cache_key = (contract.exchange, contract.token)
        with self._lock:
            self._quote_cache[cache_key] = quote
        watch_labels = self._watch_labels_for_contract(contract)
        if not watch_labels:
            return
        try:
            for watch_label in watch_labels:
                option_quote_saver.write(contract, quote, watch_label)
        except Exception as exc:
            log.warning(
                "[AngelOptionService] option quote persist failed | symbol=%s error=%s",
                contract.symbol,
                exc,
            )

    def _build_quote(
        self,
        contract: OptionContract,
        payload: Dict[str, Any],
        ts: datetime,
        *,
        source: str,
    ) -> OptionQuote:
        best_buy = payload.get("best_5_buy_data") or payload.get("best_buy_data") or []
        best_sell = payload.get("best_5_sell_data") or payload.get("best_sell_data") or []
        bid = self._normalize_book_price(payload.get("best_bid_price"), best_buy)
        ask = self._normalize_book_price(payload.get("best_ask_price"), best_sell)
        bid_size = self._normalize_book_qty(payload.get("best_bid_qty"), best_buy)
        ask_size = self._normalize_book_qty(payload.get("best_ask_qty"), best_sell)

        ltp = _to_float(
            payload.get("ltp")
            or payload.get("last_price")
            or payload.get("last_traded_price")
        )
        if ltp <= 0.0:
            ltp = bid or ask
        if bid <= 0.0 and ltp > 0.0:
            bid = ltp
        if ask <= 0.0 and ltp > 0.0:
            ask = ltp

        return OptionQuote(
            ltp=ltp,
            ts=ts,
            raw=dict(payload),
            bid=bid,
            ask=ask,
            bid_size=bid_size,
            ask_size=ask_size,
            source=source,
        )

    def _current_underlying_price(self, symbol: str) -> float:
        with self._lock:
            snapshot = self._underlying_quotes.get(symbol, {})
        return float(snapshot.get("price", 0.0) or 0.0)

    def _normalize_book_price(self, raw_price: Any, rows: Any) -> float:
        direct = _to_float(raw_price, 0.0)
        if direct > 0.0:
            if direct > 100000.0:
                return direct / 100.0
            if direct > 1000.0 and float(direct).is_integer():
                return direct / 100.0
            return direct
        if not isinstance(rows, list) or not rows:
            return 0.0
        row = rows[0]
        price = _to_float(row.get("price"), 0.0)
        if price > 100000.0:
            return price / 100.0
        if price > 1000.0 and float(price).is_integer():
            return price / 100.0
        return price

    def _normalize_book_qty(self, raw_qty: Any, rows: Any) -> int:
        direct = _to_int(raw_qty, 0)
        if direct > 0:
            return direct
        if not isinstance(rows, list) or not rows:
            return 0
        return _to_int(rows[0].get("quantity"), 0)

    def _parse_quote_timestamp(self, payload: Dict[str, Any]) -> datetime:
        raw = (
            payload.get("exchange_timestamp")
            or payload.get("last_traded_timestamp")
            or payload.get("quote_time")
            or 0
        )
        try:
            value = float(raw)
            if value > 10_000_000_000:
                value /= 1000.0
            if value > 0:
                return datetime.fromtimestamp(value)
        except Exception:
            pass
        return datetime.now()


angel_option_service = AngelOptionService()
