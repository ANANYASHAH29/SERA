"""Cost-comparison table: accuracy vs number of expensive re-evaluations
per method -- the key result differentiating SERA from brute-force
bisection (both reach an answer, but bisection pays O(log N) expensive
re-evaluations while SERA/baselines pay exactly 1).

Usage:
    python experiments/cost_comparison.py --in results/trials.csv --out results/cost_comparison.csv
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


def build_cost_table(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for method, g in df.groupby("method"):
        rows.append(
            dict(
                method=method,
                top1_accuracy=g["top1_correct"].mean(),
                top2_accuracy=g["top2_correct"].mean(),
                mean_reevaluations=g["num_reevaluations"].mean(),
                max_reevaluations=g["num_reevaluations"].max(),
                total_reevaluations=g["num_reevaluations"].sum(),
                n_trials=len(g),
            )
        )
    out = pd.DataFrame(rows).sort_values("mean_reevaluations").reset_index(drop=True)
    sera_cost = out.loc[out["method"] == "sera", "mean_reevaluations"]
    bisect_cost = out.loc[out["method"] == "full_bisection", "mean_reevaluations"]
    if len(sera_cost) and len(bisect_cost) and sera_cost.iloc[0] > 0:
        speedup = bisect_cost.iloc[0] / sera_cost.iloc[0]
        out["reevals_vs_sera"] = out["mean_reevaluations"] / sera_cost.iloc[0]
        print(f"full_bisection uses {speedup:.1f}x more expensive re-evaluations than SERA on average")
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--in", dest="infile", type=str, default="results/trials.csv")
    parser.add_argument("--out", type=str, default="results/cost_comparison.csv")
    args = parser.parse_args()

    df = pd.read_csv(args.infile)
    table = build_cost_table(df)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    table.to_csv(out_path, index=False)
    print(table.to_string(index=False))


if __name__ == "__main__":
    main()
