"""
Application configuration.

This codebase runs intrabar on Angel paper trading for Indian index workflows.
Strategy logic must remain untouched; only the market environment, execution,
instrument metadata, and runtime controls are adapted here.
"""

from __future__ import annotations

import os


MAINTENANCE_MODE = True
MAINTENANCE_CONTACT_NAME = "Raj"
MAINTENANCE_CONTACT_EMAIL = "rajydv141@gmail.com"
MAINTENANCE_CONTACT_MESSAGE = f"Contact admin {MAINTENANCE_CONTACT_NAME}: {MAINTENANCE_CONTACT_EMAIL}"


def timeframe_label(tf_seconds: int) -> str:
    """Return a stable human-readable label for a second-based timeframe."""
    if tf_seconds % 60 == 0:
        return f"{tf_seconds // 60}m"
    return f"{int(tf_seconds)}s"


def candles_per_session(tf_seconds: int, session_minutes: int = 375) -> int:
    """Estimate the number of bars per regular trading session."""
    return max((session_minutes * 60) // int(tf_seconds), 1)


# Credentials
API_KEY = "ctl6ZR9I"
SECRET_KEY = "cbdc7c4c-2b15-4f4f-b76c-80a6f82cc585"
CLIENT_ID = "R507871"
PWD = "2012"
TOTP_KEY = "JXFNP4AGCXVSCTQKJVRQPKQ4PY"


# Broker/runtime
BROKER_NAME = "ANGEL"
PAPER_MODE = True
PAPER_TRADE_CAPITAL_RS = 5000.0
PAPER_IGNORE_FEES = True
PAPER_BROKERAGE_PER_ORDER_RS = 0.0
FAST_ITM1_EXECUTION_MODE = True
PAPER_SLIPPAGE_TICKS = 1
PAPER_ORDER_TYPE = "BOOK_LADDER"
ACTIVE_EXECUTION_MODES = ("TYPE_B",)
ANGEL_PRICE_SCALE = 100.0
ANGEL_WS_SUBSCRIPTION_MODE = 3
ANGEL_MARKETDATA_MODE = "FULL"
OPTION_ITM_DEPTH = 1
OPTION_LOG_BUCKETS = ("ATM", "ITM1", "ITM2")
OPTION_LOTS_PER_TRADE = 1
OPTION_QUOTE_CACHE_MS = 900
OPTION_QUOTE_STALENESS_LIMIT_MS = 50
OPTION_EXECUTION_MAX_QUOTE_AGE_MS = 0.0
INDEX_EXECUTION_MAX_QUOTE_AGE_MS = 0.0
OPTION_SIGNAL_MAX_AGE_MS = 0.0
OPTION_LADDER_STRIKES_EACH_SIDE = 0
OPTION_LADDER_RETRY_COOLDOWN_S = 30.0
OPTION_ORDER_INITIAL_WAIT_MS = 40
OPTION_ORDER_FINAL_WAIT_MS = 30
OPTION_ORDER_POLL_MS = 2
OPTION_BOOK_PRICE_STEP_RS = 0.10
OPTION_BOOK_MAX_SPREAD_RS = 1.0
OPTION_BOOK_MAX_SLIPPAGE_RS = 0.40
OPTION_ENTRY_STEP_WAIT_MS = 20
OPTION_EXIT_STEP_WAIT_MS = 15
OPTION_ENTRY_MAX_EXECUTION_MS = 50
OPTION_EXIT_MAX_EXECUTION_MS = 45
OPTION_LIVE_ORDER_SETTLE_MS = 250
OPTION_LIVE_ORDER_MAX_POLLS = 2
OPTION_FEED_HEALTH_STALE_MS = 5000.0
OPTION_FEED_HEALTH_CHECK_S = 2.0
OPTION_ORDER_TIF = "IOC"
OPTION_ORDER_VARIETY = "NORMAL"
OPTION_ORDER_PRODUCT_TYPE = "INTRADAY"
AB_TEST_MULTI_EXECUTION_ENABLED = True
AB_TEST_TARGET_LOTS = 1
AB_TEST_QUOTE_MAX_AGE_MS = 0.0
AB_TEST_MAX_SPREAD_RS = 0.0
AB_TEST_ENTRY_DEADLINE_MS = 50
AB_TEST_EXIT_DEADLINE_MS = 40
LOW_LATENCY_MAX_ABS_SPREAD_RS = 1.0
LOW_LATENCY_MAX_QUOTE_AGE_MS = 0.0
LOW_LATENCY_LIMIT_REPRICE_WAIT_MS = 40
LOW_LATENCY_ORDER_POLL_MS = 10


# Supported live timeframes (seconds)
TIMEFRAMES = [5, 10, 15, 30, 60, 120]
HISTORICAL_WARMUP_ENABLED = True
HISTORICAL_WARMUP_CANDLES = 350
HISTORICAL_WARMUP_FETCH_DELAY_S = 0.35
HISTORICAL_WARMUP_API_CHUNK_DAYS = 5


# Session times (India cash market)
MARKET_START = "09:15"
ENTRY_START = "09:18"
ENTRY_CUTOFF_TIME = "15:25"
FORCE_EXIT_TIME = "15:28"
MARKET_END = "15:30"


# Instruments
INSTRUMENTS = {
    "NIFTY": {
        "token": "99926000",
        "exchange": "nse_cm",
        "exchange_type": 1,
        "symbol": "Nifty 50",
        "broker_symbol": "NIFTY",
        "angel_symbol": "Nifty 50",
        "instrument_type": "INDEX",
        "asset_kind": "spot_index",
        "lot_size": 50,
        "tick_size": 0.05,
        "strike_step": 50,
        "price_limit": 500,
        "derivative_root": "NIFTY",
        "supports_options": True,
        "supports_futures": True,
    },
    "BANKNIFTY": {
        "token": "99926009",
        "exchange": "nse_cm",
        "exchange_type": 1,
        "symbol": "Nifty Bank",
        "broker_symbol": "BANKNIFTY",
        "angel_symbol": "Nifty Bank",
        "instrument_type": "INDEX",
        "asset_kind": "spot_index",
        "lot_size": 15,
        "tick_size": 0.05,
        "strike_step": 100,
        "price_limit": 1000,
        "derivative_root": "BANKNIFTY",
        "supports_options": True,
        "supports_futures": True,
    },
    "FINNIFTY": {
        "token": "99926037",
        "exchange": "nse_cm",
        "exchange_type": 1,
        "symbol": "Nifty Fin Service",
        "broker_symbol": "FINNIFTY",
        "angel_symbol": "Nifty Fin Service",
        "instrument_type": "INDEX",
        "asset_kind": "spot_index",
        "lot_size": 40,
        "tick_size": 0.05,
        "strike_step": 50,
        "price_limit": 500,
        "derivative_root": "FINNIFTY",
        "supports_options": True,
        "supports_futures": True,
    },
    "SENSEX": {
        "token": "99919000",
        "exchange": "bse_cm",
        "exchange_type": 3,
        "symbol": "SENSEX",
        "broker_symbol": "SENSEX",
        "angel_symbol": "SENSEX",
        "instrument_type": "INDEX",
        "asset_kind": "spot_index",
        "lot_size": 10,
        "tick_size": 0.05,
        "strike_step": 100,
        "price_limit": 1000,
        "derivative_root": "SENSEX",
        "supports_options": True,
        "supports_futures": True,
    },
}

ACTIVE_TRADING_SYMBOLS = ("NIFTY",)
ACTIVE_CANDLE_SYMBOLS = ACTIVE_TRADING_SYMBOLS
ALL_INSTRUMENTS = {
    symbol: dict(INSTRUMENTS[symbol])
    for symbol in ACTIVE_TRADING_SYMBOLS
    if symbol in INSTRUMENTS
}


# Calculation parameters
CALC_BASE_WINDOW = 2
CALC_CONFIRM_WINDOW = 2
CALC_GRADIENT_WINDOW = 1
CALC_GRADIENT_SMOOTHING = 0
RTC_SMOOTHING_WINDOW = 1
RTC_USE_SMOOTHING = False
CALC_FLOW_WINDOW = 2
CALC_SERIES_WINDOWS = [9, 16, 21]

RTC_PARAMETER_GRID = [
    (1.5, 1),
    (2, 2),
    (0.75, 1),
    (0.5, 1),
]


# Volume availability
NO_VOLUME_SYMBOLS = {"NIFTY", "BANKNIFTY", "FINNIFTY", "SENSEX"}


# Generic decision levels
ENTRY_PROFILE_A = -1.0
ENTRY_PROFILE_B = 24.0
ENTRY_PROFILE_C = 0.0
RTC_EXIT_PROFILE = (0.75, 1)
EXIT_COMPONENT_LEVEL = 3.5
SIGNAL_STABILITY_MS = 0


# Runtime paths
DATA_DIR = "data"
LOG_DIR = "logs"
MODEL_DIR = "models"
MONITORING_DIR = os.path.join(DATA_DIR, "monitoring")
for _path in (DATA_DIR, LOG_DIR, MODEL_DIR, MONITORING_DIR):
    os.makedirs(_path, exist_ok=True)

ANGEL_SCRIP_MASTER_URL = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
ANGEL_SCRIP_MASTER_CACHE = os.path.join(DATA_DIR, "angel_scrip_master.json")


# Machine learning flags (optional subsystem)
ML_USE_MODEL = True
ML_LABEL_FORWARD_BARS = 5
ML_LABEL_THRESHOLD = 0.0015
ML_TEST_SIZE = 0.20
ML_MIN_ROWS = 500
ML_RANDOM_STATE = 42
ML_MIN_BUY_PROB = 0.45
ML_MIN_SELL_PROB = 0.45

LGBM_PARAMS = {
    "objective": "multiclass",
    "num_class": 3,
    "boosting_type": "gbdt",
    "n_estimators": 400,
    "learning_rate": 0.03,
    "max_depth": 5,
    "num_leaves": 31,
    "min_child_samples": 20,
    "subsample": 0.8,
    "colsample_bytree": 0.7,
    "reg_alpha": 0.1,
    "reg_lambda": 0.1,
    "class_weight": "balanced",
    "random_state": ML_RANDOM_STATE,
    "n_jobs": -1,
    "verbose": -1,
}


# Runtime controls
KILL_SWITCH_SECONDS = 20
MAX_STRATEGIES = 8
RUNTIME_STARTUP_WARMUP_TICKS = 30


# Observability
MONITORING_ENABLED = True
MONITORING_EVENT_HOOK_MODE = True
MONITORING_LOG_PARSER_MODE = False
MONITORING_WRAPPER_MODE = False
MONITORING_DASHBOARD_INTERVAL_S = 30.0
MONITORING_RESOURCE_INTERVAL_S = 5.0
MONITORING_ALERT_COOLDOWN_S = 60.0
MONITORING_SNAPSHOT_WINDOW = 5000
MONITORING_RATE_WINDOW_S = 5.0
MONITORING_EVENT_QUEUE_SIZE = 50000
MONITORING_LATENCY_LIMIT_MS = 250.0
MONITORING_QUEUE_LIMIT = 5000
MONITORING_API_FAILURE_LIMIT_PCT = 10.0
MONITORING_TICK_DELAY_LIMIT_MS = 1000.0
MONITORING_SLOW_TICK_LIMIT_MS = 20.0
MONITORING_NO_FILL_SIGNAL_LIMIT = 25
MONITORING_CPU_WARN_PCT = 85.0
MONITORING_MEMORY_WARN_MB = 2048.0
MONITORING_PERSIST_JSONL = True
MONITORING_PERSIST_CSV = True
MONITORING_LOG_DASHBOARD = True
MONITORING_LOG_PATH = os.path.join(LOG_DIR, "engine.log")

INDICATOR_CACHE_CONFIG = {
    "enabled": True,
    "max_age_ms": 250,
    "track_stats": True,
}

FEED_DEAD_SECONDS = 30


# Low-latency runtime
LOW_LATENCY_CANDLE_WORKERS = 4
LOW_LATENCY_TICK_QUEUE_LIMIT = 1000
LOW_LATENCY_QUEUE_PUT_TIMEOUT_MS = 2.0
LOW_LATENCY_STRATEGY_QUEUE_LIMIT = 1000
LOW_LATENCY_EXECUTION_QUEUE_LIMIT = 500
LOW_LATENCY_DISPATCH_PRICE_THRESHOLD = 0.05
LOW_LATENCY_SIGNAL_MAX_AGE_MS = 0.0
LOW_LATENCY_HARD_LATENCY_LIMIT_MS = 500.0
LOW_LATENCY_SIGNAL_PRICE_DRIFT_LIMIT = 5.0
LOW_LATENCY_QUEUE_WARNING_RATIO = 0.75
LOW_LATENCY_LOAD_SHED_COOLDOWN_S = 5.0
LOW_LATENCY_IDLE_DRAIN_TIMEOUT_S = 10.0
LOW_LATENCY_BENCHMARK_OUTPUT = os.path.join(MONITORING_DIR, "low_latency_benchmark.json")
