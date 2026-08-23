"""Serves the pre-computed experiment sweep (results/*.csv, written by
experiments/run_trials.py + build_confusion_matrix.py + cost_comparison.py)
as JSON, so the frontend doesn't need a CSV parser. Read-only -- this
router never re-runs the sweep, it just reads whatever's already there.
"""
from __future__ import annotations

import math

import pandas as pd
from fastapi import APIRouter, HTTPException

from sera.conditions.registry import ALL_CATEGORIES
from sera.config import RESULTS_DIR

router = APIRouter(prefix="/experiments", tags=["experiments"])

LABELS = ALL_CATEGORIES + ["NONE"]


def _clean(records: list) -> list:
    """Replace NaN (pandas' hole for missing values) with None so it
    survives JSON serialization instead of becoming invalid JSON.
    """
    for row in records:
        for k, v in row.items():
            if isinstance(v, float) and math.isnan(v):
                row[k] = None
    return records


@router.get("/summary")
def experiments_summary():
    accuracy_path = RESULTS_DIR / "accuracy_summary.csv"
    cost_path = RESULTS_DIR / "cost_comparison.csv"
    if not accuracy_path.exists() or not cost_path.exists():
        raise HTTPException(
            404,
            "no experiment results found -- run experiments/run_trials.py, "
            "build_confusion_matrix.py, and cost_comparison.py first",
        )

    accuracy_summary = _clean(pd.read_csv(accuracy_path).to_dict(orient="records"))
    cost_comparison = _clean(pd.read_csv(cost_path).to_dict(orient="records"))

    confusion_matrices = {}
    for method in [row["method"] for row in accuracy_summary]:
        cm_path = RESULTS_DIR / f"confusion_matrix_{method}.csv"
        if cm_path.exists():
            df = pd.read_csv(cm_path, index_col=0)
            confusion_matrices[method] = {
                "labels": list(df.columns),
                "conditions": list(df.index),
                "matrix": df.values.tolist(),
            }

    return {
        "accuracy_summary": accuracy_summary,
        "cost_comparison": cost_comparison,
        "confusion_matrices": confusion_matrices,
    }
