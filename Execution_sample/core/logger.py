import logging
import sys
from pathlib import Path
from config import LOG_DIR

Path(LOG_DIR).mkdir(exist_ok=True)

def _setup() -> logging.Logger:
    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)-20s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    logger = logging.getLogger("QuantEngine")
    logger.setLevel(logging.DEBUG)

    # File handler — all levels
    fh = logging.FileHandler(f"{LOG_DIR}/engine.log", encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)

    # Console handler — INFO and above only
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)

    logger.addHandler(fh)
    logger.addHandler(ch)
    return logger

log = _setup()