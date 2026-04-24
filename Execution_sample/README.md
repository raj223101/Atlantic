# Trading Framework Architecture

This project is organized as a modular trading framework with separate layers for calculation, strategy evaluation, execution, risk, runtime orchestration, and storage.

## Architecture

- `calculation/`
  Neutral calculation layer for reusable `X_C_*` and `RTC_*` components.
- `strategy/`
  Strategy lifecycle, signal contracts, and generic strategy shell.
- `execution/`
  Signal routing, runtime strategy evaluation, and execution adapters.
- `risk/`
  Entry validation, position sizing, and stop-loss planning.
- `runtime/`
  Low-latency event loop, queueing, dispatch, and runtime coordination.
- `candle_engine/`
  Multi-timeframe candle construction from live ticks.
- `storage/`
  File persistence for candles, trades, and monitoring artifacts.
- `core/`
  Shared state, logging, maintenance helpers, and API context.
- `monitoring/`
  Metrics collection, dashboards, health monitoring, and alerts.

## Framework Flow

```text
Feed -> Candle Engine -> Calculation Layer -> Strategy Evaluation -> Execution Layer -> Storage/Monitoring
```

More concretely:

```text
Tick Feed
  -> CandleBuilder
  -> calculation/x_c_rtc_engine.py
  -> execution/multi_strategy_engine.py
  -> execution/signal_router.py
  -> execution/paper_broker.py or other adapter
  -> monitoring/ and storage/
```

## Core Interfaces

The generic strategy framework remains available under `strategy/` and includes:

- `initialize()`
- `generate_signal(data)`
- `validate_entry(signal)`
- `validate_exit(position, data)`

The signal layer is kept generic through placeholders like:

- `X_C_1`
- `X_C_2`
- `X_C_3`
- `X_C_4`
- `E_C`

The scoring model is still represented as:

```text
P(win) = 1 / (1 + exp(-Score))
```

## Ladder System

The execution layer also supports a ladder-based order model built around `BOOK_LADDER`.

In this model, the strategy does not jump directly from signal to a single order price. Instead, execution progresses through a staged price ladder:

```text
PASSIVE -> CONTROLLED -> LADDER -> FORCED
```

- `PASSIVE`, `CONTROLLED`, and `LADDER` are limit-order phases used to discover price with minimal spread impact.
- `FORCED` is the terminal fast path that can escalate to a market order when the time budget is exhausted.
- the ladder is primed during runtime startup so execution has book context ready before signal handling
- the ladder system is isolated inside the execution layer, so strategy logic stays reusable and independent from order-routing details

Relevant files:

- [execution/runtime_bootstrap.py](/C:/Users/Light/OneDrive/Desktop/Execution_sample/execution/runtime_bootstrap.py)
- [execution/angel_option_service.py](/C:/Users/Light/OneDrive/Desktop/Execution_sample/execution/angel_option_service.py)
- [execution/option_execution_engine.py](/C:/Users/Light/OneDrive/Desktop/Execution_sample/execution/option_execution_engine.py)

## Execution Speed Frame

This framework is documented around a low-latency execution envelope rather than a single hardcoded rule set.

- complete signal-to-execution flow is described as an ultra-low-latency operating frame under healthy runtime conditions
- entry and exit timing are controlled by the active execution profile rather than fixed values in this document
- repricing cadence and order polling are intentionally abstracted at the documentation level

For ladder execution, the intended behavior is:

- limit-order discovery happens first through the staged ladder
- if the limit path does not complete inside its budget, the engine escalates to the terminal market-order phase
- the architecture keeps a dedicated fast-path market-order escalation window inside the execution profile

In the current `TYPE_C` ladder profile, the timing model is:

- passive discovery
- controlled price improvement
- ladder escalation
- forced terminal execution

That keeps the `TYPE_C` path inside a compact low-latency envelope while preserving a dedicated terminal market-order window.

## TYPE_C Label

`TYPE_C` is the `HYBRID_ADAPTIVE` execution label.

Its purpose is to balance fill quality and speed:

- it starts with price discovery through limit-order ladder phases
- it becomes more aggressive only when the book shows directional pressure
- it uses ladder depth without binding the strategy framework to any market-specific signal formula

At a high level, `TYPE_C` behaves like a microstructure-aware execution profile:

- it uses a bounded ladder depth from the active execution profile
- it reads book pressure before deciding whether to stay passive or move closer to the offer/bid
- it keeps the strategy layer generic and pushes all price-placement behavior into the execution layer

## Micropricing

`TYPE_C` relies on micropricing to estimate fair short-horizon pressure inside the spread.

The microprice is computed from the best bid, best ask, and their available sizes:

```text
microprice = ((ask * bid_size) + (bid * ask_size)) / (bid_size + ask_size)
```

This gives more weight to the side with less resting size and helps the engine understand whether pressure is leaning toward the bid or ask.

Within the execution framework, micropricing is used to:

- bias early ladder prices toward the stronger side of the book
- detect bullish or bearish pressure together with order-book imbalance
- improve the `TYPE_C` transition between passive, controlled, and forced execution phases

If full bid/ask data is not available, the engine falls back to simpler price references such as midpoint or last traded price.

## Maintenance Mode

This repository now includes a transparent maintenance mode controlled by `MAINTENANCE_MODE` in [config.py](/C:/Users/Light/OneDrive/Desktop/Execution_sample/config.py).

When maintenance mode is enabled:

- calculation outputs return a maintenance payload instead of live values
- signal generation is suppressed transparently
- candle persistence output is skipped
- visible output is reduced to the admin contact message

Current maintenance contact:

```text
Contact admin Raj: rajydv141@gmail.com
```

This behavior is explicit and centralized through [core/maintenance.py](/C:/Users/Light/OneDrive/Desktop/Execution_sample/core/maintenance.py).

## Important Files

- [config.py](/C:/Users/Light/OneDrive/Desktop/Execution_sample/config.py)
- [core/maintenance.py](/C:/Users/Light/OneDrive/Desktop/Execution_sample/core/maintenance.py)
- [calculation/x_c_rtc_engine.py](/C:/Users/Light/OneDrive/Desktop/Execution_sample/calculation/x_c_rtc_engine.py)
- [calculation/x_c_rtc_manager.py](/C:/Users/Light/OneDrive/Desktop/Execution_sample/calculation/x_c_rtc_manager.py)
- [execution/multi_strategy_engine.py](/C:/Users/Light/OneDrive/Desktop/Execution_sample/execution/multi_strategy_engine.py)
- [execution/signal_router.py](/C:/Users/Light/OneDrive/Desktop/Execution_sample/execution/signal_router.py)
- [runtime/engine.py](/C:/Users/Light/OneDrive/Desktop/Execution_sample/runtime/engine.py)

The overall design stays modular, so calculation logic, execution adapters, and risk policies can still be swapped independently when maintenance mode is turned off.
