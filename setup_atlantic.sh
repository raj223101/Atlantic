#!/usr/bin/env bash
set -euo pipefail

# Atlantic repository bootstrap script
# Python 3.10+ scaffold with modular architecture and placeholders only.

mkdir -p src/{data/{historical,realtime,storage},research/{strategies,indicators,feature_engineering,evaluation},backtest,execution/brokers,intelligence,utils}
mkdir -p config notebooks tests

# ------------------------------
# Root files
# ------------------------------
cat << 'EOF' > main.py
"""Application entry point for Atlantic trading system."""

from __future__ import annotations

import logging

from src.backtest.engine import BacktestEngine
from src.research.strategies.base import BaseStrategy
from src.execution.order_manager import OrderManager
from src.execution.risk_manager import RiskManager
from src.execution.portfolio import PortfolioTracker

LOGGER = logging.getLogger(__name__)


def configure_logging() -> None:
    """Configure application-wide logging."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )


def main() -> None:
    """Run a minimal application flow."""
    configure_logging()
    LOGGER.info("Starting Atlantic trading system")

    strategy: BaseStrategy = BaseStrategy(name="placeholder_strategy")
    order_manager = OrderManager()
    risk_manager = RiskManager()
    portfolio = PortfolioTracker()

    engine = BacktestEngine(
        strategy=strategy,
        order_manager=order_manager,
        risk_manager=risk_manager,
        portfolio_tracker=portfolio,
    )
    engine.run()

    LOGGER.info("Atlantic trading system finished")


if __name__ == "__main__":
    main()
EOF

cat << 'EOF' > requirements.txt
pandas
numpy
pyyaml
EOF

cat << 'EOF' > .gitignore
# Python
__pycache__/
*.py[cod]
*.so
.venv/
venv/
.env
.pytest_cache/
.mypy_cache/
.coverage
htmlcov/

# IDE
.vscode/
.idea/

# Data files
data/
*.csv
*.tsv
*.parquet
*.feather
*.h5
*.hdf5
*.xlsx
*.xls
*.jsonl

# Logs
*.log
logs/

# Jupyter
.ipynb_checkpoints/

# OS
.DS_Store
Thumbs.db
EOF

cat << 'EOF' > README.md
# Atlantic

Atlantic is a production-grade Python trading system scaffold designed for scalability, modularity, and clean separation of responsibilities.

> **Important:** This repository intentionally excludes proprietary strategy logic, real trading rules, and API credentials.

## Architecture

The system is organized into clear layers:

- **Data Layer (`src/data`)**
  - Historical tick downloader
  - Realtime tick stream consumer
  - Parquet-based storage abstraction

- **Research & Backtest Layer (`src/research`, `src/backtest`)**
  - Pluggable strategy classes (placeholder signals only)
  - Indicator and feature engineering scaffolds
  - Event-driven backtest engine
  - Performance evaluation metrics scaffold

- **Execution Layer (`src/execution`)**
  - Abstract broker interface (`BaseBroker`)
  - Broker stubs: Flattrade, Delta Exchange, IC Markets
  - Order manager, risk manager, portfolio tracker

- **Intelligence Layer (`src/intelligence`)**
  - Trade-to-candle mapping with `pandas.merge_asof`
  - Slippage placeholder analysis
  - MAE/MFE placeholder analysis
  - Execution quality placeholder metrics

- **Utilities (`src/utils`)**
  - Shared logging and configuration helpers

## Design Principles

- Python 3.10+
- Type hints throughout
- Standard `logging` usage
- Clear docstrings
- Dependency injection in core components
- Minimal dependencies

## Repository Structure

- `src/` source modules
- `config/` configuration files
- `notebooks/` research notebooks
- `tests/` unit tests
- `main.py` application entry point
- `requirements.txt` minimal dependencies

## Disclaimer

This project is an architectural scaffold and does not contain:
- proprietary strategy logic
- live trading rules
- broker API keys or secrets
EOF

# ------------------------------
# Package init files
# ------------------------------
cat << 'EOF' > src/__init__.py
"""Atlantic source package."""
EOF

cat << 'EOF' > src/data/__init__.py
"""Data layer package."""
EOF

cat << 'EOF' > src/data/historical/__init__.py
"""Historical data module."""
EOF

cat << 'EOF' > src/data/realtime/__init__.py
"""Realtime data module."""
EOF

cat << 'EOF' > src/data/storage/__init__.py
"""Storage module."""
EOF

cat << 'EOF' > src/research/__init__.py
"""Research layer package."""
EOF

cat << 'EOF' > src/research/strategies/__init__.py
"""Strategies package."""
EOF

cat << 'EOF' > src/research/indicators/__init__.py
"""Indicators package."""
EOF

cat << 'EOF' > src/research/feature_engineering/__init__.py
"""Feature engineering package."""
EOF

cat << 'EOF' > src/research/evaluation/__init__.py
"""Evaluation package."""
EOF

cat << 'EOF' > src/backtest/__init__.py
"""Backtest package."""
EOF

cat << 'EOF' > src/execution/__init__.py
"""Execution package."""
EOF

cat << 'EOF' > src/execution/brokers/__init__.py
"""Broker integrations package."""
EOF

cat << 'EOF' > src/intelligence/__init__.py
"""Intelligence layer package."""
EOF

cat << 'EOF' > src/utils/__init__.py
"""Utilities package."""
EOF

# ------------------------------
# Data layer
# ------------------------------
cat << 'EOF' > src/data/historical/downloader.py
"""Historical tick data downloader module."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

