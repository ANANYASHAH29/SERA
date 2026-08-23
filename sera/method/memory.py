"""SQLite-backed case memory: stores resolved incidents (symptom evidence,
confirmed cause, validation result) and exposes a simple historical prior
so past cases can inform future ranking (e.g. "in this repo, regressions
have historically been drift 30% of the time").
"""
from __future__ import annotations

import json
from typing import List, Optional

from sera.db.models import Candidate, Case, Incident, Run, ValidationResult
from sera.db.session import session_scope
from sera.method.ranker import RankedCandidate
from sera.method.validator import ValidationOutcome
from sera.pipeline.evaluation import RunMetrics


def record_run(session, config, metrics: RunMetrics, seed: Optional[int], is_baseline: bool) -> Run:
    run = Run(
        seed=seed,
        is_baseline=is_baseline,
        config_json=json.dumps(config.field_dict()),
        accuracy=metrics.accuracy,
        mean_confidence=metrics.mean_confidence,
        mean_entropy=metrics.mean_entropy,
    )
    session.add(run)
    session.flush()
    return run


def record_incident(
    session,
    baseline_run: Run,
    regressed_run: Run,
    injected_condition: Optional[str] = None,
    repo_full_name: Optional[str] = None,
) -> Incident:
    incident = Incident(
        baseline_run_id=baseline_run.id,
        regressed_run_id=regressed_run.id,
        accuracy_drop=baseline_run.accuracy - regressed_run.accuracy,
        injected_condition=injected_condition,
        repo_full_name=repo_full_name,
    )
    session.add(incident)
    session.flush()
    return incident


def record_ranking(session, incident: Incident, ranked: List[RankedCandidate]) -> None:
    for i, cand in enumerate(ranked):
        session.add(
            Candidate(
                incident_id=incident.id,
                candidate_id=cand.candidate_id,
                kind=cand.kind,
                hypothesized_category=cand.hypothesized_category,
                provenance_score=cand.provenance_score,
                shape_match_score=cand.shape_match_score,
                combined_score=cand.combined_score,
                rank=i,
            )
        )


def resolve_incident(session, incident: Incident, validation: ValidationOutcome) -> Case:
    session.add(
        ValidationResult(
            incident_id=incident.id,
            candidate_id=validation.candidate_id,
            before_accuracy=validation.before_accuracy,
            after_accuracy=validation.after_accuracy,
            baseline_accuracy=validation.baseline_accuracy,
            recovered=validation.recovered,
            confirmed=validation.confirmed,
            recovery_threshold=validation.recovery_threshold,
        )
    )
    incident.status = "validated"

    confirmed_cause = validation.candidate_id if validation.confirmed else "unresolved"
    case = Case(
        incident_id=incident.id,
        confirmed_cause=confirmed_cause,
        category=incident.injected_condition,
        evidence_json=json.dumps(
            {
                "before_accuracy": validation.before_accuracy,
                "after_accuracy": validation.after_accuracy,
                "confirmed": validation.confirmed,
            }
        ),
    )
    session.add(case)
    session.flush()
    return case


def historical_drift_rate(session, repo_full_name: Optional[str] = None, default: float = 0.35) -> float:
    """Fraction of past validated incidents whose confirmed cause was drift.

    Falls back to `default` when there isn't enough history yet (fewer
    than 5 resolved cases), so a cold-start database doesn't bias ranking.
    """
    query = session.query(Case).join(Incident)
    if repo_full_name:
        query = query.filter(Incident.repo_full_name == repo_full_name)
    cases = query.all()
    if len(cases) < 5:
        return default
    drift_count = sum(1 for c in cases if c.confirmed_cause == "__no_commit_drift__")
    return drift_count / len(cases)
