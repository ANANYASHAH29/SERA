"""Stores the result of a controlled intervention: the tenant's own CI
reverts the top suspect commit's flagged files to their pre-commit state,
re-runs the canary, and reports whether accuracy actually recovered.

This is deliberately a second, separate report rather than something SERA
computes itself -- reverting files and re-running the pipeline is exactly
the kind of tenant-code execution SERA never does on its own infrastructure
(see routes_report.py's module docstring). The tenant's CI already has the
checkout and the dependencies, so it does the revert-and-rerun itself and
reports the before/after numbers here, the same trust model as every other
report in this codebase.
"""
from __future__ import annotations

import json
from typing import List, Optional

from sera.db.models import ScanResult

REGRESSION_THRESHOLD = 0.05  # same threshold used to call the original drop an incident


def record_validation(scan: ScanResult, files_reverted: List[str], after_metric: float) -> dict:
    summary = json.loads(scan.summary_json or "{}")
    baseline_metric = summary.get("baseline_metric")
    before_metric = summary.get("current_metric")
    top_candidate = (summary.get("candidates") or [None])[0]

    recovered = baseline_metric is not None and (baseline_metric - after_metric) < REGRESSION_THRESHOLD

    validation = {
        "files_reverted": files_reverted,
        "before_metric": before_metric,
        "after_metric": after_metric,
        "baseline_metric": baseline_metric,
        "recovered": recovered,
        "suspect_commit_sha": top_candidate.get("commit_sha") if top_candidate else None,
        "stage_label": top_candidate.get("stage_label") if top_candidate else None,
    }
    scan.validation_json = json.dumps(validation)
    return validation


def load_validation(scan: ScanResult) -> Optional[dict]:
    if not scan.validation_json:
        return None
    try:
        return json.loads(scan.validation_json)
    except ValueError:
        return None