import pandas as pd

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class HistoricalDataRequest:
    """Request definition for historical data download."""

    market: str
    symbol: str
    start: datetime
    end: datetime


class HistoricalDataDownloader:
    """Download historical tick data for multiple markets."""

    def fetch_ticks(self, request: HistoricalDataRequest) -> pd.DataFrame:
        """Fetch historical ticks.

        Args:
            request: Historical data request.

        Returns:
            Placeholder tick dataframe.

        TODO:
            Implement exchange-specific historical data clients.
        """
        LOGGER.info(
            "Fetching historical ticks | market=%s symbol=%s start=%s end=%s",
            request.market,
            request.symbol,
            request.start.isoformat(),
            request.end.isoformat(),
        )
        df = pd.DataFrame(
            {
                "timestamp": pd.to_datetime([], utc=True),
                "price": pd.Series([], dtype="float64"),
                "size": pd.Series([], dtype="float64"),
                "symbol": pd.Series([], dtype="string"),
            }
        )
        return df
EOF

cat << 'EOF' > src/data/realtime/stream.py
"""Realtime tick streaming module."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timezone

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class Tick:
    """Realtime tick event."""

    timestamp: datetime
    symbol: str
    price: float
    size: float


class RealtimeTickStreamer:
    """Stream realtime ticks from market data providers."""

    def stream(self, market: str, symbol: str) -> Iterator[Tick]:
        """Yield realtime ticks as an iterator.

        Args:
            market: Market name (e.g., india, crypto, forex).
            symbol: Trading symbol.

        Yields:
            Tick objects.

        TODO:
            Connect to realtime market feed providers.
        """
        LOGGER.info("Starting realtime stream | market=%s symbol=%s", market, symbol)
        # Placeholder: no live connection.
        return
        yield Tick(
            timestamp=datetime.now(timezone.utc),
            symbol=symbol,
            price=0.0,
            size=0.0,
        )
EOF

cat << 'EOF' > src/data/storage/parquet_store.py
"""Parquet storage abstraction with optional in-memory cache."""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

LOGGER = logging.getLogger(__name__)


class ParquetStore:
    """Read and write parquet datasets with optional cache."""

    def __init__(self, base_path: Path) -> None:
        """Initialize parquet store.

        Args:
            base_path: Base path for persisted parquet data.
        """
        self._base_path = base_path
        self._cache: dict[str, pd.DataFrame] = {}
        self._base_path.mkdir(parents=True, exist_ok=True)

    def write(self, key: str, frame: pd.DataFrame) -> Path:
        """Write dataframe to parquet and cache it.

        Args:
            key: Logical dataset key.
            frame: Dataframe to persist.

        Returns:
            Output parquet path.
        """
        output_path = self._base_path / f"{key}.parquet"
        frame.to_parquet(output_path, index=False)
        self._cache[key] = frame.copy()
        LOGGER.info("Wrote parquet dataset | key=%s path=%s", key, output_path)
        return output_path

    def read(self, key: str, use_cache: bool = True) -> pd.DataFrame:
        """Read dataframe from cache or parquet.

        Args:
            key: Logical dataset key.
            use_cache: Whether to use in-memory cache first.

        Returns:
            Loaded dataframe.
        """
        if use_cache and key in self._cache:
            LOGGER.info("Cache hit | key=%s", key)
            return self._cache[key].copy()

        input_path = self._base_path / f"{key}.parquet"
        LOGGER.info("Reading parquet dataset | key=%s path=%s", key, input_path)
        frame = pd.read_parquet(input_path)
        if use_cache:
            self._cache[key] = frame.copy()
        return frame
EOF

# ------------------------------
# Research layer
# ------------------------------
cat << 'EOF' > src/research/strategies/base.py
"""Base strategy definitions."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import pandas as pd

