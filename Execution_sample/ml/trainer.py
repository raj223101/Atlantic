"""
ml/trainer.py
─────────────
Offline LightGBM training.

    python -m ml.trainer                         # all symbols
    python -m ml.trainer --symbols NIFTY         # one symbol
    python -m ml.trainer --symbols NIFTY --plot  # + importance chart

Artefacts saved to MODEL_DIR:
    {SYMBOL}_model.lgb
    {SYMBOL}_scaler.pkl
    {SYMBOL}_meta.json
    training_report.txt
"""

from __future__ import annotations

import argparse
import json
import os
import pickle
import sys
import time
from datetime import datetime
from typing import List, Optional

import numpy as np

try:
    import lightgbm as lgb
    from sklearn.preprocessing import StandardScaler
    from sklearn.metrics import classification_report, confusion_matrix
    _DEPS_OK = True
except ImportError as e:
    _DEPS_OK = False
    _DEPS_ERR = str(e)

from config import (
    MODEL_DIR, ML_MIN_ROWS, ML_TEST_SIZE,
    ML_LABEL_FORWARD_BARS, ML_LABEL_THRESHOLD,
    LGBM_PARAMS, INSTRUMENTS,
)
from ml.data_pipeline import DataPipeline
from ml.feature_builder import FEATURE_NAMES, N_FEATURES


def _check_deps():
    if not _DEPS_OK:
        print(f"❌ Missing: {_DEPS_ERR}")
        print("   pip install lightgbm scikit-learn")
        sys.exit(1)


class ModelTrainer:

    @staticmethod
    def train_symbol(symbol: str, plot: bool = False) -> Optional[dict]:
        print(f"\n{'='*60}\n  Training: {symbol}\n{'='*60}")

        # ── Load data ─────────────────────────────────────────────────
        df = DataPipeline.load_symbol(symbol)
        if df.empty:
            print("  ❌ No data — skipping")
            return None

        X, y = DataPipeline.to_xy(df)
        valid = y >= 0
        X, y  = X[valid], y[valid]

        print(f"  Total samples : {len(y):,}")
        DataPipeline.describe(df)

        if len(y) < ML_MIN_ROWS:
            print(f"  ❌ Only {len(y)} rows (need {ML_MIN_ROWS}) — skipping")
            return None

        # ── Time-ordered split — NO shuffle ───────────────────────────
        split     = int(len(X) * (1 - ML_TEST_SIZE))
        X_tr, X_te = X[:split], X[split:]
        y_tr, y_te = y[:split], y[split:]
        print(f"  Train: {len(X_tr):,}   Test: {len(X_te):,}")

        # ── Scale ─────────────────────────────────────────────────────
        scaler    = StandardScaler()
        X_tr_s    = scaler.fit_transform(X_tr)
        X_te_s    = scaler.transform(X_te)

        # ── Train ─────────────────────────────────────────────────────
        print("  Training LightGBM...")
        t0    = time.time()
        model = lgb.LGBMClassifier(**LGBM_PARAMS)
        model.fit(
            X_tr_s, y_tr,
            eval_set=[(X_te_s, y_te)],
            eval_metric="multi_logloss",
            callbacks=[
                lgb.early_stopping(50, verbose=False),
                lgb.log_evaluation(100),
            ],
        )
        print(f"  Done in {time.time()-t0:.1f}s  |  "
              f"best_iter={model.best_iteration_}")

        # ── Evaluate ──────────────────────────────────────────────────
        y_pred  = model.predict(X_te_s)
        acc     = float(np.mean(y_pred == y_te))
        report  = classification_report(
            y_te, y_pred,
            target_names=["NEUTRAL","BUY","SELL"],
            zero_division=0,
        )
        cm = confusion_matrix(y_te, y_pred, labels=[0,1,2])

        print(f"\n  Test accuracy : {acc:.4f}")
        print(report)
        print("  Confusion matrix (rows=actual, cols=pred):")
        print(f"  {'':10}  NEU   BUY  SELL")
        for i, row in enumerate(cm):
            print(f"  {'NBS'[i]:1s}{'NEUTRAL BUY SELL'.split()[i]:9s}  "
                  f"{row[0]:5d} {row[1]:5d} {row[2]:5d}")

        # ── Feature importance top 20 ─────────────────────────────────
        imps   = model.feature_importances_
        top_idx = np.argsort(imps)[::-1][:20]
        top20  = [(FEATURE_NAMES[i], int(imps[i])) for i in top_idx]
        print("\n  Top-20 features:")
        max_imp = top20[0][1] if top20 else 1
        for name, imp in top20:
            bar = "█" * int(30 * imp / max_imp)
            print(f"    {name:40s} {imp:6d}  {bar}")

        if plot:
            try:
                import matplotlib.pyplot as plt
                lgb.plot_importance(model, max_num_features=30, figsize=(10,8))
                plt.tight_layout()
                out = os.path.join(MODEL_DIR, f"{symbol}_importance.png")
                plt.savefig(out, dpi=120)
                plt.close()
                print(f"  Saved plot → {out}")
            except Exception as e:
                print(f"  ⚠️  Plot failed: {e}")

        # ── Save ──────────────────────────────────────────────────────
        os.makedirs(MODEL_DIR, exist_ok=True)
        model_path  = os.path.join(MODEL_DIR, f"{symbol}_model.lgb")
        scaler_path = os.path.join(MODEL_DIR, f"{symbol}_scaler.pkl")
        meta_path   = os.path.join(MODEL_DIR, f"{symbol}_meta.json")

        model.booster_.save_model(model_path)
        with open(scaler_path, "wb") as f: pickle.dump(scaler, f)

        meta = {
            "symbol":             symbol,
            "trained_at":         datetime.now().isoformat(),
            "n_features":         N_FEATURES,
            "feature_names":      FEATURE_NAMES,
            "best_iteration":     model.best_iteration_,
            "test_accuracy":      acc,
            "label_forward_bars": ML_LABEL_FORWARD_BARS,
            "label_threshold":    ML_LABEL_THRESHOLD,
            "top20_features":     [n for n,_ in top20],
        }
        with open(meta_path, "w") as f: json.dump(meta, f, indent=2)

        print(f"\n  ✅ model  → {model_path}")
        print(f"     scaler → {scaler_path}")
        print(f"     meta   → {meta_path}")
        return {"symbol": symbol, "accuracy": acc, "report": report}

    @staticmethod
    def train_all(symbols: Optional[List[str]] = None, plot: bool = False):
        _check_deps()
        symbols  = symbols or list(INSTRUMENTS.keys())
        results  = []
        lines    = [f"Training Report — {datetime.now():%Y-%m-%d %H:%M:%S}", "="*60]

        for sym in symbols:
            res = ModelTrainer.train_symbol(sym, plot=plot)
            if res:
                results.append(res)
                lines += [f"\n{sym}  acc={res['accuracy']:.4f}", res["report"]]

        rpt_path = os.path.join(MODEL_DIR, "training_report.txt")
        with open(rpt_path, "w") as f: f.write("\n".join(lines))

        print(f"\n{'='*60}\nSUMMARY")
        for r in results:
            print(f"  {r['symbol']:12s}  accuracy={r['accuracy']:.4f}")
        print(f"Report → {rpt_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", nargs="+", default=None)
    parser.add_argument("--plot", action="store_true")
    args = parser.parse_args()
    ModelTrainer.train_all(symbols=args.symbols, plot=args.plot)
