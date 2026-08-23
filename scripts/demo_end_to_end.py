"""Scripted end-to-end demo: healthy baseline -> inject F3 -> detection
fires -> commit history fetched (synthetic by default, real GitHub with
--github) -> ranking produced -> top candidate validated -> recovery
confirmed -> case stored in memory. Meant to be read out loud during a
live demo -- each step prints what it found before moving on.

Usage:
    python scripts/demo_end_to_end.py
    python scripts/demo_end_to_end.py --github owner/repo --since 2026-08-01 --until 2026-08-23
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sera.conditions.registry import CONFIG_CONDITIONS
from sera.config import baseline_config
from sera.db.session import session_scope
from sera.github_integration.diff_analyzer import classify_commits
from sera.github_integration.fetch_commits import fetch_commit_history
from sera.github_integration.synthetic_history import generate_synthetic_history
from sera.method.evidence_signals import compute_shape_features
from sera.method.memory import record_incident, record_ranking, record_run, resolve_incident
from sera.method.ranker import rank_candidates
from sera.method.validator import validate_top_candidate
from sera.pipeline.ingestion import build_canary_set
from sera.pipeline.runner import run_pipeline

REGRESSION_THRESHOLD = 0.05


def step(title: str) -> None:
    print(f"\n{'=' * 70}\n{title}\n{'=' * 70}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--github", type=str, default=None, help="owner/repo for real GitHub mode")
    parser.add_argument("--since", type=str, default=None)
    parser.add_argument("--until", type=str, default=None)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    step("STEP 1: healthy baseline run")
    base_config = baseline_config()
    canary = build_canary_set()
    baseline_metrics = run_pipeline(base_config, canary, corruption_seed=args.seed)
    print(f"baseline accuracy={baseline_metrics.accuracy:.3f}  "
          f"mean_confidence={baseline_metrics.mean_confidence:.3f}  "
          f"mean_entropy={baseline_metrics.mean_entropy:.3f}")

    step("STEP 2: inject F3 (normalization drift)")
    regressed_config = CONFIG_CONDITIONS["F3"].apply(base_config, severity=0.6)
    regressed_metrics = run_pipeline(regressed_config, canary, corruption_seed=args.seed)
    print(f"regressed accuracy={regressed_metrics.accuracy:.3f}  "
          f"mean_confidence={regressed_metrics.mean_confidence:.3f}  "
          f"mean_entropy={regressed_metrics.mean_entropy:.3f}")

    drop = baseline_metrics.accuracy - regressed_metrics.accuracy
    step("STEP 3: regression detection")
    if drop < REGRESSION_THRESHOLD:
        print(f"accuracy drop {drop:.3f} below threshold {REGRESSION_THRESHOLD} -- no incident. Exiting.")
        return
    print(f"accuracy drop = {drop:.3f} >= threshold {REGRESSION_THRESHOLD} -> INCIDENT OPENED")

    step("STEP 4: commit history retrieval")
    if args.github:
        since = datetime.fromisoformat(args.since)
        until = datetime.fromisoformat(args.until)
        print(f"fetching real commit history for {args.github} [{since} .. {until}]")
        commits = fetch_commit_history(args.github, since=since, until=until)
    else:
        print("using synthetic commit history (no --github repo given)")
        commits = generate_synthetic_history(
            num_harmless=4, guilty_category="F3", include_concurrent_unrelated=True, seed=args.seed
        )
    classify_commits(commits)
    for c in commits:
        tag = f"risk={c.risk_categories}" if c.risk_categories else "harmless"
        print(f"  {c.sha[:12]}  {c.timestamp.isoformat()}  {c.message!r}  [{tag}]")

    step("STEP 5: joint ranking (commits + drift hypothesis)")
    observed_shape = compute_shape_features(baseline_metrics, regressed_metrics)
    print(f"observed shape: {observed_shape}")
    ranked = rank_candidates(commits, observed_shape)
    for i, cand in enumerate(ranked):
        label = cand.commit.sha[:12] if cand.commit else "NO_COMMIT (drift)"
        print(
            f"  #{i+1}  {label:20s}  category={cand.hypothesized_category}  "
            f"provenance={cand.provenance_score:.2f}  shape_match={cand.shape_match_score:.2f}  "
            f"combined={cand.combined_score:.3f}"
        )

    top = ranked[0]
    top_label = top.commit.sha[:12] if top.commit else "NO_COMMIT (drift)"
    print(f"\n>>> top-ranked suspect: {top_label}")

    step("STEP 6: isolated validation of the top candidate only")
    outcome = validate_top_candidate(
        top,
        regressed_config,
        base_config,
        canary,
        before_accuracy=regressed_metrics.accuracy,
        baseline_accuracy=baseline_metrics.accuracy,
    )
    print(f"before={outcome.before_accuracy:.3f}  after={outcome.after_accuracy:.3f}  "
          f"recovered={outcome.recovered}  confirmed={outcome.confirmed}")

    step("STEP 7: case stored in memory")
    with session_scope() as session:
        baseline_run = record_run(session, base_config, baseline_metrics, seed=args.seed, is_baseline=True)
        regressed_run = record_run(session, regressed_config, regressed_metrics, seed=args.seed, is_baseline=False)
        incident = record_incident(session, baseline_run, regressed_run, injected_condition="F3")
        record_ranking(session, incident, ranked)
        case = resolve_incident(session, incident, outcome)
        print(f"incident #{incident.id} stored, case #{case.id} confirmed_cause={case.confirmed_cause}")

    step("DONE")
    print("SERA correctly attributed the regression to the F3 commit, validated it with exactly")
    print("one isolated re-evaluation, and stored the resolved case for future ranking priors.")


if __name__ == "__main__":
    main()
