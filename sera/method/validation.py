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


def _verdict_for(before_metric: Optional[float], after_metric: float, baseline_metric: Optional[float], combined: bool) -> str:
    recovered = baseline_metric is not None and (baseline_metric - after_metric) < REGRESSION_THRESHOLD
    if recovered:
        return "validated_combined" if combined else "validated"
    if combined:
        return "insufficient_combined"
    improved = before_metric is not None and after_metric > before_metric + 0.01
    # An individual revert with zero (or negative) improvement is NOT
    # evidence the commit is innocent -- in a multi-fault incident,
    # commits interact, and only a full re-diagnosis (or the combined
    # attempt) can rule one out. "not_supported" names the actual
    # evidence (no individual improvement observed) instead of claiming
    # a conclusion ("innocent") the single test can't support.
    return "insufficient_as_sole_cause" if improved else "not_supported"


def record_interventions(scan: ScanResult, attempts: List[dict]) -> List[dict]:
    """Sequential-validation version of record_validation: stores every
    individual + combined intervention attempt tried for this incident,
    in order, each with its own verdict computed from the SAME before/
    after evidence -- never a single collapsed recovered/not-recovered
    boolean. `validation_json` (the single-attempt field the existing
    dashboard cards already read) is kept in sync with the FIRST attempt,
    so nothing that already renders that field breaks.
    """
    summary = json.loads(scan.summary_json or "{}")
    baseline_metric = summary.get("baseline_metric")
    before_metric = summary.get("current_metric")

    recorded = []
    for a in attempts:
        verdict = _verdict_for(before_metric, a["after_metric"], baseline_metric, a.get("combined", False))
        recorded.append(
            {
                "commit_sha": a["commit_sha"],
                "stage_label": a.get("stage_label"),
                "files_reverted": a["files_reverted"],
                "before_metric": before_metric,
                "after_metric": a["after_metric"],
                "baseline_metric": baseline_metric,
                "combined": a.get("combined", False),
                "verdict": verdict,
                "recovered": verdict in ("validated", "validated_combined"),
            }
        )

    scan.interventions_json = json.dumps(recorded)
    if recorded:
        first = recorded[0]
        scan.validation_json = json.dumps(
            {
                "files_reverted": first["files_reverted"],
                "before_metric": first["before_metric"],
                "after_metric": first["after_metric"],
                "baseline_metric": first["baseline_metric"],
                "recovered": first["recovered"],
                "suspect_commit_sha": first["commit_sha"],
                "stage_label": first["stage_label"],
            }
        )
    return recorded


def load_interventions(scan: ScanResult) -> List[dict]:
    if not scan.interventions_json:
        return []
    try:
        return json.loads(scan.interventions_json)
    except ValueError:
        return []
