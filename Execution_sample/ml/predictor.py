"""
Live ML inference - thread-safe and lazy-loaded.

The predictor consumes the configured exit, entry, and HTF snapshots
and leaves the classifier logic unchanged.
"""

from __future__ import annotations

import json
import os
import pickle
import threading
import warnings
from typing import Dict, Optional, Tuple

import numpy as np

from config import MODEL_DIR, ML_MIN_BUY_PROB, ML_MIN_SELL_PROB, ML_USE_MODEL
from ml.feature_builder import FEATURE_NAMES, FeatureBuilder

warnings.filterwarnings("ignore")

try:
    import lightgbm as lgb

    _LGBM_OK = True
except ImportError:
    _LGBM_OK = False

_CLASS = {0: "NEUTRAL", 1: "BUY", 2: "SELL"}


class _Bundle:
    __slots__ = ("booster", "scaler", "meta")

    def __init__(self, booster, scaler, meta):
        self.booster = booster
        self.scaler = scaler
        self.meta = meta


class MLPredictor:

    _models: Dict[str, _Bundle] = {}
    _lock = threading.Lock()
    _loaded = False

    @classmethod
    def load_models(cls, symbols: Optional[list] = None):
        if not _LGBM_OK:
            print("lightgbm not installed - ML disabled")
            return

        with cls._lock:
            if cls._loaded and symbols is None:
                return

            discovered = symbols or (
                [
                    filename.replace("_model.lgb", "")
                    for filename in os.listdir(MODEL_DIR)
                    if filename.endswith("_model.lgb")
                ]
                if os.path.isdir(MODEL_DIR) else []
            )

            for symbol in discovered:
                model_path = os.path.join(MODEL_DIR, f"{symbol}_model.lgb")
                scaler_path = os.path.join(MODEL_DIR, f"{symbol}_scaler.pkl")
                meta_path = os.path.join(MODEL_DIR, f"{symbol}_meta.json")

                if not os.path.exists(model_path):
                    continue

                try:
                    booster = lgb.Booster(model_file=model_path)
                    with open(scaler_path, "rb") as handle:
                        scaler = pickle.load(handle)
                    with open(meta_path) as handle:
                        meta = json.load(handle)
                    cls._models[symbol] = _Bundle(booster, scaler, meta)
                    print(
                        f"  ML model: {symbol} "
                        f"(acc={meta.get('test_accuracy', 0):.3f} "
                        f"features={meta.get('n_features', 0)})"
                    )
                except Exception as exc:
                    print(f"  Load failed {symbol}: {exc}")

            cls._loaded = True

    @classmethod
    def predict(
        cls,
        symbol: str,
        ind_exit: Dict,
        ind_entry: Dict,
        ind_htf: Dict,
        stats_exit: Dict,
        stats_entry: Dict,
        stats_htf: Dict,
    ) -> Tuple[str, Dict[str, float]]:
        if not ML_USE_MODEL:
            return "NEUTRAL", {}

        if not cls._loaded:
            cls.load_models()

        bundle = cls._models.get(symbol)
        if bundle is None:
            return "NO_MODEL", {}

        try:
            fv, _ = FeatureBuilder.from_live(
                ind_exit,
                ind_entry,
                ind_htf,
                stats_exit,
                stats_entry,
                stats_htf,
            )
            fv_scaled = bundle.scaler.transform(fv.reshape(1, -1))
            raw = bundle.booster.predict(fv_scaled)[0]
        except Exception as exc:
            print(f"ML predict error ({symbol}): {exc}")
            return "NEUTRAL", {}

        p0, p1, p2 = float(raw[0]), float(raw[1]), float(raw[2])
        probs = {"NEUTRAL": p0, "BUY": p1, "SELL": p2}

        if p1 >= ML_MIN_BUY_PROB and p1 >= p2:
            return "BUY", probs
        if p2 >= ML_MIN_SELL_PROB and p2 > p1:
            return "SELL", probs
        return "NEUTRAL", probs

    @classmethod
    def is_available(cls, symbol: str) -> bool:
        if not cls._loaded:
            cls.load_models()
        return symbol in cls._models

    @classmethod
    def explain(
        cls,
        symbol: str,
        ind_exit: Dict,
        ind_entry: Dict,
        ind_htf: Dict,
        stats_exit: Dict,
        stats_entry: Dict,
        stats_htf: Dict,
    ):
        if not cls.is_available(symbol):
            print(f"No model for {symbol}")
            return

        bundle = cls._models[symbol]
        fv, names = FeatureBuilder.from_live(
            ind_exit,
            ind_entry,
            ind_htf,
            stats_exit,
            stats_entry,
            stats_htf,
        )
        fv_scaled = bundle.scaler.transform(fv.reshape(1, -1))
        probs = bundle.booster.predict(fv_scaled)[0]
        importances = bundle.booster.feature_importance(importance_type="gain")
        top = np.argsort(importances)[::-1][:15]

        print(f"\n{'-' * 55}")
        print(
            f"  {symbol} | {_CLASS[int(np.argmax(probs))]} | "
            f"N={probs[0]:.3f} B={probs[1]:.3f} S={probs[2]:.3f}"
        )
        for idx in top:
            if idx < len(names):
                print(
                    f"    {names[idx]:42s} "
                    f"val={fv[idx]:8.4f}  "
                    f"imp={importances[idx]:.0f}"
                )
        print(f"{'-' * 55}\n")
