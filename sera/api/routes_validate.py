"""Endpoint for the cost-bounded targeted validation step: re-evaluate only
the top-ranked candidate and record the resolved case.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from sera.api import state
from sera.api.schemas import ValidationResponse
from sera.db.models import Incident
from sera.db.session import session_scope
from sera.method.memory import record_ranking, resolve_incident
from sera.method.validator import validate_top_candidate

router = APIRouter(prefix="/incidents", tags=["validate"])


@router.post("/{incident_id}/validate", response_model=ValidationResponse)
def validate_incident(incident_id: int):
    ranking = state.get_incident_ranking(incident_id)
    if not ranking:
        raise HTTPException(409, "no ranking available; call /rank first")
    top_candidate = ranking[0]

    with session_scope() as session:
        incident = session.get(Incident, incident_id)
        if incident is None:
            raise HTTPException(404, "incident not found")

        baseline_config, baseline_batch, baseline_accuracy = state.get_run_context(
            incident.baseline_run_id
        )
        regressed_config, regressed_batch, regressed_accuracy = state.get_run_context(
            incident.regressed_run_id
        )

        outcome = validate_top_candidate(
            candidate=top_candidate,
            regressed_config=regressed_config,
            baseline_config=baseline_config,
            regressed_batch=regressed_batch,
            before_accuracy=regressed_accuracy,
            baseline_accuracy=baseline_accuracy,
        )

        record_ranking(session, incident, ranking)
        resolve_incident(session, incident, outcome)

        return ValidationResponse(
            incident_id=incident_id,
            candidate_id=outcome.candidate_id,
            kind=outcome.kind,
            before_accuracy=outcome.before_accuracy,
            after_accuracy=outcome.after_accuracy,
            baseline_accuracy=outcome.baseline_accuracy,
            recovered=outcome.recovered,
            confirmed=outcome.confirmed,
        )
