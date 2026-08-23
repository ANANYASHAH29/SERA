"""Runs a canary evaluation independent of any PR being open -- required
for genuine drift (D1) to ever be caught in real usage, since drift isn't
triggered by a code change and a PR-only check would never see it.

Persists a small baseline-metrics JSON (not the full SQLite DB — see
README "Scheduled canary runs" for why) so each scheduled run can diff
against the last known-good state. First run bootstraps that file.

Usage (standalone, e.g. a cron job or a manual run):
    python scripts/run_scheduled_canary.py --baseline-file .sera/baseline_metrics.json

Usage (inside a GitHub Actions workflow, with commit-history ranking):
    python scripts/run_scheduled_canary.py \
        --baseline-file .sera/baseline_metrics.json \
        --repo owner/name --lookback-hours 6
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sera.canary_interface import (
    reference_cifar10_canary_eval,
    run_subprocess_canary_eval,
    to_run_metrics,
)
from sera.db.session import session_scope
from sera.github_integration.diff_analyzer import classify_commits
from sera.github_integration.fetch_commits import fetch_commit_history
from sera.method.evidence_signals import compute_shape_features
from sera.method.memory import record_incident, record_ranking, record_run
from sera.method.ranker import rank_candidates
from sera.repo_config import load_repo_config_from_path

REGRESSION_THRESHOLD = 0.05


def _github_step_summary(text: str) -> None:
    import os

    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write(text + "\n")
    print(text)


def load_baseline(path: Path):
    if not path.exists():
        return None
    return json.loads(path.read_text())


def save_baseline(path: Path, result) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "accuracy": result.accuracy,
                "mean_confidence": result.mean_confidence,
                "mean_entropy": result.mean_entropy,
                "per_sample_confidence": result.per_sample_confidence,
                "per_sample_correct": result.per_sample_correct,
                "recorded_at": datetime.now(timezone.utc).isoformat(),
            },
            indent=2,
        )
    )


def baseline_dict_to_result(d: dict):
    from sera.canary_interface import CanaryEvalResult

    return CanaryEvalResult(
        accuracy=d["accuracy"],
        mean_confidence=d["mean_confidence"],
        mean_entropy=d.get("mean_entropy", 0.0),
        per_sample_confidence=d["per_sample_confidence"],
        per_sample_correct=d["per_sample_correct"],
    )


def run_canary(repo_root: Path):
    config = load_repo_config_from_path(repo_root)
    if config and config.canary_entrypoint:
        return run_subprocess_canary_eval(config.canary_entrypoint, cwd=repo_root)
    return reference_cifar10_canary_eval()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=str, default=".")
    parser.add_argument("--baseline-file", type=str, default=".sera/baseline_metrics.json")
    parser.add_argument("--repo", type=str, default=None, help="owner/name, for commit-history ranking")
    parser.add_argument("--lookback-hours", type=int, default=6)
    parser.add_argument("--update-baseline-on-success", action="store_true", default=True)
    args = parser.parse_args()

    repo_root = Path(args.repo_root).resolve()
    baseline_path = Path(args.baseline_file)
    if not baseline_path.is_absolute():
        baseline_path = repo_root / baseline_path

    _github_step_summary(f"## SERA scheduled canary run — {datetime.now(timezone.utc).isoformat()}")

    current = run_canary(repo_root)
    _github_step_summary(
        f"current: accuracy={current.accuracy:.3f} mean_confidence={current.mean_confidence:.3f}"
    )

    baseline_data = load_baseline(baseline_path)
    if baseline_data is None:
        save_baseline(baseline_path, current)
        _github_step_summary(f"no prior baseline found at `{baseline_path}` — bootstrapped one from this run.")
        return 0

    baseline_result = baseline_dict_to_result(baseline_data)
    drop = baseline_result.accuracy - current.accuracy
    _github_step_summary(f"baseline accuracy={baseline_result.accuracy:.3f}  drop={drop:.3f}")

    if drop < REGRESSION_THRESHOLD:
        _github_step_summary(f"drop {drop:.3f} below threshold {REGRESSION_THRESHOLD} — no incident. Healthy.")
        if args.update_baseline_on_success:
            save_baseline(baseline_path, current)
        return 0

    _github_step_summary(f"**INCIDENT: accuracy dropped {drop:.3f} — investigating.**")

    baseline_metrics = to_run_metrics(baseline_result)
    current_metrics = to_run_metrics(current)
    observed_shape = compute_shape_features(baseline_metrics, current_metrics)

    commits = []
    if args.repo:
        since = datetime.now(timezone.utc) - timedelta(hours=args.lookback_hours)
        until = datetime.now(timezone.utc)
        repo_config = load_repo_config_from_path(repo_root)
        commits = fetch_commit_history(args.repo, since=since, until=until)
        classify_commits(commits, repo_config=repo_config)

    ranked = rank_candidates(commits, observed_shape)
    top = ranked[0]
    top_label = top.commit.sha[:12] if top.commit else "NO_COMMIT (drift)"
    _github_step_summary(f"top suspect: **{top_label}** (category={top.hypothesized_category}, score={top.combined_score:.3f})")

    # Scheduled mode intentionally stops at ranking, not validation: SERA's
    # in-process validator (sera.method.validator) reverts a PipelineConfig
    # field, which only makes sense for the CIFAR-10 reference pipeline. A
    # pluggable repo's canary is an opaque subprocess with no such config to
    # revert. Full validation for an arbitrary repo is exactly what the PR
    # bot provides instead (scripts/pr_check.py), by diffing accuracy at the
    # PR's base commit vs. its head commit via git checkout -- a git-native
    # equivalent of "revert and re-run" that doesn't require SERA to
    # understand the repo's own config format.
    with session_scope() as session:
        baseline_run = record_run(session, _dummy_config(), baseline_metrics, seed=None, is_baseline=True)
        regressed_run = record_run(session, _dummy_config(), current_metrics, seed=None, is_baseline=False)
        incident = record_incident(session, baseline_run, regressed_run, repo_full_name=args.repo)
        record_ranking(session, incident, ranked)
        _github_step_summary(f"incident #{incident.id} stored in case memory (unvalidated — see README).")

    _github_step_summary(
        "Note: scheduled mode ranks candidates but does not run the isolated "
        "revert-and-reevaluate validation step, since that requires an in-process "
        "PipelineConfig SERA controls. For full validation, wire this incident into "
        "the FastAPI `/incidents/{id}/validate` flow or extend the subprocess canary "
        "contract with a revert hook."
    )
    return 1


def _dummy_config():
    from sera.config import baseline_config

    return baseline_config()


if __name__ == "__main__":
    sys.exit(main())
