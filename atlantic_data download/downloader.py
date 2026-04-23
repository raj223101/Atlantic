import random
import time

import pandas as pd
import requests

from config import CFG
from processor import json_to_df
from utils import symbol_dir


class TwelveDataConfigurationError(RuntimeError):
    pass


class TwelveDataAuthError(RuntimeError):
    pass


class TwelveDataAPIError(RuntimeError):
    pass


class TwelveDataDownloader:
    def __init__(self, logger):
        CFG.load_environment()
        if not CFG.api_key:
            raise TwelveDataConfigurationError(
                f"{CFG.api_key_env_var} is missing. Add it to {CFG.env_file} before running the pipeline."
            )
        self.logger = logger
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "atlantic-data-pipeline/1.0"})

    @staticmethod
    def _extract_api_error(payload: dict | None) -> tuple[str, str]:
        if isinstance(payload, dict) and payload.get("status") == "error":
            return str(payload.get("code", "")).strip(), str(payload.get("message", "Unknown API error")).strip()
        return "", ""

    @staticmethod
    def _is_auth_error(status_code: int, code: str, message: str) -> bool:
        message_lower = message.lower()
        return (
            status_code == 401
            or code == "401"
            or "apikey" in message_lower
            or "api key" in message_lower
            or "incorrect or not specified" in message_lower
        )

    def verify_api_access(self, symbol: str | None = None):
        test_symbol = symbol or CFG.auth_test_symbol
        self.logger.info(f"Running Twelve Data auth preflight for {test_symbol}")
        payload = self._request_with_retry(
            {
                "symbol": test_symbol,
                "interval": CFG.interval,
                "outputsize": CFG.auth_test_outputsize,
                "format": CFG.response_format,
                "apikey": CFG.api_key,
                "order": "DESC",
            }
        )
        if not payload or "values" not in payload or not payload["values"]:
            raise TwelveDataAPIError(
                f"Twelve Data preflight returned no values for {test_symbol}. Check network access and symbol support."
            )
        self.logger.info("Twelve Data auth preflight passed.")

    def _request_with_retry(self, params: dict):
        url = f"{CFG.base_url}{CFG.endpoint_time_series}"
        for attempt in range(1, CFG.max_retries + 1):
            try:
                r = self.session.get(url, params=params, timeout=CFG.request_timeout_sec)
                try:
                    payload = r.json()
                except ValueError:
                    payload = {}

                code, msg = self._extract_api_error(payload)
                if self._is_auth_error(r.status_code, code, msg):
                    raise TwelveDataAuthError(
                        f"Twelve Data authentication failed: {msg or 'invalid API key'}. "
                        f"Update {CFG.env_file} with a valid rotated key and rerun from {CFG.expected_venv_python()}."
                    )

                if r.status_code == 429:
                    sleep_t = random.uniform(CFG.min_sleep_sec, CFG.max_sleep_sec)
                    self.logger.warning(f"Rate limited (429). Sleeping {sleep_t:.1f}s...")
                    time.sleep(sleep_t)
                    continue

                r.raise_for_status()

                if code or msg:
                    self.logger.warning(f"API error [{code}]: {msg}")
                    if "rate limit" in msg.lower():
                        sleep_t = random.uniform(CFG.min_sleep_sec, CFG.max_sleep_sec)
                        self.logger.warning(f"Rate limit message. Sleeping {sleep_t:.1f}s...")
                        time.sleep(sleep_t)
                        continue
                    if attempt == CFG.max_retries:
                        return None
                    time.sleep(1.5 * attempt)
                    continue
                return payload

            except requests.RequestException as e:
                self.logger.error(f"HTTP error attempt {attempt}/{CFG.max_retries}: {e}")
                if attempt == CFG.max_retries:
                    return None
                time.sleep(1.5 * attempt)
        return None

    def _read_existing_1m(self, symbol: str) -> pd.DataFrame:
        fp = symbol_dir(CFG.data_dir, symbol) / "1min.csv"
        if not fp.exists():
            return pd.DataFrame(columns=["datetime", "open", "high", "low", "close", "volume"])
        df = pd.read_csv(fp)
        if df.empty:
            return df
        df["datetime"] = pd.to_datetime(df["datetime"], utc=True, errors="coerce")
        for c in ["open", "high", "low", "close", "volume"]:
            df[c] = pd.to_numeric(df[c], errors="coerce")
        return (
            df.dropna(subset=["datetime"])
            .sort_values("datetime")
            .drop_duplicates(subset=["datetime"], keep="last")
            .reset_index(drop=True)
        )

    def _write_1m(self, symbol: str, df: pd.DataFrame):
        sp = symbol_dir(CFG.data_dir, symbol)
        fp = sp / "1min.csv"
        df = df.sort_values("datetime").drop_duplicates(subset=["datetime"], keep="last")
        df.to_csv(fp, index=False)

    def download_symbol(self, symbol: str, days: int = 90, force_refresh: bool = False):
        self.logger.info(f"Downloading {symbol}...")
        existing = pd.DataFrame() if force_refresh else self._read_existing_1m(symbol)

        now_utc = pd.Timestamp.now(tz="UTC").floor("min")
        start_target = (now_utc - pd.Timedelta(days=days)).floor("min")

        if not existing.empty:
            last_ts = existing["datetime"].max()
            if pd.notna(last_ts):
                start_target = max(start_target, last_ts + pd.Timedelta(minutes=1))
                self.logger.info(f"{symbol} incremental from {start_target}")

        if start_target >= now_utc:
            self.logger.info(f"{symbol} already up to date.")
            return existing

        all_new = []
        end_date = now_utc

        while end_date > start_target:
            params = {
                "symbol": symbol,
                "interval": CFG.interval,
                "outputsize": CFG.outputsize,
                "format": CFG.response_format,
                "apikey": CFG.api_key,
                "end_date": end_date.strftime("%Y-%m-%d %H:%M:%S"),
                "order": "DESC",
            }

            self.logger.info(f"API call {symbol} end_date={params['end_date']}")
            payload = self._request_with_retry(params)
            if not payload or "values" not in payload:
                self.logger.warning(f"No data returned for {symbol}. Breaking loop.")
                break

            chunk = json_to_df(payload["values"])
            if chunk.empty:
                break

            chunk = chunk[chunk["datetime"] >= start_target]
            if chunk.empty:
                break

            all_new.append(chunk)
            oldest = chunk["datetime"].min()
            end_date = oldest - pd.Timedelta(minutes=1)

            time.sleep(CFG.per_symbol_pause_sec)

        new_df = pd.concat(all_new, ignore_index=True) if all_new else pd.DataFrame(
            columns=["datetime", "open", "high", "low", "close", "volume"]
        )

        merged = pd.concat([existing, new_df], ignore_index=True) if not existing.empty else new_df
        merged = merged.sort_values("datetime").drop_duplicates(subset=["datetime"], keep="last").reset_index(drop=True)

        self._write_1m(symbol, merged)
        self.logger.info(f"{symbol} saved rows={len(merged)}")
        return merged
