"""
Angel One websocket feed adapter for Indian index paper trading.
"""

from __future__ import annotations

import threading
import time
from datetime import datetime

from SmartApi.smartWebSocketV2 import SmartWebSocketV2

from config import (
    ANGEL_PRICE_SCALE,
    ANGEL_WS_SUBSCRIPTION_MODE,
    API_KEY,
    CLIENT_ID,
    ALL_INSTRUMENTS,
)
from core.instrument_registry import get_instrument, resolve_symbol_from_token
from core.logger import log
from execution.angel_option_service import OptionContract, angel_option_service
from feeds.tick_queue import TickQueue
from feeds.tick_validator import TickValidator

RECONNECT_BASE_DELAY = 5
RECONNECT_MAX_DELAY = 60
RECONNECT_MAX_RETRIES = 20
OPTION_SUBSCRIPTION_CORRELATION_ID = "ANGEL_LIVE"


class AngelFeed:
    def __init__(self, auth_token: str, feed_token: str, tick_queue: TickQueue):
        self.auth_token = auth_token.replace("Bearer ", "").strip()
        self.feed_token = feed_token
        self._queue = tick_queue
        self.sws = None

        sub_map: dict[int, list[str]] = {}
        self._token_map: dict[str, str] = {}
        for name, info in ALL_INSTRUMENTS.items():
            token = str(info["token"])
            exchange_type = int(info.get("exchange_type", 1))
            sub_map.setdefault(exchange_type, []).append(token)
            self._token_map[token] = name

        self._base_tokens = [
            {"exchangeType": exchange_type, "tokens": tokens}
            for exchange_type, tokens in sub_map.items()
        ]
        self._dynamic_tokens: dict[int, set[str]] = {}
        self._dynamic_lock = threading.RLock()
        angel_option_service.bind_feed(self)

        log.info(
            "[AngelFeed] subscription plan:\n%s",
            "\n".join(
                f"  exchangeType={exchange_type}: {tokens}"
                for exchange_type, tokens in sub_map.items()
            ),
        )

        self._reconnect_count = 0
        self._reconnect_active = False
        self._connected = False
        self._shutdown = False
        self._reconnect_lock = threading.Lock()

    def start(self) -> None:
        self._shutdown = False
        self._launch_ws_thread()

    def stop(self) -> None:
        self._shutdown = True
        self._connected = False
        try:
            if self.sws:
                self.sws.close_connection()
        except Exception:
            pass

    def _launch_ws_thread(self) -> None:
        try:
            self.sws = SmartWebSocketV2(
                self.auth_token,
                API_KEY,
                CLIENT_ID,
                self.feed_token,
            )
            self.sws.on_data = self._on_data
            self.sws.on_open = self._on_open
            self.sws.on_error = self._on_error
            self.sws.on_close = self._on_close

            thread = threading.Thread(
                target=self.sws.connect,
                name=f"AngelWS-{self._reconnect_count}",
                daemon=True,
            )
            thread.start()
        except Exception as exc:
            log.error("[AngelFeed] launch error: %s", exc, exc_info=True)
            self._schedule_reconnect()

    def _on_open(self, wsapp) -> None:
        del wsapp
        self._connected = True
        self._reconnect_count = 0
        log.info("[AngelFeed] websocket connected")
        time.sleep(0.5)
        self._subscribe()

    def _subscribe(self) -> None:
        self._subscribe_payload(self._base_tokens, label="base")
        dynamic_payload = self._dynamic_payload()
        if dynamic_payload:
            self._subscribe_payload(dynamic_payload, label="options")

    def _subscribe_payload(self, payload, *, label: str) -> None:
        if not payload:
            return
        try:
            self.sws.subscribe("ANGEL_LIVE", ANGEL_WS_SUBSCRIPTION_MODE, payload)
            token_count = sum(len(item.get("tokens", [])) for item in payload)
            log.info("[AngelFeed] subscribed | label=%s instruments=%d", label, token_count)
        except Exception as exc:
            log.error("[AngelFeed] subscribe error | label=%s error=%s", label, exc, exc_info=True)

    def _dynamic_payload(self):
        with self._dynamic_lock:
            return [
                {"exchangeType": exchange_type, "tokens": sorted(tokens)}
                for exchange_type, tokens in self._dynamic_tokens.items()
                if tokens
            ]

    def subscribe_option_contract(self, contract: OptionContract) -> None:
        token = str(contract.token)
        exchange_type = int(contract.exchange_type)
        with self._dynamic_lock:
            tokens = self._dynamic_tokens.setdefault(exchange_type, set())
            if token in tokens:
                return
            tokens.add(token)
        if self._connected and self.sws is not None:
            self._subscribe_payload(
                [{"exchangeType": exchange_type, "tokens": [token]}],
                label=f"option:{contract.symbol}",
            )

    def unsubscribe_option_contract(self, contract: OptionContract) -> None:
        token = str(contract.token)
        exchange_type = int(contract.exchange_type)
        removed = False
        with self._dynamic_lock:
            tokens = self._dynamic_tokens.get(exchange_type)
            if tokens is None or token not in tokens:
                return
            tokens.discard(token)
            if not tokens:
                self._dynamic_tokens.pop(exchange_type, None)
            removed = True
        if not removed or not self._connected or self.sws is None:
            return
        try:
            self.sws.unsubscribe(
                OPTION_SUBSCRIPTION_CORRELATION_ID,
                ANGEL_WS_SUBSCRIPTION_MODE,
                [{"exchangeType": exchange_type, "tokens": [token]}],
            )
            log.info("[AngelFeed] unsubscribed | label=option:%s instruments=1", contract.symbol)
        except Exception as exc:
            log.error(
                "[AngelFeed] unsubscribe error | label=option:%s error=%s",
                contract.symbol,
                exc,
                exc_info=True,
            )

    def _on_error(self, wsapp, error) -> None:
        del wsapp
        err = str(error)
        if "Please login first" in err or "Invalid token" in err:
            return
        log.error("[AngelFeed] websocket error: %s", error)
        self._handle_disconnect("error")

    def _on_close(self, wsapp) -> None:
        del wsapp
        log.warning("[AngelFeed] websocket closed")
        self._handle_disconnect("close")

    def _handle_disconnect(self, reason: str) -> None:
        self._connected = False
        if self._shutdown:
            return
        with self._reconnect_lock:
            if self._reconnect_active:
                return
            self._reconnect_active = True
        thread = threading.Thread(
            target=self._reconnect_loop,
            name="AngelReconnect",
            daemon=True,
            kwargs={"reason": reason},
        )
        thread.start()

    def _schedule_reconnect(self) -> None:
        self._handle_disconnect("launch")

    def _reconnect_loop(self, reason: str) -> None:
        try:
            while not self._shutdown:
                self._reconnect_count += 1
                if self._reconnect_count > RECONNECT_MAX_RETRIES:
                    log.critical("[AngelFeed] max reconnects reached | reason=%s", reason)
                    break

                delay = min(
                    RECONNECT_BASE_DELAY * (2 ** (self._reconnect_count - 1)),
                    RECONNECT_MAX_DELAY,
                )
                log.warning(
                    "[AngelFeed] reconnect #%d in %ss | reason=%s",
                    self._reconnect_count,
                    delay,
                    reason,
                )
                time.sleep(delay)
                if self._shutdown:
                    break

                self._launch_ws_thread()
                for _ in range(30):
                    time.sleep(0.5)
                    if self._connected:
                        with self._reconnect_lock:
                            self._reconnect_active = False
                        return
        except Exception as exc:
            log.error("[AngelFeed] reconnect error: %s", exc, exc_info=True)
        finally:
            with self._reconnect_lock:
                self._reconnect_active = False

    def _normalize_price(self, raw_value) -> float:
        return float(raw_value or 0.0) / ANGEL_PRICE_SCALE

    def _normalize_depth_price(self, rows, side: str) -> float:
        if not isinstance(rows, list) or not rows:
            return 0.0
        row = rows[0]
        del side
        return self._normalize_price(row.get("price"))

    def _normalize_depth_qty(self, rows) -> int:
        if not isinstance(rows, list) or not rows:
            return 0
        return int(float(rows[0].get("quantity", 0) or 0))

    def _normalize_oi_change(self, raw_value) -> float:
        try:
            value = float(raw_value or 0.0)
        except (TypeError, ValueError):
            return 0.0
        if abs(value) > 1000:
            return 0.0
        return value

    def _parse_timestamp(self, raw_timestamp) -> datetime:
        if raw_timestamp in (None, "", 0, "0"):
            return datetime.now()

        try:
            value = float(raw_timestamp)
            if value > 10_000_000_000:
                value /= 1000.0
            return datetime.fromtimestamp(value)
        except Exception:
            return datetime.now()

    def _on_data(self, wsapp, message) -> None:
        del wsapp

        try:
            if "last_traded_price" not in message:
                return

            token = str(message.get("token", ""))
            symbol = resolve_symbol_from_token(token) or self._token_map.get(token)
            ts = self._parse_timestamp(message.get("exchange_timestamp"))
            if not symbol:
                angel_option_service.ingest_ws_quote(message, ts)
                return

            instrument = get_instrument(symbol)
            raw_ltp = float(message["last_traded_price"])
            ltp = self._normalize_price(raw_ltp)
            volume = int(message.get("volume_trade_for_the_day", 0) or 0)
            best_buy = message.get("best_5_buy_data") or []
            best_sell = message.get("best_5_sell_data") or []
            best_bid_price = self._normalize_depth_price(best_buy, "buy")
            best_ask_price = self._normalize_depth_price(best_sell, "sell")

            raw = {
                "volume": volume,
                "market_volume_day": volume,
                "token": token,
                "exchange_type": instrument.exchange_type,
                "angel_symbol": instrument.angel_symbol,
                "subscription_mode": int(message.get("subscription_mode", ANGEL_WS_SUBSCRIPTION_MODE)),
                "sequence_number": int(message.get("sequence_number", 0) or 0),
                "last_traded_quantity": int(message.get("last_traded_quantity", 0) or 0),
                "average_traded_price": self._normalize_price(message.get("average_traded_price", 0)),
                "total_buy_quantity": float(message.get("total_buy_quantity", 0) or 0),
                "total_sell_quantity": float(message.get("total_sell_quantity", 0) or 0),
                "open_price_of_the_day": self._normalize_price(message.get("open_price_of_the_day", 0)),
                "high_price_of_the_day": self._normalize_price(message.get("high_price_of_the_day", 0)),
                "low_price_of_the_day": self._normalize_price(message.get("low_price_of_the_day", 0)),
                "closed_price": self._normalize_price(message.get("closed_price", 0)),
                "last_traded_timestamp": int(float(message.get("last_traded_timestamp", 0) or 0)),
                "open_interest": int(float(message.get("open_interest", 0) or 0)),
                "open_interest_change_percentage": self._normalize_oi_change(message.get("open_interest_change_percentage", 0)),
                "upper_circuit_limit": self._normalize_price(message.get("upper_circuit_limit", 0)),
                "lower_circuit_limit": self._normalize_price(message.get("lower_circuit_limit", 0)),
                "year_high_price": self._normalize_price(message.get("52_week_high_price", 0)),
                "year_low_price": self._normalize_price(message.get("52_week_low_price", 0)),
                "best_bid_price": best_bid_price,
                "best_bid_qty": self._normalize_depth_qty(best_buy),
                "best_ask_price": best_ask_price,
                "best_ask_qty": self._normalize_depth_qty(best_sell),
                "spread": max(best_ask_price - best_bid_price, 0.0) if best_bid_price and best_ask_price else 0.0,
                "raw_message": dict(message),
            }

            if not TickValidator.validate(symbol, ltp, ts, "angel"):
                return

            angel_option_service.update_underlying_price(symbol, ltp, ts)
            self._queue.enqueue(symbol, ltp, ts, raw)
        except Exception as exc:
            log.error("[AngelFeed] on_data failure: %s", exc, exc_info=True)
