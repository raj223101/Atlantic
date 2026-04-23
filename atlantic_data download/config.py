from dataclasses import dataclass, field
from pathlib import Path
import os
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent
ENV_FILE = PROJECT_ROOT / ".env"
load_dotenv(dotenv_path=ENV_FILE, override=False)

@dataclass
class Config:
    project_root: Path = PROJECT_ROOT
    env_file: Path = ENV_FILE
    api_key_env_var: str = "TWELVE_DATA_API_KEY"
    api_key: str = field(default_factory=lambda: os.getenv("TWELVE_DATA_API_KEY", "").strip())
    base_url: str = "https://api.twelvedata.com"
    endpoint_time_series: str = "/time_series"

    data_dir: Path = PROJECT_ROOT / "data"
    interval: str = "1min"
    outputsize: int = 5000
    response_format: str = "JSON"

    default_days: int = 90
    request_timeout_sec: int = 30
    max_retries: int = 3
    min_sleep_sec: float = 8.0
    max_sleep_sec: float = 15.0
    per_symbol_pause_sec: float = 1.0
    auth_test_symbol: str = "EUR/USD"
    auth_test_outputsize: int = 2

    synthetic_timeframes: tuple = ("5s", "10s", "15s", "30s")

    symbols: dict = field(default_factory=lambda: {
        "forex": ["EUR/USD", "USD/JPY", "GBP/USD", "USD/CHF", "USD/CAD", "EUR/JPY", "GBP/JPY"],
        "indices": ["US500", "USTEC", "US30", "DE40", "UK100"],
        "commodities": ["XTI/USD", "XAU/USD"],
        "crypto": ["BTC/USD", "ETH/USD"],
    })

    def all_symbols(self):
        out = []
        for group in self.symbols.values():
            out.extend(group)
        return out

    def load_environment(self) -> str:
        load_dotenv(dotenv_path=self.env_file, override=False)
        self.api_key = os.getenv(self.api_key_env_var, "").strip()
        return self.api_key

    def expected_venv_python(self) -> Path:
        if os.name == "nt":
            return self.project_root / ".venv" / "Scripts" / "python.exe"
        return self.project_root / ".venv" / "bin" / "python"

CFG = Config()
