"""Shared core for processing a generic (task-agnostic) scan result --
used by BOTH the user_id-authenticated dashboard-paste endpoint
(sera/api/routes_generic_scan.py) and the report_token-authenticated CI
endpoint (sera/api/routes_report.py). Lives here, not in either route
file, specifically so neither route module needs to import the other.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Dict, List, Optional

import numpy as np
from pydantic import BaseModel, model_validator

from sera.db.models import ConnectedRepo, ScanResult
from sera.method.evidence_signals import compute_shape_features
from sera.method.memory import record_run
from sera.method.ranker import rank_candidates
from sera.pipeline.evaluation import RunMetrics

REGRESSION_THRESHOLD = 0.05


class GenericScanResult(BaseModel):
    task_type: str
    primary_metric: float
    primary_metric_name: str
    secondary_metrics: Dict[str, float] = {}
    per_sample_scores: List[int]
    n_samples: int
    canary_set_hash: Optional[str] = None
    # The commit the CI actually ran against -- optional so old reporters
    # (and the dashboard's manual-paste path, which has no git checkout to
    # ask) keep working, but required for the recovery workflow, which
    # needs to know exactly which real Git state was healthy.
    head_sha: Optional[str] = None

    @model_validator(mode="after")
    def _check_sample_count_consistency(self):
        # A silent mismatch here doesn't fail loudly at submission time --
        # it fails later and confusingly, whenever this result is next
        # compared against a DIFFERENT-length result in compute_shape_features
        # (a plain elementwise numpy subtraction that requires equal
        # lengths). Reject it up front instead.
        if len(self.per_sample_scores) != self.n_samples:
            raise ValueError(
                f"n_samples ({self.n_samples}) does not match "
                f"len(per_sample_scores) ({len(self.per_sample_scores)})"
            )
        return self


def generic_to_run_metrics(result: GenericScanResult) -> RunMetrics:
    """Adapts the generic schema into the same RunMetrics shape the frozen
    ranker/evidence_signals already consume. No per-sample confidence field
    exists in this schema (only per-sample correctness) -- broadcasting the
    aggregate mean_confidence to every sample is a documented approximation
    (same pattern canary_interface.to_run_metrics uses for entropy). This
    weakens the "confident_but_wrong" shape signal's fidelity specifically;
    it doesn't break the pipeline.
    """
    correct = np.array([bool(x) for x in result.per_sample_scores], dtype=bool)
    mean_confidence = result.secondary_metrics.get("mean_confidence", 0.5)
    mean_entropy = result.secondary_metrics.get("mean_entropy", 0.0)
    confidence = np.full(len(correct), mean_confidence, dtype=float)
    entropy = np.full(len(correct), mean_entropy, dtype=float)

    return RunMetrics(
        accuracy=result.primary_metric,
        mean_confidence=mean_confidence,
        mean_entropy=mean_entropy,
        per_image_confidence=confidence,
        per_image_entropy=entropy,
        per_image_correct=correct,
        predictions=np.zeros(len(correct), dtype=int),
    )


def load_stored_baseline(repo: ConnectedRepo) -> Optional[GenericScanResult]:
    if repo.generic_baseline_snapshot_json is None:
        return None
    try:
        return GenericScanResult(**json.loads(repo.generic_baseline_snapshot_json))
    except (ValueError, TypeError):
        return None


def _placeholder_config():
    from sera.config import baseline_config

    return baseline_config()


def process_generic_scan_result(
    session, repo: ConnectedRepo, result: GenericScanResult, fetch_commits_fn, source: str = "manual"
) -> dict:
    """Core logic: bootstrap-or-compare against the repo's generic
    baseline, rank against real commit history on a regression, and
    persist a ScanResult. `fetch_commits_fn(session, repo)` is injected
    (rather than imported directly) so this module has no dependency on
    either route file -- both routes_generic_scan.py and routes_report.py
    pass in their own `_fetch_and_classify_commits`. `source` is purely
    descriptive ("ci" vs "manual"), stored so the dashboard can show how a
    given scan actually got here instead of a hardcoded label.
    """
    current_metrics = generic_to_run_metrics(result)
    baseline_result = load_stored_baseline(repo)

    if baseline_result is None:
        repo.generic_baseline_snapshot_json = json.dumps(result.model_dump())
        repo.last_scan_at = datetime.utcnow()
        run = record_run(session, _placeholder_config(), current_metrics, seed=None, is_baseline=True)
        scan = ScanResult(
            repo_id=repo.id,
            run_id=run.id,
            status="healthy",
            head_sha=result.head_sha,
            summary_json=json.dumps(
                {
                    "task_type": result.task_type,
                    "primary_metric_name": result.primary_metric_name,
                    "baseline_metric": result.primary_metric,
                    "current_metric": result.primary_metric,
                    "metric_drop": 0.0,
                    "secondary_metrics": result.secondary_metrics,
                    "source": source,
                    "candidates": [],
                }
            ),
        )
        session.add(scan)
        session.flush()
        return {"status": "baseline_set", "primary_metric": result.primary_metric, "scan_id": scan.id}

    baseline_metrics = generic_to_run_metrics(baseline_result)
    drop = baseline_result.primary_metric - result.primary_metric
    observed_shape = compute_shape_features(baseline_metrics, current_metrics)

    window_since = None
    commits_analyzed = 0
    commits_relevant = 0
    if drop < REGRESSION_THRESHOLD:
        status = "healthy"
        repo.generic_baseline_snapshot_json = json.dumps(result.model_dump())  # rolling baseline
        candidates_out = []
    else:
        status = "incident"
        commits, repo_config, window_since = fetch_commits_fn(session, repo)
        commits_analyzed = len(commits)
        ranked = rank_candidates(commits, observed_shape)
        # Drop candidates with zero evidence (touch no risk-category file
        # at all -- e.g. a README or CI-config commit) from what's shown.
        # They contribute nothing to the hypothesis space; listing them
        # anyway just clutters the ranking with commits that were never
        # actually being considered. The drift hypothesis always stays,
        # even at a low score, since it's a genuine alternative explanation.
        visible = [c for c in ranked if c.kind == "drift" or c.combined_score > 0]
        candidates_out = [{"rank": i, **c.to_dict(repo_config)} for i, c in enumerate(visible)]
        commits_relevant = sum(1 for c in visible if c.kind == "commit")

    run = record_run(session, _placeholder_config(), current_metrics, seed=None, is_baseline=False)
    scan = ScanResult(
        repo_id=repo.id,
        run_id=run.id,
        status=status,
        head_sha=result.head_sha,
        summary_json=json.dumps(
            {
                "task_type": result.task_type,
                "primary_metric_name": result.primary_metric_name,
                "baseline_metric": baseline_result.primary_metric,
                "current_metric": result.primary_metric,
                "metric_drop": drop,
                "secondary_metrics": result.secondary_metrics,
                "observed_shape": {
                    "broadness": observed_shape.broadness,
                    "subset_concentration": observed_shape.subset_concentration,
                    "confident_but_wrong": observed_shape.confident_but_wrong,
                },
                "source": source,
                "window_since": window_since.isoformat() if window_since else None,
                "commits_analyzed": commits_analyzed,
                "commits_relevant": commits_relevant,
                "candidates": candidates_out,
            }
        ),
    )
    session.add(scan)
    repo.last_scan_at = datetime.utcnow()
    session.flush()

    from sera.method.recovery import resolve_pending_recovery

    resolve_pending_recovery(session, repo, scan)

    response = {"status": status, "scan_id": scan.id, "metric_drop": drop}
    # Surface up to the top 3 commit candidates directly in the report
    # response (not just stored server-side) so a CI reporter can
    # immediately act on them -- sequential per-candidate validation,
    # without a second round-trip to fetch the ranking. top_candidate is
    # kept as the first entry for any caller that only wants one.
    commit_candidates = [c for c in candidates_out if c["kind"] == "commit"][:3]
    if commit_candidates:
        response["candidates"] = [
            {
                "commit_sha": c["commit_sha"],
                "stage_label": c.get("stage_label"),
                "files_changed": c["commit_files"],
            }
            for c in commit_candidates
        ]
        response["top_candidate"] = {
            "commit_sha": commit_candidates[0]["commit_sha"],
            "files_changed": commit_candidates[0]["commit_files"],
        }
    return response
