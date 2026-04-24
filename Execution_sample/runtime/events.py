from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Tuple

from execution.multi_strategy_engine import StrategySignalEvent


@dataclass(slots=True)
class TickEvent:
    symbol: str
    tick: Dict[str, Any]
    recv_epoch: float
    sequence_number: int


@dataclass(slots=True)
class SnapshotEvent:
    symbol: str
    price: float
    ts: datetime
    recv_epoch: float
    snapshots_by_tf: Dict[int, Dict[str, Any]]
    changed_tfs: Tuple[int, ...]


@dataclass(slots=True)
class ExecutionTask:
    event: StrategySignalEvent
    recv_epoch: float
