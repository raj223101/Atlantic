# Low-Latency Runtime

This package adds a separate event-driven runtime around the existing candle, calculation, strategy, and execution modules.

## Architecture

`AngelFeed -> LowLatencyTradingEngine.enqueue() -> bounded ingress queue -> candle/calculation worker -> strategy workers (grouped by primary timeframe) -> execution worker`

The existing strategy logic, calculation formulas, and execution decisions are not rewritten. The low-latency runtime only changes how data flows through those components.

## Key properties

- Event-driven pipeline
- Bounded drop-oldest queues
- Separate execution worker
- Stale-signal rejection
- Queue-pressure detection
- Monitoring hooks for each stage
- Replay benchmark support

## Runtime knobs

Configured from `config.py`:

- `LOW_LATENCY_CANDLE_WORKERS`
- `LOW_LATENCY_TICK_QUEUE_LIMIT`
- `LOW_LATENCY_STRATEGY_QUEUE_LIMIT`
- `LOW_LATENCY_EXECUTION_QUEUE_LIMIT`
- `LOW_LATENCY_DISPATCH_PRICE_THRESHOLD`
- `LOW_LATENCY_SIGNAL_MAX_AGE_MS`
- `LOW_LATENCY_HARD_LATENCY_LIMIT_MS`
- `LOW_LATENCY_SIGNAL_PRICE_DRIFT_LIMIT`
- `LOW_LATENCY_QUEUE_WARNING_RATIO`
- `LOW_LATENCY_LOAD_SHED_COOLDOWN_S`

## Example config

```json
{
  "strategies_per_tf": 3,
  "timeframes": 3,
  "segments": 1,
  "latency_limit_ms": 250,
  "queue_limit": 1000
}
```

## Replay benchmark

```powershell
& 'C:\Users\Light\AppData\Local\Programs\Python\Python313\python.exe' `
  -m runtime.benchmark `
  --csv data\NIFTY_ticks.csv `
  --symbol NIFTY
```

The benchmark writes a JSON summary to `LOW_LATENCY_BENCHMARK_OUTPUT`.
