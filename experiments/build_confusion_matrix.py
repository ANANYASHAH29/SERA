"""Builds a 6x6 (true condition x predicted category) confusion matrix per
method from results/trials.csv, plus top-1/top-2 accuracy with 95%
confidence intervals across seeds, and PNG heatmaps.

Usage:
    python experiments/build_confusion_matrix.py --in results/trials.csv --out-dir results/
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from sera.conditions.registry import ALL_CATEGORIES

LABELS = ALL_CATEGORIES + ["NONE"]


def _wilson_ci(successes: int, n: int, z: float = 1.96):
    if n == 0:
        return (float("nan"), float("nan"), float("nan"))
    p = successes / n
    denom = 1 + z**2 / n
    center = (p + z**2 / (2 * n)) / denom
    half = (z * math.sqrt((p * (1 - p) + z**2 / (4 * n)) / n)) / denom
    return p, max(0.0, center - half), min(1.0, center + half)


def accuracy_summary(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for method, g in df.groupby("method"):
        n = len(g)
        top1_hits = int(g["top1_correct"].sum())
        top2_hits = int(g["top2_correct"].sum())
        top1_mean, top1_lo, top1_hi = _wilson_ci(top1_hits, n)
        top2_mean, top2_lo, top2_hi = _wilson_ci(top2_hits, n)
        rows.append(
            dict(
                method=method,
                n_trials=n,
                top1_accuracy=top1_mean,
                top1_ci_low=top1_lo,
                top1_ci_high=top1_hi,
                top2_accuracy=top2_mean,
                top2_ci_low=top2_lo,
                top2_ci_high=top2_hi,
            )
        )
    return pd.DataFrame(rows).sort_values("method").reset_index(drop=True)


def confusion_matrix_for_method(df: pd.DataFrame, method: str) -> pd.DataFrame:
    sub = df[df["method"] == method]
    matrix = pd.crosstab(sub["condition"], sub["guess_category"])
    matrix = matrix.reindex(index=ALL_CATEGORIES, columns=LABELS, fill_value=0)
    return matrix


def plot_confusion_matrix(matrix: pd.DataFrame, method: str, out_path: Path) -> None:
    fig, ax = plt.subplots(figsize=(6, 5))
    im = ax.imshow(matrix.values, cmap="Blues")
    ax.set_xticks(range(len(matrix.columns)))
    ax.set_xticklabels(matrix.columns, rotation=45, ha="right")
    ax.set_yticks(range(len(matrix.index)))
    ax.set_yticklabels(matrix.index)
    ax.set_xlabel("predicted category")
    ax.set_ylabel("true condition")
    ax.set_title(f"SERA confusion matrix — {method}")
    for i in range(matrix.shape[0]):
        for j in range(matrix.shape[1]):
            ax.text(j, i, str(matrix.values[i, j]), ha="center", va="center", fontsize=8)
    fig.colorbar(im, ax=ax, shrink=0.8)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--in", dest="infile", type=str, default="results/trials.csv")
    parser.add_argument("--out-dir", type=str, default="results")
    args = parser.parse_args()

    df = pd.read_csv(args.infile)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    summary = accuracy_summary(df)
    summary.to_csv(out_dir / "accuracy_summary.csv", index=False)
    print(summary.to_string(index=False))

    for method in sorted(df["method"].unique()):
        matrix = confusion_matrix_for_method(df, method)
        matrix.to_csv(out_dir / f"confusion_matrix_{method}.csv")
        plot_confusion_matrix(matrix, method, out_dir / f"confusion_matrix_{method}.png")
        print(f"wrote confusion matrix for {method}")


if __name__ == "__main__":
    main()
