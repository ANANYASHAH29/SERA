"""PR-comment bot: on a PR, runs the canary eval at the PR's base commit
and at its head commit (a git-native "revert and re-run", equivalent in
spirit to SERA's in-process validator but for an arbitrary repo's own
code), ranks the PR's own commits against the drift hypothesis, and
comments ONLY if this specific PR's own commits are the top suspect.
Stays silent if the top suspect is drift or if there's no regression at
all -- a bot that comments on every PR "just in case" trains people to
ignore it, which defeats the point.

Meant to run inside a GitHub Actions workflow after actions/checkout
(see .github/workflows/sera_pr_check.yml), but also runs standalone for
local testing:

    python scripts/pr_check.py --repo owner/name --pr 42 --repo-root .

Requires a GITHUB_TOKEN with pull-request write access (the Actions
default GITHUB_TOKEN has this for same-repo PRs).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from sera.canary_interface import (
    reference_cifar10_canary_eval,
    run_subprocess_canary_eval,
    to_run_metrics,
)
from sera.conditions.registry import NO_COMMIT_CANDIDATE_ID
from sera.github_integration.commit_types import CommitInfo
from sera.github_integration.diff_analyzer import classify_commits
from sera.github_integration.pr_commenter import format_comment, post_pr_comment
from sera.method.evidence_signals import compute_shape_features
from sera.method.ranker import rank_candidates
from sera.repo_config import load_repo_config_from_path

REGRESSION_THRESHOLD = 0.05


def log(msg: str) -> None:
    print(msg)
    step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if step_summary:
        with open(step_summary, "a", encoding="utf-8") as f:
            f.write(msg + "\n")


def run_canary_at_current_checkout(repo_root: Path):
    config = load_repo_config_from_path(repo_root)
    if config and config.canary_entrypoint:
        return run_subprocess_canary_eval(config.canary_entrypoint, cwd=repo_root)
    return reference_cifar10_canary_eval()


def evaluate_at_ref(repo_root: Path, sha: str):
    """Checks out `sha` in the local repo, runs the canary eval there, then
    restores the original ref. Refuses to run against a dirty working tree.
    """
    import git

    repo = git.Repo(repo_root)
    if repo.is_dirty(untracked_files=False):
        raise RuntimeError(
            "refusing to checkout a different commit: working tree has uncommitted changes"
        )
    original_ref = repo.head.commit.hexsha
    try:
        repo.git.checkout(sha)
        return run_canary_at_current_checkout(repo_root)
    finally:
        repo.git.checkout(original_ref)


def get_pr_context(repo_full_name: str, pr_number: int, token: str):
    from github import Github

    client = Github(token) if token else Github()
    repo = client.get_repo(repo_full_name)
    pr = repo.get_pull(pr_number)

    commits = []
    for gh_commit in pr.get_commits():
        commit_data = gh_commit.commit
        commits.append(
            CommitInfo(
                sha=gh_commit.sha,
                message=(commit_data.message.splitlines()[0] if commit_data.message else ""),
                author=commit_data.author.name if commit_data.author else "unknown",
                timestamp=commit_data.author.date if commit_data.author else None,
                files_changed=[f.filename for f in (gh_commit.files or [])],
                pr_number=pr_number,
                pr_html_url=pr.html_url,
            )
        )
    return pr, commits, pr.base.sha, pr.head.sha


def resolve_event_pr_number() -> int:
    event_path = os.environ.get("GITHUB_EVENT_PATH")
    if not event_path or not os.path.exists(event_path):
        raise RuntimeError("no --pr given and GITHUB_EVENT_PATH is not set")
    event = json.loads(Path(event_path).read_text())
    pr = event.get("pull_request")
    if not pr:
        raise RuntimeError("GITHUB_EVENT_PATH does not contain a pull_request payload")
    return pr["number"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=str, default=os.environ.get("GITHUB_REPOSITORY"))
    parser.add_argument("--pr", type=int, default=None)
    parser.add_argument("--repo-root", type=str, default=".")
    parser.add_argument("--token", type=str, default=os.environ.get("GITHUB_TOKEN"))
    parser.add_argument("--dry-run", action="store_true", help="rank but never post a comment")
    args = parser.parse_args()

    if not args.repo:
        raise RuntimeError("--repo not given and GITHUB_REPOSITORY is not set")
    pr_number = args.pr if args.pr is not None else resolve_event_pr_number()
    repo_root = Path(args.repo_root).resolve()

    log(f"## SERA PR check — {args.repo}#{pr_number}")

    pr, commits, base_sha, head_sha = get_pr_context(args.repo, pr_number, args.token)
    repo_config = load_repo_config_from_path(repo_root)
    classify_commits(commits, repo_config=repo_config)
    for c in commits:
        tag = f"risk={c.risk_categories}" if c.risk_categories else "harmless"
        log(f"  {c.sha[:12]}  {c.message!r}  [{tag}]")

    log(f"evaluating canary at base ({base_sha[:12]}) and head ({head_sha[:12]})...")
    baseline_result = evaluate_at_ref(repo_root, base_sha)
    current_result = evaluate_at_ref(repo_root, head_sha)

    drop = baseline_result.accuracy - current_result.accuracy
    log(f"base accuracy={baseline_result.accuracy:.3f}  head accuracy={current_result.accuracy:.3f}  drop={drop:.3f}")

    if drop < REGRESSION_THRESHOLD:
        log(f"drop below threshold {REGRESSION_THRESHOLD} — no comment posted. Clean.")
        return 0

    baseline_metrics = to_run_metrics(baseline_result)
    current_metrics = to_run_metrics(current_result)
    observed_shape = compute_shape_features(baseline_metrics, current_metrics)

    ranked = rank_candidates(commits, observed_shape)
    top = ranked[0]
    pr_commit_shas = {c.sha for c in commits}

    if top.candidate_id not in pr_commit_shas:
        log(
            f"regression detected (drop={drop:.3f}) but top suspect is "
            f"{'drift, not this PR' if top.candidate_id == NO_COMMIT_CANDIDATE_ID else 'a commit outside this PR'} "
            f"— staying silent to avoid false-blaming this PR."
        )
        return 0

    log(f"top suspect IS this PR's commit {top.candidate_id[:12]} — posting comment.")
    evidence = [
        f"commit `{top.candidate_id[:12]}` touches a risk-category file (category {top.hypothesized_category})",
        f"observed confidence/entropy-shift shape matches {top.hypothesized_category}'s known pattern "
        f"(shape match {top.shape_match_score:.2f})",
        f"combined evidence score {top.combined_score:.2f} (next-highest candidate: "
        f"{ranked[1].combined_score:.2f})",
    ]
    body = format_comment(
        before_accuracy=baseline_result.accuracy,
        after_accuracy=current_result.accuracy,
        detected_date=date.today(),
        evidence=evidence,
    )

    if args.dry_run:
        log("--dry-run set: not actually posting. Comment body would be:\n" + body)
    else:
        url = post_pr_comment(args.repo, pr_number, body, token=args.token)
        log(f"posted comment: {url}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
