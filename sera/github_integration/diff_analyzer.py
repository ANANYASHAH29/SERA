"""Classifies a commit's changed files into F1-F5 risk categories.

Deliberately simple, cheap matching against filenames/paths — this is the
"cheap, pre-execution evidence" step from the design: no build, no
checkout, no re-execution of the pipeline, just looking at which paths a
diff touched.

Two pattern sources:
  - A repo's own `.sera.yml` (see `sera.repo_config`), matched as glob
    patterns via `fnmatch` against the full path -- this is what makes
    SERA usable against an arbitrary repo instead of just its own demo
    pipeline.
  - SERA's hardcoded demo-pipeline patterns (`sera.conditions.registry`),
    matched as case-insensitive substrings, used whenever no `.sera.yml`
    is found so the existing CIFAR-10 demo keeps working unchanged.
"""
from __future__ import annotations

import fnmatch
from pathlib import PurePosixPath
from typing import Iterable, List, Optional

from sera.conditions.registry import all_risk_patterns
from sera.github_integration.commit_types import CommitInfo
from sera.repo_config import RepoConfig


def _matches_glob(path: str, patterns: List[str]) -> bool:
    # Plain fnmatch, so patterns are full-string matches: "models/*.ckpt"
    # only matches a file directly under models/, not arbitrarily nested --
    # write "**/models/*.ckpt" (or just "*.ckpt") to match at any depth.
    # This is deliberately simpler than gitignore's implicit-anywhere rules.
    name = PurePosixPath(path).name
    return any(fnmatch.fnmatch(path, p) or fnmatch.fnmatch(name, p) for p in patterns)


def _matches_substring(path: str, patterns: List[str]) -> bool:
    lowered = path.lower()
    return any(p.lower() in lowered for p in patterns)


def classify_files(
    files_changed: Iterable[str], repo_config: Optional[RepoConfig] = None
) -> List[str]:
    """Return the sorted list of risk categories any of `files_changed` map to.

    If `repo_config` has risk patterns, those are used (glob matching).
    Otherwise falls back to SERA's built-in demo-pipeline patterns
    (substring matching, unchanged from before `.sera.yml` support existed).
    """
    if repo_config is not None and repo_config.risk_patterns:
        patterns = repo_config.risk_patterns
        matcher = _matches_glob
    else:
        patterns = all_risk_patterns()
        matcher = _matches_substring

    hits = set()
    for path in files_changed:
        for category, pats in patterns.items():
            if matcher(path, pats):
                hits.add(category)
    return sorted(hits)


def classify_commit(commit: CommitInfo, repo_config: Optional[RepoConfig] = None) -> CommitInfo:
    """Classify in place and return the same CommitInfo for chaining."""
    commit.risk_categories = classify_files(commit.files_changed, repo_config=repo_config)
    return commit


def classify_commits(
    commits: Iterable[CommitInfo], repo_config: Optional[RepoConfig] = None
) -> List[CommitInfo]:
    return [classify_commit(c, repo_config=repo_config) for c in commits]
