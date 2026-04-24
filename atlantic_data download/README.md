# Dukascopy Hybrid Tick Pipeline

Hybrid Node.js + Python pipeline for downloading Dukascopy tick data with `dukascopy-node`, cleaning it, and producing continuous candle datasets for backtesting.

## Included files

- `download.js`: downloads daily raw tick CSV files with retries, caching, skip-existing logic, and per-run logs
- `process.py`: turns raw CSVs into 1s/5s/10s/15s/30s/1min datasets
- `resampler.py`: chunked tick cleaning and resampling logic
- `utils.py`: loading, alignment, fast lookup, and execution simulation helpers
- `config/instruments.json`: shared symbol-to-Dukascopy instrument mapping

## Storage layout

```text
data/
  raw/
    EURUSD/
      2026-01-01.csv
      2026-01-02.csv
  processed/
    EURUSD/
      1s.csv
      5s.csv
      10s.csv
      15s.csv
      30s.csv
      1min.csv
      manifest.json
logs/
  downloads/
  processing/
```

## Install

```bash
npm install
python -m pip install -r requirements.txt
```

If `node` or `npm` are not available on PATH in PowerShell, use the local portable setup instead:

```powershell
.\setup-node-local.ps1
.\npm-local.ps1 install
```

Windows CMD/PowerShell-friendly wrappers that avoid PowerShell script policy issues:

```cmd
setup-node-local.cmd
npm-local.cmd install
```

## Download raw tick data

```bash
node download.js --symbols all --from 2026-01-01 --to 2026-03-31
```

Portable PowerShell equivalent:

```powershell
.\node-local.ps1 .\download.js --symbols all --from 2026-01-01 --to 2026-03-31
```

Portable CMD equivalent:

```cmd
node-local.cmd download.js --symbols all --from 2026-01-01 --to 2026-03-31
```

```bash
node download.js --symbols forex,crypto
node download.js --symbols EURUSD,US30,XAUUSD
node download.js --symbols all --lookback-days 90
node download.js --symbols all --from 2026-01-01 --to 2026-03-31 --batch-size 2 --batch-pause 3000 --retries 12
```

## Process into multi-timeframe candles

```bash
python process.py --symbols all --output-format both
```

```bash
python process.py --symbols EURUSD,US30 --start 2026-01-01 --end 2026-03-31
python process.py --symbols all --continuous --chunk-size 500000 --output-format parquet
```

## Output schema

Processed candles are saved in UTC with `timestamp` as Unix epoch milliseconds and include:

- `open`, `high`, `low`, `close`
- `bid_open`, `bid_high`, `bid_low`, `bid_close`
- `ask_open`, `ask_high`, `ask_low`, `ask_close`
- `spread_open`, `spread_high`, `spread_low`, `spread_close`, `spread_mean`
- `volume`
- `bid_volume`, `ask_volume`
- `tick_count`
- `synthetic_seconds`

`volume` is the average of summed bid/ask volume inside each bar. `synthetic_seconds` marks forward-filled 1-second bars created to keep the 1-second timeline continuous.

## Strategy helpers

```python
from utils import (
    ExecutionConfig,
    align_multi_timeframe,
    load_multi_timeframe,
    simulate_execution,
)

frames = load_multi_timeframe("data/processed", "EURUSD", ["1s", "1min"])
aligned = align_multi_timeframe(frames, base_timeframe="1s")

execution = simulate_execution(
    frame=frames["1s"],
    side="buy",
    signal_timestamp="2026-01-15T09:15:00Z",
    quantity=10000,
    config=ExecutionConfig(delay_ms_min=100, delay_ms_max=500),
)

print(execution.to_dict())
```

## Notes

- `US30`, `US500`, `USTEC`, `DE40`, `UK100`, and `XTIUSD` are user-facing aliases mapped to Dukascopy instrument ids in `config/instruments.json`.
- `XTIUSD` is mapped to Dukascopy's `lightcmdusd` feed.
- `setup-node-local.ps1` downloads the official Node.js v24.15.0 Windows x64 zip and extracts it with `tar.exe`, which preserves the bundled npm layout more reliably than `Expand-Archive` for this package.
- `node-local.ps1` and `npm-local.ps1` let you run the Node side from this repo without changing your global PATH.
- `setup-node-local.cmd`, `node-local.cmd`, and `npm-local.cmd` are the easiest entry points on machines where PowerShell script execution is disabled.
- For very large tick ranges, keep daily raw files, lower `--batch-size`, and raise `--batch-pause` to reduce rate-limit pressure.
- Parquet output requires `pyarrow`.