LOGGER = logging.getLogger(__name__)


@dataclass
class BaseStrategy:
    """Base class for pluggable strategies."""

    name: str

    def generate_signal(self, market_data: pd.DataFrame) -> Any | None:
        """Generate trading signal from market data.

        Args:
            market_data: Input market data frame.

        Returns:
            Placeholder signal (`None`).

        TODO:
            Implement proprietary strategy logic.
        """
        LOGGER.debug("Generating signal | strategy=%s rows=%d", self.name, len(market_data))
        return None
EOF

cat << 'EOF' > src/research/strategies/sample_strategy.py
"""Sample pluggable strategy implementation with placeholder logic."""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from src.research.strategies.base import BaseStrategy

LOGGER = logging.getLogger(__name__)


class SampleStrategy(BaseStrategy):
    """A sample strategy class with no proprietary logic."""

    def __init__(self) -> None:
        """Initialize sample strategy."""
        super().__init__(name="sample_strategy")

    def generate_signal(self, market_data: pd.DataFrame) -> Any | None:
        """Generate placeholder signal.

        Args:
            market_data: Input market data.

        Returns:
            None as placeholder.
        """
        LOGGER.info("SampleStrategy called | rows=%d", len(market_data))
        # TODO: implement proprietary strategy
        return None
EOF

cat << 'EOF' > src/research/indicators/engine.py
"""Indicator engine placeholders."""

from __future__ import annotations

import logging

import pandas as pd

LOGGER = logging.getLogger(__name__)


class IndicatorEngine:
    """Compute non-proprietary indicator placeholders."""

    def compute(self, frame: pd.DataFrame) -> pd.DataFrame:
        """Return feature frame with placeholder indicators.

        Args:
            frame: Market data frame.

        Returns:
            Input frame with placeholder indicator columns.
        """
        LOGGER.info("Computing indicators | rows=%d", len(frame))
        output = frame.copy()
        output["indicator_placeholder"] = 0.0
        return output
EOF

cat << 'EOF' > src/research/feature_engineering/engine.py
"""Feature engineering placeholders."""

from __future__ import annotations

import logging

import pandas as pd

LOGGER = logging.getLogger(__name__)


class FeatureEngineeringEngine:
    """Build model/backtest features with placeholder logic."""

    def transform(self, frame: pd.DataFrame) -> pd.DataFrame:
        """Create placeholder features.

        Args:
            frame: Input dataframe.

        Returns:
            Dataframe with placeholder features.
        """
        LOGGER.info("Transforming features | rows=%d", len(frame))
        output = frame.copy()
        output["feature_placeholder"] = 0.0
        return output
