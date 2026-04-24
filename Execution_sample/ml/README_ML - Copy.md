# ML Layer — LightGBM Signal Filter

## What was built

A complete, production-ready ML pipeline layered on top of your existing rule-based engine.

```
tick → Candle Engine → Indicator Engine → Feature Builder
                                                ↓
                                        LightGBM Model
                                                ↓
                              Rule Signal + ML Confirmation
                                                ↓
                                       Execution Engine
```

---

## Files delivered

| File | Purpose |
|------|---------|
| `config.py` | Updated — adds generic calculation grids plus `LGBM_PARAMS` and `ML_*` settings |
| `state_memory.py` | Updated — stores multi-length HMA/TEMA (9, 16, 21) and 3 UT param sets |
| `calculation/x_c_rtc_manager.py` | Updated — computes all multi-length variants |
| `candle_saver.py` | Updated — saves full expanded feature set to CSV |
| `signal_engine.py` | Updated — adds `check_entry_with_ml()` |
| `trade_manager.py` | Updated — passes per-candle stats to ML predictor |
| `main.py` | Updated — loads ML models at startup |
| `ml/__init__.py` | Package marker |
| `ml/feature_builder.py` | Converts calculation dicts → flat feature vector (~180 features) |
| `ml/label_generator.py` | Forward-looking 3-class labels (BUY / SELL / NEUTRAL) |
| `ml/data_pipeline.py` | Loads CSVs, merges 1m/2m/5m, builds training DataFrame |
| `ml/trainer.py` | Offline training script with evaluation + feature importance |
| `ml/predictor.py` | Live inference engine with thread-safe model loading |

---

## Step 1 — Collect training data

Run your system live (or paper) for **at least 5–10 trading sessions**.
Data accumulates automatically in `data/SYMBOL_Xm.csv`.

A typical day yields ~375 rows per symbol per timeframe.
You need **≥ 500 rows on the 2m file** before training.

---

## Step 2 — Train models

```bash
# Train all symbols
python -m ml.trainer

# Train a subset
python -m ml.trainer --symbols NIFTY BANKNIFTY

# Train + save feature importance plots
python -m ml.trainer --symbols NIFTY --plot
```

Saved to `models/`:
```
models/
  NIFTY_model.lgb        ← LightGBM booster
  NIFTY_scaler.pkl       ← StandardScaler
  NIFTY_meta.json        ← feature names, accuracy, thresholds
  training_report.txt    ← full classification report
```

---

## Step 3 — Enable ML in live trading

In `config.py`:
```python
ML_USE_MODEL = True    # Enable ML filter
ML_MIN_BUY_PROB  = 0.45   # Tune aggressiveness
ML_MIN_SELL_PROB = 0.45
```

The system loads models at startup (`main.py`). If no model file exists for
a symbol, it falls back to rule-only signals automatically.

---

## Feature schema (~180 features)

Per timeframe (5m / 2m / 1m), 6 feature groups:

| Group | Features per TF |
|-------|----------------|
| ADX | adx, s_adx, adx_max, adx_min, s_adx_max, s_adx_min |
| DI+ | di_plus, s_di_plus + max/min variants |
| DI- | di_minus, s_di_minus + max/min variants |
| HMA × 3 lengths (9, 16, 21) | hma_L, hma_L_bb + max/min |
| TEMA × 3 lengths (9, 16, 21) | tema_L, tema_L_bb + max/min |
| UT × 3 param sets | ut_N, ut_N_bb + max/min |
| CVD | cvd_bb, cvd_lr |

**Total: ~60 features × 3 TFs = ~180 features**

---

## Label scheme

Labels are generated on **2m candle closes**:

| Class | Condition | Meaning |
|-------|-----------|---------|
| 0 | \|return\| < 0.15% | NEUTRAL |
| 1 | return > +0.15% | BUY |
| 2 | return < −0.15% | SELL |

`return` = (close[+5 bars] − close[now]) / close[now]

Tune via `config.py`:
```python
ML_LABEL_FORWARD_BARS = 5      # horizon
ML_LABEL_THRESHOLD    = 0.0015 # ±0.15%
```

---

## ML decision logic

```
Rule triggers BUY
      ↓
ML predicts BUY with p ≥ 0.45
      ↓
Trade placed ✅

Rule triggers BUY
      ↓
ML predicts SELL
      ↓
Trade BLOCKED ❌
```

If ML says NEUTRAL, the rule signal passes through unchanged.

---

## Tuning guide

| Parameter | Effect |
|-----------|--------|
| `ML_MIN_BUY_PROB` ↑ | Fewer trades, higher quality |
| `ML_LABEL_FORWARD_BARS` ↑ | Longer-horizon prediction |
| `ML_LABEL_THRESHOLD` ↑ | Fewer BUY/SELL labels, more NEUTRAL |
| `LGBM_PARAMS["n_estimators"]` ↑ | More trees (slower, potentially better) |
| `LGBM_PARAMS["learning_rate"]` ↓ | Slower learning, needs more trees |

---

## Debugging live predictions

```python
from ml.predictor import MLPredictor
MLPredictor.load_models()
MLPredictor.explain("NIFTY", data_1m, data_2m, data_5m, stats_1m, stats_2m, stats_5m)
```

Prints the top 15 features driving the prediction for that tick.

---

## Install dependencies

```bash
pip install lightgbm scikit-learn --break-system-packages
```
