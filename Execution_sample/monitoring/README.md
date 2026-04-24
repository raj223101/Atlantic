# Performance Monitoring And Observability

This package adds a non-intrusive observability layer for the trading engine.
It is designed to observe runtime behavior without changing strategy logic,
calculation rules, execution decisions, or market-data semantics.

## Architecture

The monitoring stack is split into:

- `performance_monitor.py`
  Orchestrator and public hook API
- `collector.py`
  Rolling metric collection and aggregation
- `analyzer.py`
  Health analysis, recommendations, and instability detection
- `alerts.py`
  Threshold alerting with cooldown protection
- `dashboard.py`
  Console dashboard rendering
- `storage.py`
  Async snapshot and alert persistence
- `log_parser.py`
  Zero-touch fallback log tail parser
- `wrappers.py`
  Lightweight decorator and context-manager helpers

## Integration Modes

### 1. Event Hook Mode

Preferred mode. Runtime components call lightweight hooks such as:

```python
from monitoring.performance_monitor import performance_monitor

performance_monitor.on_tick_received(...)
performance_monitor.on_stage("calculation_engine", elapsed_ms)
performance_monitor.on_signal(...)
performance_monitor.on_order(...)
performance_monitor.on_api_call(...)
```

This mode is now wired into:

- tick intake and queue processing
- stage timing from `main.py`
- signal routing
- paper execution lifecycle
- broker quote and greeks API calls
- feed heartbeat loop

### 2. Log Parsing Mode

Enable in config:

```python
MONITORING_LOG_PARSER_MODE = True
```

The monitor will tail `logs/engine.log` and parse:

- `[TickQueue]`
- `[SignalRouter]`
- `[PaperBroker]`

This mode is intended as a zero-touch fallback when event hooks are not available.

### 3. Wrapper Mode

Use the wrapper helpers when timing a boundary function without editing business logic:

```python
from monitoring.wrappers import monitor_stage, observe_stage
from monitoring.performance_monitor import performance_monitor

@monitor_stage(performance_monitor, "api_call")
def fetch_data():
    ...

with observe_stage(performance_monitor, "custom_stage"):
    do_work()
```

## Stored Outputs

Monitoring data is written under `data/monitoring`:

- `snapshots.jsonl`
- `alerts.jsonl`
- `dashboard_metrics.csv`

## Dashboard Example

```text
SYSTEM HEALTH DASHBOARD

Tick Rate:          124.6 ticks/sec
Tick Delay:         18.4 ms avg
Queue Size:         7
Queue Wait:         4.6 ms avg
Avg Latency:        39.8 ms
P95 Latency:        92.3 ms
P99 Latency:        151.4 ms
API Success:        98.7%
Signal Fill Rate:   84.2%
CPU Usage:          21.7%
Memory:             312.4 MB

STATUS: STABLE
```

## Config Knobs

All main thresholds are configurable in `config.py`:

- `MONITORING_LATENCY_LIMIT_MS`
- `MONITORING_QUEUE_LIMIT`
- `MONITORING_API_FAILURE_LIMIT_PCT`
- `MONITORING_TICK_DELAY_LIMIT_MS`
- `MONITORING_NO_FILL_SIGNAL_LIMIT`
- `MONITORING_CPU_WARN_PCT`
- `MONITORING_MEMORY_WARN_MB`

## Design Notes

- Event ingestion is async and non-blocking
- Monitoring writes are async and decoupled from the trading path
- Only aggregated metrics and threshold alerts are logged
- The system can suggest safe mode, but it does not block trading by itself
- The implementation is intentionally separate from strategy logic