EOF

cat << 'EOF' > src/research/evaluation/performance.py
"""Performance evaluation module."""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
import pandas as pd

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class PerformanceReport:
    """Performance summary report."""

    total_pnl: float
    max_drawdown: float
    sharpe_like: float


class PerformanceEvaluator:
    """Evaluate backtest outcomes using standard metrics."""

    def evaluate(self, equity_curve: pd.Series) -> PerformanceReport:
        """Compute basic performance statistics.

        Args:
            equity_curve: Equity curve series.

        Returns:
            Performance report.
        """
        LOGGER.info("Evaluating performance | points=%d", len(equity_curve))
        if equity_curve.empty:
            return PerformanceReport(total_pnl=0.0, max_drawdown=0.0, sharpe_like=0.0)

        pnl = float(equity_curve.iloc[-1] - equity_curve.iloc[0])
        running_max = equity_curve.cummax()
        drawdown = equity_curve - running_max
        max_drawdown = float(drawdown.min())
        returns = equity_curve.pct_change().dropna()
        sharpe_like = float(
            (returns.mean() / returns.std()) if (not returns.empty and returns.std() != 0) else 0.0
        )
        return PerformanceReport(total_pnl=pnl, max_drawdown=max_drawdown, sharpe_like=sharpe_like)
EOF

# ------------------------------
# Backtest layer
# ------------------------------
cat << 'EOF' > src/backtest/events.py
"""Event definitions for event-driven backtesting."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class MarketEvent:
    """Market data event."""

    timestamp: datetime
    payload: dict[str, Any]


@dataclass(frozen=True)
class SignalEvent:
    """Strategy signal event."""

    timestamp: datetime
    signal: Any | None


@dataclass(frozen=True)
class OrderEvent:
    """Order event."""

    timestamp: datetime
    order: dict[str, Any]
EOF

cat << 'EOF' > src/backtest/engine.py
"""Event-driven backtesting engine."""

from __future__ import annotations

import logging
from collections import deque
from datetime import datetime, timezone
from typing import Any

import pandas as pd

from src.backtest.events import MarketEvent, OrderEvent, SignalEvent
from src.execution.order_manager import OrderManager
from src.execution.portfolio import PortfolioTracker
from src.execution.risk_manager import RiskManager
from src.research.strategies.base import BaseStrategy

LOGGER = logging.getLogger(__name__)


class BacktestEngine:
    """Minimal event-driven backtest engine with dependency injection."""

    def __init__(
        self,
        strategy: BaseStrategy,
        order_manager: OrderManager,
        risk_manager: RiskManager,
        portfolio_tracker: PortfolioTracker,
    ) -> None:
        """Initialize engine dependencies.

        Args:
            strategy: Strategy instance.
            order_manager: Order manager dependency.
            risk_manager: Risk manager dependency.
            portfolio_tracker: Portfolio tracker dependency.
        """
        self._strategy = strategy
        self._order_manager = order_manager
        self._risk_manager = risk_manager
        self._portfolio_tracker = portfolio_tracker
        self._event_queue: deque[Any] = deque()

    def run(self) -> None:
        """Run a minimal event loop."""
        LOGGER.info("Starting backtest run")
        market_frame = pd.DataFrame({"price": [100.0, 101.0, 99.5]})
        market_event = MarketEvent(timestamp=datetime.now(timezone.utc), payload={"data": market_frame})
        self._event_queue.append(market_event)

        while self._event_queue:
            event = self._event_queue.popleft()
            self._handle_event(event)

        LOGGER.info("Backtest run complete")

    def _handle_event(self, event: Any) -> None:
        """Dispatch event to handlers.

        Args:
            event: Event instance.
        """
        if isinstance(event, MarketEvent):
            market_data = event.payload["data"]
            signal = self._strategy.generate_signal(market_data=market_data)
            self._event_queue.append(SignalEvent(timestamp=event.timestamp, signal=signal))

        elif isinstance(event, SignalEvent):
            order = self._order_manager.create_order_from_signal(event.signal)
            if order is not None and self._risk_manager.approve_order(order):
                self._event_queue.append(OrderEvent(timestamp=event.timestamp, order=order))

        elif isinstance(event, OrderEvent):
            self._portfolio_tracker.apply_order(event.order)
            LOGGER.info("Order applied to portfolio")
EOF

# ------------------------------
# Execution layer
# ------------------------------
cat << 'EOF' > src/execution/brokers/base.py
"""Abstract broker interface."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any

