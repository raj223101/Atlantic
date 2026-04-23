# Atlantic Data Pipeline Runbook

## 1. Rebuild the local virtual environment

The project expects a local interpreter at `.\.venv\Scripts\python.exe`. If `.venv` is missing or broken, rebuild it from the project root:

```powershell
Remove-Item -LiteralPath .\.venv -Recurse -Force
C:\Users\Light\AppData\Local\Programs\Python\Python313\python.exe -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## 2. Configure the Twelve Data key

Create or update the root `.env` file:

```dotenv
TWELVE_DATA_API_KEY=your_rotated_key_here
```

Use a newly rotated key. The previously exposed key should be treated as compromised.

## 3. Use the workspace interpreter in VS Code

- Open the folder `C:\Users\Light\OneDrive\Desktop\atlantic_data download`
- Run `Python: Select Interpreter`
- Choose `.\.venv\Scripts\python.exe`
- Use one of the workspace debug profiles from `.vscode/launch.json`

The project now fails fast if it is launched with the global interpreter instead of the workspace `.venv`.

## 4. Run the startup preflight

This checks:

- workspace interpreter
- `.env` presence
- `TWELVE_DATA_API_KEY` presence
- a small authenticated Twelve Data `/time_series` request for `EUR/USD`

```powershell
.\.venv\Scripts\python.exe .\main.py --preflight-only
```

## 5. Run the downloader

Full refresh:

```powershell
.\.venv\Scripts\python.exe .\main.py --symbols all --days 90 --force-refresh
```

Incremental update:

```powershell
.\.venv\Scripts\python.exe .\main.py --symbols all --days 90
```

Optional features:

```powershell
.\.venv\Scripts\python.exe .\main.py --symbols all --days 90 --add-features
```

## 6. Expected outputs

Per symbol, files are written under `data\<SANITIZED_SYMBOL>\`:

- `1min.csv`
- `5s.csv`
- `10s.csv`
- `15s.csv`
- `30s.csv`

Examples:

- `data\EURUSD\1min.csv`
- `data\BTCUSD\5s.csv`

## 7. Current runtime behavior

- Timestamps are parsed and saved in UTC
- Local `1min.csv` files are sorted ascending and de-duplicated on `datetime`
- Incremental runs fetch only bars newer than the latest saved timestamp
- Synthetic `5s`, `10s`, `15s`, and `30s` files are regenerated from local `1min.csv`
- No API calls are needed in the strategy loop

## 8. Common failures

`Twelve Data authentication failed`

- The key is invalid, missing, or still using the compromised key
- Update `.env` with a valid rotated key and rerun the preflight

`This project must be run with ...\.venv\Scripts\python.exe`

- VS Code or the terminal is using the global interpreter
- Re-select the workspace interpreter and run again

`Expected local virtualenv interpreter was not found`

- `.venv` was not created correctly
- Rebuild `.venv` using step 1
