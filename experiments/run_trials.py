"""Multi-seed experiment runner: all 6 conditions x all 4 methods
(3 baselines + SERA), recording each method's top-ranked guess vs ground
truth and the number of expensive re-evaluations it needed.

Usage:
    python experiments/run_trials.py --seeds 0 1 2 3 4 --out results/trials.csv
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from sera.baselines.confidence_only import guess_from_shape_only
from sera.baselines.full_bisection import bisect_commits
from sera.baselines.naive_latest_commit import guess_latest_commit
from sera.conditions.registry import ALL_CATEGORIES, NO_COMMIT_CANDIDATE_ID
from sera.method.ranker import rank_candidates
from sera.method.validator import validate_top_candidate

from experiments.scenario import (
    bisection_bad_threshold,
    build_scenario,
    config_as_of_factory,
    run_baseline_and_regressed,
)
from sera.method.evidence_signals import compute_shape_features

METHODS = ["sera", "naive_latest", "confidence_only", "full_bisection"]


def _top1_correct(guess_candidate_id: str, ground_truth_id: str) -> bool:
    return guess_candidate_id == ground_truth_id


def _top2_correct(ranked_ids, ground_truth_id: str) -> bool:
    return ground_truth_id in ranked_ids[:2]


def _category_of_guess(guess_id: str, commits) -> str:
    """Map a guessed candidate id back to a condition category (F1-F5/D1/NONE)
    for confusion-matrix purposes, using the commit's *true* synthetic
    risk-category label (not the method's own belief about it).
    """
    if guess_id == NO_COMMIT_CANDIDATE_ID:
        return "D1"
    for c in commits:
        if c.sha == guess_id:
            return c.risk_categories[0] if c.risk_categories else "NONE"
    return "NONE"


def run_one_trial(condition: str, seed: int) -> list:
    scenario = build_scenario(condition, seed=seed)
    baseline_metrics, regressed_metrics = run_baseline_and_regressed(scenario)
    observed_shape = compute_shape_features(baseline_metrics, regressed_metrics)
    ground_truth_id = scenario.ground_truth_candidate_id

    rows = []

    # --- SERA ---
    ranked = rank_candidates(scenario.commits, observed_shape)
    top = ranked[0]
    outcome = validate_top_candidate(
        top,
        scenario.regressed_config,
        scenario.baseline_config,
        scenario.regressed_batch,
        before_accuracy=regressed_metrics.accuracy,
        baseline_accuracy=baseline_metrics.accuracy,
    )
    rows.append(
        dict(
            method="sera",
            condition=condition,
            seed=seed,
            top1_correct=_top1_correct(top.candidate_id, ground_truth_id),
            top2_correct=_top2_correct([c.candidate_id for c in ranked], ground_truth_id),
            num_reevaluations=outcome.num_reevaluations,
            confirmed=outcome.confirmed,
            guess=top.candidate_id,
            guess_category=_category_of_guess(top.candidate_id, scenario.commits),
        )
    )

    # --- confidence-only ---
    guess = guess_from_shape_only(scenario.commits, observed_shape)
    outcome = validate_top_candidate(
        guess,
        scenario.regressed_config,
        scenario.baseline_config,
        scenario.regressed_batch,
        before_accuracy=regressed_metrics.accuracy,
        baseline_accuracy=baseline_metrics.accuracy,
    )
    rows.append(
        dict(
            method="confidence_only",
            condition=condition,
            seed=seed,
            top1_correct=_top1_correct(guess.candidate_id, ground_truth_id),
            top2_correct=_top1_correct(guess.candidate_id, ground_truth_id),
            num_reevaluations=outcome.num_reevaluations,
            confirmed=outcome.confirmed,
            guess=guess.candidate_id,
            guess_category=_category_of_guess(guess.candidate_id, scenario.commits),
        )
    )

    # --- naive latest commit ---
    guess = guess_latest_commit(scenario.commits)
    outcome = validate_top_candidate(
        guess,
        scenario.regressed_config,
        scenario.baseline_config,
        scenario.regressed_batch,
        before_accuracy=regressed_metrics.accuracy,
        baseline_accuracy=baseline_metrics.accuracy,
    )
    rows.append(
        dict(
            method="naive_latest",
            condition=condition,
            seed=seed,
            top1_correct=_top1_correct(guess.candidate_id, ground_truth_id),
            top2_correct=_top1_correct(guess.candidate_id, ground_truth_id),
            num_reevaluations=outcome.num_reevaluations,
            confirmed=outcome.confirmed,
            guess=guess.candidate_id,
            guess_category=_category_of_guess(guess.candidate_id, scenario.commits),
        )
    )

    # --- full bisection ---
    if scenario.commits:
        accuracy_as_of = config_as_of_factory(scenario)
        bad_threshold = bisection_bad_threshold(baseline_metrics.accuracy, regressed_metrics.accuracy)
        bisect_result = bisect_commits(scenario.commits, accuracy_as_of, bad_threshold)
        bisection_guess_id = bisect_result.guessed_candidate_id
        num_reevals = bisect_result.num_reevaluations
    else:
        bisection_guess_id = NO_COMMIT_CANDIDATE_ID
        num_reevals = 0
    rows.append(
        dict(
            method="full_bisection",
            condition=condition,
            seed=seed,
            top1_correct=_top1_correct(bisection_guess_id, ground_truth_id),
            top2_correct=_top1_correct(bisection_guess_id, ground_truth_id),
            num_reevaluations=num_reevals,
            confirmed=None,
            guess=bisection_guess_id,
            guess_category=_category_of_guess(bisection_guess_id, scenario.commits),
        )
    )

    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seeds", type=int, nargs="+", default=[0, 1, 2, 3, 4])
    parser.add_argument("--out", type=str, default="results/trials.csv")
    args = parser.parse_args()

    all_rows = []
    for condition in ALL_CATEGORIES:
        for seed in args.seeds:
            print(f"running condition={condition} seed={seed}")
            all_rows.extend(run_one_trial(condition, seed))

    df = pd.DataFrame(all_rows)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_path, index=False)
    df.to_json(out_path.with_suffix(".json"), orient="records", indent=2)
    print(f"wrote {len(df)} rows to {out_path} and {out_path.with_suffix('.json')}")


if __name__ == "__main__":
    main()