LOGGER = logging.getLogger(__name__)


class BaseBroker(ABC):
    """Abstract base class for broker integrations."""

    @abstractmethod
    def connect(self) -> None:
        """Connect to broker."""

    @abstractmethod
    def place_order(self, order: dict[str, Any]) -> str:
        """Place an order and return broker order ID."""

    @abstractmethod
    def cancel_order(self, broker_order_id: str) -> bool:
        """Cancel order by broker order ID."""
EOF

cat << 'EOF' > src/execution/brokers/flattrade.py
"""Flattrade broker stub."""

from __future__ import annotations

import logging
from typing import Any

from src.execution.brokers.base import BaseBroker

LOGGER = logging.getLogger(__name__)


class FlattradeBroker(BaseBroker):
    """Stub integration for Flattrade."""

    def connect(self) -> None:
        """Connect to Flattrade broker."""
        LOGGER.info("Connecting to Flattrade (stub)")
        # TODO: implement Flattrade authentication/session

    def place_order(self, order: dict[str, Any]) -> str:
        """Place order in Flattrade (stub)."""
        LOGGER.info("Placing order in Flattrade (stub)")
        # TODO: implement order placement
        return "FLATTRADE_ORDER_ID_PLACEHOLDER"

    def cancel_order(self, broker_order_id: str) -> bool:
        """Cancel order in Flattrade (stub)."""
        LOGGER.info("Cancelling order in Flattrade (stub) | id=%s", broker_order_id)
        # TODO: implement order cancellation
        return False
EOF

cat << 'EOF' > src/execution/brokers/delta.py
"""Delta Exchange broker stub."""

from __future__ import annotations

import logging
from typing import Any

from src.execution.brokers.base import BaseBroker

LOGGER = logging.getLogger(__name__)


class DeltaBroker(BaseBroker):
    """Stub integration for Delta Exchange."""

    def connect(self) -> None:
        """Connect to Delta Exchange broker."""
        LOGGER.info("Connecting to Delta Exchange (stub)")
        # TODO: implement Delta authentication/session

    def place_order(self, order: dict[str, Any]) -> str:
        """Place order in Delta Exchange (stub)."""
        LOGGER.info("Placing order in Delta Exchange (stub)")
        # TODO: implement order placement
        return "DELTA_ORDER_ID_PLACEHOLDER"

    def cancel_order(self, broker_order_id: str) -> bool:
        """Cancel order in Delta Exchange (stub)."""
        LOGGER.info("Cancelling order in Delta Exchange (stub) | id=%s", broker_order_id)
        # TODO: implement order cancellation
        return False
EOF

cat << 'EOF' > src/execution/brokers/ic_markets.py
"""IC Markets broker stub."""

from __future__ import annotations

import logging
from typing import Any

from src.execution.brokers.base import BaseBroker

LOGGER = logging.getLogger(__name__)


class ICMarketsBroker(BaseBroker):
    """Stub integration for IC Markets."""

    def connect(self) -> None:
        """Connect to IC Markets broker."""
        LOGGER.info("Connecting to IC Markets (stub)")
        # TODO: implement IC Markets authentication/session

    def place_order(self, order: dict[str, Any]) -> str:
        """Place order in IC Markets (stub)."""
        LOGGER.info("Placing order in IC Markets (stub)")
        # TODO: implement order placement
        return "ICM_ORDER_ID_PLACEHOLDER"

    def cancel_order(self, broker_order_id: str) -> bool:
        """Cancel order in IC Markets (stub)."""
        LOGGER.info("Cancelling order in IC Markets (stub) | id=%s", broker_order_id)
        # TODO: implement order cancellation
        return False
