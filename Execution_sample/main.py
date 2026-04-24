"""
Unified application entry point.
"""

from __future__ import annotations

import sys
import time

from config import (
    ACTIVE_CANDLE_SYMBOLS,
    ACTIVE_TRADING_SYMBOLS,
    ALL_INSTRUMENTS,
    MAINTENANCE_CONTACT_MESSAGE,
    MAINTENANCE_MODE,
    ML_USE_MODEL,
)
from core.api_context import set_trading_api
from core.logger import log
from core.maintenance import log_maintenance_once
from execution.force_exit import check_and_force_exit, reset_for_new_session
from execution.runtime_bootstrap import initialize_live_runtime
from execution.signal_router import signal_router
from monitoring.performance_monitor import performance_monitor
from runtime.engine import LowLatencyTradingEngine
from runtime.feed_manager import LowLatencyFeedManager

_last_price = {symbol: 0.0 for symbol in ALL_INSTRUMENTS}


def _login():
    try:
        import pyotp
        from SmartApi import SmartConnect
        from config import API_KEY, CLIENT_ID, PWD, TOTP_KEY
    except ImportError as exc:
        log.error("[Main] required trading dependency missing: %s", exc)
        raise

    obj = SmartConnect(api_key=API_KEY)
    totp = pyotp.TOTP(TOTP_KEY).now()
    session = obj.generateSession(CLIENT_ID, PWD, totp)
    if not session.get("status"):
        raise RuntimeError(session.get("message", "login failed"))
    return obj, session["data"]["jwtToken"], obj.getfeedToken()


def _log_ml_status() -> None:
    if not ML_USE_MODEL:
        log.info("[Main] ML disabled")
        return
    try:
        __import__("ml")
        log.info("[Main] ML package detected")
    except Exception:
        log.warning("[Main] ML enabled in config but optional ml package is not present; continuing rule-only")


def main() -> None:
    log.info("=" * 72)
    log.info("  UNIFIED QUANT ENGINE")
    log.info("  Trading Symbols: %s", ", ".join(ACTIVE_TRADING_SYMBOLS))
    log.info("  Candle Symbols: %s", ", ".join(ACTIVE_CANDLE_SYMBOLS))
    log.info("  Tick Symbols: %s", ", ".join(ALL_INSTRUMENTS))
    log.info("=" * 72)

    if MAINTENANCE_MODE:
        log_maintenance_once("main.startup")
        log.warning("[Main] %s", MAINTENANCE_CONTACT_MESSAGE)
        return

    try:
        api, auth_token, feed_token = _login()
    except Exception as exc:
        log.error("[Main] login failed: %s", exc, exc_info=True)
        sys.exit(1)

    set_trading_api(api)
    performance_monitor.start()
    performance_monitor.on_heartbeat(
        "startup",
        {
            "engine_mode": "low_latency",
            "trading_symbols": list(ACTIVE_TRADING_SYMBOLS),
            "candle_symbols": list(ACTIVE_CANDLE_SYMBOLS),
            "tick_symbols": list(ALL_INSTRUMENTS),
        },
    )

    reset_for_new_session()
    initialize_live_runtime()

    _log_ml_status()

    strategy_count = signal_router.initialize()
    log.info("[Main] signal router ready | runtimes=%d", strategy_count)
    engine = LowLatencyTradingEngine(
        signal_router=signal_router,
        last_price_store=_last_price,
    )
    feed_manager = LowLatencyFeedManager(auth_token, feed_token, engine=engine)
    feed_manager.start()

    try:
        while True:
            time.sleep(1)
            check_and_force_exit(_last_price)
    except KeyboardInterrupt:
        log.info("[Main] shutdown requested")
        sys.exit(0)
    except Exception as exc:
        log.error("[Main] fatal error: %s", exc, exc_info=True)
        sys.exit(1)
    finally:
        if "feed_manager" in locals() and hasattr(feed_manager, "stop"):
            try:
                feed_manager.stop()
            except Exception:
                log.exception("[Main] feed manager stop failed")
        performance_monitor.stop()


if __name__ == "__main__":
    main()
