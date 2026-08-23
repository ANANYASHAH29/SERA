"""Pluggable canary-evaluation interface.

SERA's diagnostic logic (evidence_signals, ranker, validator) only ever
consumes a `sera.pipeline.evaluation.RunMetrics` -- it doesn't care how
that metrics object was produced. The CIFAR-10/ResNet-18 pipeline is the
*reference implementation* of "run a canary eval", not the only possible
one. A different repo can plug in its own inference code two ways:

  1. Subprocess contract: point `.sera.yml`'s `canary.entrypoint` at a
     script that, when run, prints one JSON object as its LAST line of
     stdout with fields matching `CanaryEvalResult` (see the module
     docstring example below). `run_subprocess_canary_eval` runs it and
     parses that line. This is the contract external repos implement --
     any language, as long as it can print JSON.

  2. In-process callable: implement a zero-argument Python callable
     returning a `CanaryEvalResult` directly (see `CanaryEvaluator`).

Either way, `to_run_metrics` adapts the generic result into the exact
`RunMetrics` shape `compute_shape_features` and the ranker already expect
-- this file never touches that core logic, it only feeds it.

Expected JSON from a subprocess entrypoint:

    {
      "accuracy": 0.83,
      "mean_confidence": 0.79,
      "mean_entropy": 0.41,
      "per_sample_confidence": [0.91, 0.44, ...],
      "per_sample_correct": [true, false, ...]
    }

`per_sample_correct` is required, not optional: without it SERA can't
tell which images flipped from correct to wrong, which is exactly the
signal `confident_but_wrong` (genuine-drift detection) depends on.
"""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Protocol

import numpy as np


@dataclass
class CanaryEvalResult:
    accuracy: float
    mean_confidence: float
    mean_entropy: float
    per_sample_confidence: List[float]
    per_sample_correct: List[bool]

    @staticmethod
    def from_dict(d: dict) -> "CanaryEvalResult":
        missing = [k for k in ("accuracy", "mean_confidence", "per_sample_confidence", "per_sample_correct") if k not in d]
        if missing:
            raise ValueError(f"canary eval JSON is missing required field(s): {missing}")
        return CanaryEvalResult(
            accuracy=float(d["accuracy"]),
            mean_confidence=float(d["mean_confidence"]),
            mean_entropy=float(d.get("mean_entropy", 0.0)),
            per_sample_confidence=[float(x) for x in d["per_sample_confidence"]],
            per_sample_correct=[bool(x) for x in d["per_sample_correct"]],
        )


class CanaryEvaluator(Protocol):
    def __call__(self) -> CanaryEvalResult: ...


def run_subprocess_canary_eval(
    entrypoint: str, cwd: Optional[Path] = None, timeout: int = 900
) -> CanaryEvalResult:
    """Runs `entrypoint` as a subprocess and parses the last line of its
    stdout as the CanaryEvalResult JSON. `.py` scripts are run with the
    current interpreter; anything else is executed directly (so a repo
    can point this at a shell script, a compiled binary, etc.).
    """
    command = ["python", entrypoint] if entrypoint.endswith(".py") else [entrypoint]
    proc = subprocess.run(
        command,
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"canary entrypoint {entrypoint!r} exited {proc.returncode}:\n{proc.stderr[-4000:]}"
        )
    lines = [line for line in proc.stdout.strip().splitlines() if line.strip()]
    if not lines:
        raise RuntimeError(f"canary entrypoint {entrypoint!r} produced no stdout")
    try:
        data = json.loads(lines[-1])
    except json.JSONDecodeError as e:
        raise RuntimeError(
            f"canary entrypoint {entrypoint!r} did not print valid JSON on its last line: {e}\n"
            f"last line was: {lines[-1][:500]!r}"
        )
    return CanaryEvalResult.from_dict(data)


def reference_cifar10_canary_eval(config=None) -> CanaryEvalResult:
    """The built-in reference implementation: runs SERA's own ResNet-18 /
    CIFAR-10 pipeline. Used whenever a repo doesn't declare its own
    `canary.entrypoint` in `.sera.yml` -- keeps the existing demo working
    exactly as before this module existed.
    """
    from sera.config import baseline_config
    from sera.pipeline.ingestion import build_canary_set
    from sera.pipeline.runner import run_pipeline

    cfg = config or baseline_config()
    batch = build_canary_set()
    metrics = run_pipeline(cfg, batch)
    return CanaryEvalResult(
        accuracy=metrics.accuracy,
        mean_confidence=metrics.mean_confidence,
        mean_entropy=metrics.mean_entropy,
        per_sample_confidence=metrics.per_image_confidence.tolist(),
        per_sample_correct=metrics.per_image_correct.tolist(),
    )


def to_run_metrics(result: CanaryEvalResult):
    """Adapts a generic CanaryEvalResult into the RunMetrics shape the
    frozen core (evidence_signals.compute_shape_features, the ranker,
    the validator) already consumes. Predictions aren't reconstructable
    from this generic contract and aren't needed downstream, so they're
    left as zeros.
    """
    from sera.pipeline.evaluation import RunMetrics

    confidence = np.array(result.per_sample_confidence, dtype=float)
    correct = np.array(result.per_sample_correct, dtype=bool)
    if result.mean_entropy:
        entropy = np.full_like(confidence, result.mean_entropy)
    else:
        entropy = np.zeros_like(confidence)

    return RunMetrics(
        accuracy=result.accuracy,
        mean_confidence=result.mean_confidence,
        mean_entropy=result.mean_entropy,
        per_image_confidence=confidence,
        per_image_entropy=entropy,
        per_image_correct=correct,
        predictions=np.zeros(len(confidence), dtype=int),
    )