EOF

cat << 'EOF' > src/execution/order_manager.py
"""Order manager module."""

from __future__ import annotations

import logging
from typing import Any

LOGGER = logging.getLogger(__name__)


class OrderManager:
    """Create executable orders from strategy signals."""

    def create_order_from_signal(self, signal: Any | None) -> dict[str, Any] | None:
        """Convert signal into order payload.

        Args:
            signal: Strategy signal output.

        Returns:
            Order payload or None.
        """
        if signal is None:
            LOGGER.debug("No signal received; skipping order creation")
            return None

        LOGGER.info("Creating order from signal")
        # TODO: map proprietary signal schema to order payload
        return {"symbol": "PLACEHOLDER", "side": "BUY", "qty": 1.0}
EOF

cat << 'EOF' > src/execution/risk_manager.py
"""Risk management module."""

from __future__ import annotations

import logging
from typing import Any

LOGGER = logging.getLogger(__name__)


class RiskManager:
    """Apply risk checks before order submission."""

    def approve_order(self, order: dict[str, Any]) -> bool:
        """Approve or reject order by risk constraints.

        Args:
            order: Proposed order.

        Returns:
            Approval result.
        """
        LOGGER.info("Risk-checking order | symbol=%s", order.get("symbol"))
        # TODO: implement proprietary risk checks
        return True
EOF

