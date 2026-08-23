"""Wires the 5 pipeline stages together into a single callable run."""
from __future__ import annotations

from sera.config import PipelineConfig
from sera.pipeline.evaluation import RunMetrics, evaluate_predictions
from sera.pipeline.ingestion import CanaryBatch, inject_corruption_leak, validate_batch
from sera.pipeline.inference import run_inference
from sera.pipeline.input_prep import to_tensor
from sera.pipeline.preprocessing import preprocess_batch


def run_pipeline(config: PipelineConfig, batch: CanaryBatch, corruption_seed: int = 0) -> RunMetrics:
    """Run ingestion validation -> preprocessing -> input prep -> inference -> evaluation.

    `batch` is passed in already-loaded (and possibly already covariate-shifted
    by the caller for D1) so this function only applies pipeline-code-level
    effects: F4's corruption leak (a data-quality-filter config), F1's resize,
    F3's normalization, F2's channel order, and F5's checkpoint choice.
    """
    validate_batch(batch)

    working_batch = batch
    if not config.corruption_filter_enabled or config.corruption_injection_rate > 0:
        working_batch = inject_corruption_leak(
            batch,
            rate=config.corruption_injection_rate,
            severity=config.corruption_injection_severity,
            seed=corruption_seed,
        )

    preprocessed = preprocess_batch(working_batch.images, config)
    tensor = to_tensor(preprocessed, config)
    probs = run_inference(tensor, config)
    return evaluate_predictions(probs, working_batch.labels)
