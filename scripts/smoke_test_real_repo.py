"""Read-only dry-run against a real repo: fetches commits, classifies each
one's diff into risk categories, and (optionally) shows what SERA's
ranking would look like -- all WITHOUT requiring an actual accuracy
regression to have happened. Use this to sanity-check the GitHub
integration and diff-classification logic against real merge commits,
squashed PRs, and unrelated file changes before wiring up live monitoring.

Usage:
    python scripts/smoke_test_real_repo.py --repo owner/name \
        --since 2026-08-01 --until 2026-08-23

    # against a local clone instead of hitting the GitHub API for history:
    python scripts/smoke_test_real_repo.py --local-path /path/to/clone \
        --since 2026-08-01 --until 2026-08-23

    # also print an illustrative (simulated, not real) ranking:
    python scripts/smoke_test_real_repo.py --repo owner/name \
        --since 2026-08-01 --until 2026-08-23 --simulate-condition F3
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sera.conditions.registry import ALL_CATEGORIES, DRIFT_LABEL
from sera.github_integration.commit_types import CommitInfo
from sera.github_integration.diff_analyzer import classify_commits
from sera.github_integration.fetch_commits import fetch_commit_history
from sera.method.evidence_signals import CONDITION_SHAPE_TEMPLATES
from sera.method.ranker import rank_candidates
from sera.repo_config import load_repo_config_from_github, load_repo_config_from_path


def fetch_from_local_clone(local_path: Path, since: datetime, until: datetime) -> list:
    import git

    repo = git.Repo(local_path)
    commits = []
    for c in repo.iter_commits(since=since.isoformat(), until=until.isoformat()):
        files = list(c.stats.files.keys())
        commits.append(
            CommitInfo(
                sha=c.hexsha,
                message=c.summary,
                author=c.author.name,
                timestamp=datetime.fromtimestamp(c.committed_date),
                files_changed=files,
            )
        )
    return list(reversed(commits))  # chronological order, like fetch_commit_history


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=str, default=None, help="owner/name (uses GitHub API)")
    parser.add_argument("--local-path", type=str, default=None, help="path to a local git clone")
    parser.add_argument("--since", type=str, required=True)
    parser.add_argument("--until", type=str, required=True)
    parser.add_argument("--token", type=str, default=None)
    parser.add_argument(
        "--simulate-condition",
        type=str,
        default=None,
        choices=ALL_CATEGORIES,
        help="print an illustrative ranking as if this condition's known shape were observed "
        "(no real regression required -- purely for eyeballing the ranking output)",
    )
    args = parser.parse_args()

    if not args.repo and not args.local_path:
        raise SystemExit("pass either --repo owner/name or --local-path /path/to/clone")

    since = datetime.fromisoformat(args.since)
    until = datetime.fromisoformat(args.until)

    print(f"=== fetching commits [{since} .. {until}] ===")
    if args.local_path:
        local_path = Path(args.local_path)
        commits = fetch_from_local_clone(local_path, since, until)
        repo_config = load_repo_config_from_path(local_path)
    else:
        commits = fetch_commit_history(args.repo, since=since, until=until, token=args.token)
        repo_config = load_repo_config_from_github(args.repo, ref="HEAD", token=args.token)

    print(f"fetched {len(commits)} commits")
    if repo_config:
        print(f".sera.yml found ({repo_config.source}) — using its risk patterns")
        print(f"  categories declared: {sorted(repo_config.risk_patterns)}")
    else:
        print("no .sera.yml found — falling back to SERA's built-in demo-pipeline patterns")

    classify_commits(commits, repo_config=repo_config)

    print(f"\n=== per-commit diff classification ===")
    risky_count = 0
    for c in commits:
        tag = f"risk={c.risk_categories}" if c.risk_categories else "harmless"
        if c.risk_categories:
            risky_count += 1
        n_files = len(c.files_changed)
        print(f"  {c.sha[:12]}  {c.timestamp}  files={n_files:3d}  {tag:25s}  {c.message[:60]!r}")

    print(f"\n{risky_count}/{len(commits)} commits touch at least one declared risk category.")

    if args.simulate_condition:
        print(f"\n=== illustrative ranking (SIMULATED: pretending we observed {args.simulate_condition}'s shape) ===")
        print("this is NOT a real diagnosis -- no accuracy regression was measured against this repo.")
        observed_shape = CONDITION_SHAPE_TEMPLATES[args.simulate_condition]
        ranked = rank_candidates(commits, observed_shape)
        for i, cand in enumerate(ranked[:10]):
            label = cand.commit.sha[:12] if cand.commit else "NO_COMMIT (drift)"
            print(
                f"  #{i + 1}  {label:14s}  category={cand.hypothesized_category}  "
                f"provenance={cand.provenance_score:.2f}  shape_match={cand.shape_match_score:.2f}  "
                f"combined={cand.combined_score:.3f}"
            )


if __name__ == "__main__":
    main()