cat << 'EOF' > src/execution/portfolio.py
"""Portfolio tracking module."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

LOGGER = logging.getLogger(__name__)


@dataclass
class PortfolioTracker:
    """Track positions and simple realized/unrealized state."""

    positions: dict[str, float] = field(default_factory=dict)

    def apply_order(self, order: dict[str, Any]) -> None:
        """Apply filled order to positions.

        Args:
            order: Order payload.
        """
        symbol = str(order.get("symbol", "UNKNOWN"))
        qty = float(order.get("qty", 0.0))
        side = str(order.get("side", "BUY")).upper()

        signed_qty = qty if side == "BUY" else -qty
        self.positions[symbol] = self.positions.get(symbol, 0.0) + signed_qty
        LOGGER.info("Updated position | symbol=%s position=%s", symbol, self.positions[symbol])
EOF

# ------------------------------
# Intelligence layer
# ------------------------------
cat << 'EOF' > src/intelligence/trade_mapping.py
"""Trade-to-candle mapping utilities."""

from __future__ import annotations

import logging

import pandas as pd

LOGGER = logging.getLogger(__name__)


class TradeToCandleMapper:
    """Map trades to nearest prior candle using merge_asof."""

    def map_trades_to_candles(
        self,
        trades: pd.DataFrame,
        candles: pd.DataFrame,
        trade_ts_col: str = "trade_timestamp",
        candle_ts_col: str = "candle_timestamp",
        by: str | None = "symbol",
    ) -> pd.DataFrame:
        """Map each trade to its corresponding candle using pandas.merge_asof.

        Args:
            trades: Trade-level dataframe.
            candles: Candle-level dataframe.
            trade_ts_col: Trade timestamp column.
            candle_ts_col: Candle timestamp column.
            by: Optional grouping key.

        Returns:
            Merged dataframe with candle context for each trade.
        """
        LOGGER.info("Mapping trades to candles with merge_asof")
        left = trades.sort_values(trade_ts_col).copy()
        right = candles.sort_values(candle_ts_col).copy()

        merged = pd.merge_asof(
            left=left,
            right=right,
            left_on=trade_ts_col,
            right_on=candle_ts_col,
            by=by,
            direction="backward",
        )
        return merged
EOF

cat << 'EOF' > src/intelligence/slippage.py
"""Slippage analysis placeholders."""

from __future__ import annotations

import logging

import pandas as pd

LOGGER = logging.getLogger(__name__)


class SlippageAnalyzer:
    """Analyze execution slippage with placeholder logic."""

    def compute_slippage(self, executions: pd.DataFrame) -> pd.DataFrame:
        """Compute placeholder slippage metrics.

        Args:
            executions: Executions dataframe.

        Returns:
            Dataframe with placeholder slippage column.
        """
        LOGGER.info("Computing slippage | rows=%d", len(executions))
        output = executions.copy()
        output["slippage"] = 0.0
        # TODO: implement proprietary slippage model
        return output
EOF

cat << 'EOF' > src/intelligence/mae_mfe.py
"""MAE/MFE analysis placeholders."""

from __future__ import annotations

import logging

import pandas as pd

LOGGER = logging.getLogger(__name__)


class MAEMFEAnalyzer:
    """Compute MAE and MFE placeholders."""

    def compute(self, trades: pd.DataFrame) -> pd.DataFrame:
        """Compute placeholder MAE/MFE.

        Args:
            trades: Trade dataframe.

        Returns:
            Dataframe with MAE/MFE placeholders.
        """
        LOGGER.info("Computing MAE/MFE | rows=%d", len(trades))
        output = trades.copy()
        output["mae"] = 0.0
        output["mfe"] = 0.0
        # TODO: implement proprietary MAE/MFE calculations
        return output
EOF

cat << 'EOF' > src/intelligence/execution_quality.py
"""Execution quality analysis placeholders."""

from __future__ import annotations

import logging

import pandas as pd

LOGGER = logging.getLogger(__name__)


class ExecutionQualityAnalyzer:
    """Compute execution quality placeholders."""

    def evaluate(self, executions: pd.DataFrame) -> pd.DataFrame:
        """Evaluate placeholder execution quality metrics.

        Args:
            executions: Executions dataframe.

        Returns:
            Dataframe with placeholder quality score.
        """
        LOGGER.info("Evaluating execution quality | rows=%d", len(executions))
        output = executions.copy()
        output["execution_quality_score"] = 0.0
        # TODO: implement proprietary execution quality metrics
        return output
EOF

# ------------------------------
# Utils
# ------------------------------
cat << 'EOF' > src/utils/logging_utils.py
"""Shared logging helpers."""

from __future__ import annotations

import logging


def setup_logging(level: int = logging.INFO) -> None:
    """Configure logging for library and application use.

    Args:
        level: Logging level.
    """
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
EOF

cat << 'EOF' > src/utils/config.py
"""Configuration loading utilities."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

LOGGER = logging.getLogger(__name__)


def load_yaml_config(path: Path) -> dict[str, Any]:
    """Load YAML configuration file.

    Args:
        path: YAML config path.

    Returns:
        Parsed config dictionary.
    """
    LOGGER.info("Loading config | path=%s", path)
    with path.open("r", encoding="utf-8") as handle:
        payload = yaml.safe_load(handle) or {}
    return dict(payload)
EOF

# ------------------------------
# Config, notebooks, tests
# ------------------------------
cat << 'EOF' > config/config.example.yaml
app:
  name: Atlantic
  environment: development

data:
  base_path: ./local_data

backtest:
  initial_capital: 100000.0
EOF

cat << 'EOF' > notebooks/.gitkeep
EOF

cat << 'EOF' > tests/test_strategy_placeholder.py
"""Tests for strategy placeholder behavior."""

from __future__ import annotations

import pandas as pd

from src.research.strategies.sample_strategy import SampleStrategy


def test_sample_strategy_returns_none() -> None:
    """Sample strategy must return None placeholder signal."""
    strategy = SampleStrategy()
    frame = pd.DataFrame({"price": [1.0, 2.0, 3.0]})
    assert strategy.generate_signal(frame) is None
EOF

echo "Atlantic repository scaffold created successfully."
