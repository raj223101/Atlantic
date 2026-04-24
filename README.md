# Atlantic — End-to-End Quant Trading System

Atlantic is a modular, execution-focused quantitative trading system designed to operate across multiple markets with emphasis on **tick-level data, low-latency execution, and realistic PnL after costs**.

The system spans the full lifecycle of trading:
**data → strategy → backtesting → execution → monitoring**

> ⚠️ This repository contains **sample architecture, partial backtesting data, and limited live data**.
> The full production system is significantly larger and not fully open-sourced.

---

## 📖 Project Background

Atlantic originated from hands-on quantitative trading work starting in 2023.

Initial experimentation was done using external platforms (e.g., AlgoTest), which exposed limitations in:

* Execution control
* Latency
* System transparency

This led to building a **fully custom system** focused on execution quality and real-world constraints.

---

## 📏 System Scale

* **250,000+ lines of code** across multiple modules

* Covers:

  * Data pipelines
  * Strategy systems
  * Backtesting engines
  * Execution infrastructure
  * Monitoring systems

* Designed as a **modular distributed architecture**, not a single monolithic system

---

# 🧠 System Overview

Atlantic is divided into 4 core components:

1. Data Collection
2. Strategy Formation & Backtesting
3. Execution
4. Monitoring

---

# 🏗️ Global Architecture

```text
        ┌──────────────┐
        │ Data Layer   │
        └──────┬───────┘
               ↓
        ┌──────────────┐
        │ Strategy     │
        └──────┬───────┘
               ↓
        ┌──────────────┐
        │ Backtesting  │
        └──────┬───────┘
               ↓
        ┌──────────────┐
        │ Execution    │
        └──────┬───────┘
               ↓
        ┌──────────────┐
        │ Monitoring   │
        └──────────────┘
```

---

# 📦 1. Data Collection

## 🧱 Architecture

```text
Historical Sources → Processing → Storage → Backtest Engine
Real-Time Feed → Stream Handler → Execution Engine
```

---

## 🔹 Historical Data (Backtesting Only)

* Initially used NSE tick dataset (~52 days limitation)

* Migrated to **Dukascopy Hybrid Tick Pipeline** for:

  * Broader coverage
  * Multi-market compatibility
  * Better consistency

* Designed for:

  * Tick-level storage
  * Data normalization
  * Backtesting support

---

## 🔹 Real-Time Data (Execution Independent)

* Dedicated pipeline for:

  * Live trading
  * Spread analysis
  * Real-time signal evaluation

* Supports:

  * Indian F&O
  * Crypto
  * Forex

---

## ⚠️ Critical Design: Data Separation

Backtesting and execution use **completely independent data pipelines**.

### Why:

* Prevents data leakage
* Ensures realistic execution
* Improves system reliability

> Backtesting validates ideas. Execution validates reality.

---

# 📊 2. Strategy Formation & Backtesting

## 🧱 Architecture

```text
Historical Data → Feature Processing → Strategy Logic → Backtest Engine → Reports
```

---

## 🔹 Strategy Development

* **200+ strategies tested** across:

  * Multiple timeframes
  * Market segments
  * Volatility regimes

* Focus:

  * Microstructure patterns
  * Execution-aware strategies

---

## 🔹 Testing Framework

* Tick-level backtesting engine
* Includes:

  * Slippage modeling
  * Transaction cost modeling
  * Trade-level analytics

### Advanced Testing:

* Stress testing
* Risk testing
* Crash scenario simulation

---

# ⚙️ 3. Execution System

## 🧱 Architecture

```text
Real-Time Data → Signal Trigger → Execution Engine → Order Manager → Exchange
```

---

## 🔹 Core Features

* **Low-latency execution**

  * <10 ms market orders
  * <100 ms limit orders

* **Ladder-Based Limit Order Execution**

  * L1 → L5 price levels
  * Progressive aggression
  * Tick-driven updates

* Designed for:

  * Slippage minimization
  * Fast reaction to market changes

---

## 🌍 Distributed Infrastructure

```text
Mumbai ↔ London ↔ New York
        ↓
   Execution Nodes
```

* Linux-based cloud servers (SSH access)
* Used for:

  * Latency benchmarking
  * Region-specific execution testing
  * Reliability improvement

---

## ⚠️ Key Principle

Execution system is **fully independent**:

* Uses its own real-time data
* No dependency on backtesting pipeline

---

# 📈 4. Monitoring System

## 🧱 Architecture

```text
Execution Systems → Data Aggregation → Monitoring Engine → Alerts / Dashboard
```

---

## 🔹 Capabilities

* Real-time PnL tracking
* Strategy-wise monitoring
* Cross-region system tracking
* Alerting system:

  * Execution failures
  * Abnormal performance
  * Risk breaches

---

# ⚙️ Design Principles

* Execution > Signal
* Realistic PnL after costs
* Tick-level decision making
* Modular architecture
* Independent system components

---

# 📁 Repository Scope

This GitHub repository contains:

* Sample architecture
* Partial backtesting data
* Limited live data examples
* Structural code for understanding system design

❌ Does NOT include:

* Full production codebase
* Complete datasets
* Proprietary execution logic

---

# 🔧 Tech Stack

* Python
* Pandas / NumPy
* Linux (cloud deployment via SSH)
* Broker & Exchange APIs
* Event-driven architecture

---

# 🚀 Key Highlights

* 200+ strategies tested
* Tick-level processing (~2–3 ticks/sec)
* Multi-market support
* Distributed global infrastructure
* Execution-first system design

---

# 👤 Author

Raj Yadav
Quant Trading Systems | Execution-Focused Research | Market Microstructure

GitHub: https://github.com/raj223101/Atlantic

---

# 💡 Final Thought

Most trading systems focus on predicting price.

Atlantic focuses on:
**how trades are executed, how risk is managed, and what remains after costs.**
