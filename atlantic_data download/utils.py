import logging
import random
import time
from datetime import datetime, timezone
from pathlib import Path

def setup_logger(name: str = "twelve_data_system", level=logging.INFO) -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    logger.setLevel(level)

    ch = logging.StreamHandler()
    ch.setLevel(level)
    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    ch.setFormatter(formatter)
    logger.addHandler(ch)
    return logger

def sanitize_symbol(symbol: str) -> str:
    return symbol.replace("/", "").replace(":", "").strip().upper()

def symbol_dir(base_data_dir: Path, symbol: str) -> Path:
    p = base_data_dir / sanitize_symbol(symbol)
    p.mkdir(parents=True, exist_ok=True)
    return p

def normalize_path_for_compare(path: Path) -> str:
    return str(path.expanduser().resolve(strict=False)).lower()

def utc_now() -> datetime:
    return datetime.now(timezone.utc)

def random_backoff(min_sec: float, max_sec: float):
    t = random.uniform(min_sec, max_sec)
    time.sleep(t)
