"""Cost-bounded targeted validation.

Only the single top-ranked candidate gets a full, expensive isolated
re-evaluation -- a second in-process PipelineConfig, with either the
candidate's change reverted (commit hypothesis) or nothing changed (drift
hypothesis, since there is no code to revert), re-run against the SAME
canary images the regressed run saw.

For a commit hypothesis: reverting the one PipelineConfig field(s) that
condition touches and recovering accuracy CONFIRMS the commit caused it.
For the drift hypothesis: running the untouched baseline config against
the same (possibly still-shifted) images and accuracy staying low CONFIRMS
drift, since no config change could have explained the regression.
"""
from __future__ import annotations

from dataclasses import dataclass, replace

from sera.config import PipelineConfig
from sera.conditions.registry import CONDITION_FIELDS
from sera.method.ranker import RankedCandidate
from sera.pipeline.ingestion import CanaryBatch

DEFAULT_RECOVERY_THRESHOLD = 0.05  # accuracy must be within 5pp of baseline to count as "recovered"


@dataclass
class ValidationOutcome:
    candidate_id: str
    kind: str
    before_accuracy: float
    after_accuracy: float
    baseline_accuracy: float
    recovered: bool
    confirmed: bool
    recovery_threshold: float
    num_reevaluations: int = 1


def _reverted_config(
    regressed_config: PipelineConfig, baseline_config: PipelineConfig, category: str
) -> PipelineConfig:
    fields = CONDITION_FIELDS[category]
    return replace(regressed_config, **{f: getattr(baseline_config, f) for f in fields})


def validate_top_candidate(
    candidate: RankedCandidate,
    regressed_config: PipelineConfig,
    baseline_config: PipelineConfig,
    regressed_batch: CanaryBatch,
    before_accuracy: float,
    baseline_accuracy: float,
    recovery_threshold: float = DEFAULT_RECOVERY_THRESHOLD,
) -> ValidationOutcome:
    from sera.pipeline.runner import run_pipeline

    if candidate.kind == "commit" and candidate.hypothesized_category in CONDITION_FIELDS:
        test_config = _reverted_config(
            regressed_config, baseline_config, candidate.hypothesized_category
        )
    elif candidate.kind == "commit":
        # commit touches no known risk category -- nothing to revert.
        test_config = regressed_config
    else:  # drift candidate: no code to revert, re-run the clean baseline config
        test_config = baseline_config

    result = run_pipeline(test_config, regressed_batch)
    after_accuracy = result.accuracy
    recovered = (baseline_accuracy - after_accuracy) <= recovery_threshold

    confirmed = recovered if candidate.kind == "commit" else (not recovered)

    return ValidationOutcome(
        candidate_id=candidate.candidate_id,
        kind=candidate.kind,
        before_accuracy=before_accuracy,
        after_accuracy=after_accuracy,
        baseline_accuracy=baseline_accuracy,
        recovered=recovered,
        confirmed=confirmed,
        recovery_threshold=recovery_threshold,
    )
