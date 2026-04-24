"""
ml/label_generator.py
─────────────────────
3-class labels from 2m candle closes.

  0 → NEUTRAL  (move within ±threshold)
  1 → BUY      (forward return > +threshold)
  2 → SELL     (forward return < −threshold)
 -1 → unknown  (last forward_bars rows — dropped before training)
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from config import ML_LABEL_FORWARD_BARS, ML_LABEL_THRESHOLD


class LabelGenerator:

    @staticmethod
    def generate(
        closes:       np.ndarray,
        forward_bars: int   = ML_LABEL_FORWARD_BARS,
        threshold:    float = ML_LABEL_THRESHOLD,
    ) -> np.ndarray:
        n      = len(closes)
        labels = np.full(n, -1, dtype=np.int8)

        for i in range(n - forward_bars):
            entry = closes[i]
            if entry == 0:
                labels[i] = 0
                continue
            ret = (closes[i + forward_bars] - entry) / entry
            if   ret >  threshold: labels[i] = 1
            elif ret < -threshold: labels[i] = 2
            else:                  labels[i] = 0

        return labels

    @staticmethod
    def apply_to_df(
        df:           pd.DataFrame,
        close_col:    str   = "Close",
        forward_bars: int   = ML_LABEL_FORWARD_BARS,
        threshold:    float = ML_LABEL_THRESHOLD,
    ) -> pd.DataFrame:
        df = df.copy()
        df["label"] = LabelGenerator.generate(
            df[close_col].values, forward_bars, threshold
        )
        return df[df["label"] >= 0].copy()

    @staticmethod
    def class_distribution(labels: np.ndarray) -> dict:
        names   = {0: "NEUTRAL", 1: "BUY", 2: "SELL"}
        unique, counts = np.unique(labels[labels >= 0], return_counts=True)
        dist    = {int(u): int(c) for u, c in zip(unique, counts)}
        total   = sum(dist.values())
        print("  Label distribution:")
        for cls, cnt in sorted(dist.items()):
            print(f"    {names.get(cls, cls):8s}  {cnt:6d}  ({100*cnt/total:.1f}%)")
        return dist