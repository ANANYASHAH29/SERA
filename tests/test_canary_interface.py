import json
import textwrap

import numpy as np
import pytest

from sera.canary_interface import (
    CanaryEvalResult,
    run_subprocess_canary_eval,
    to_run_metrics,
)
from tests.conftest import requires_checkpoint


def test_canary_eval_result_from_dict_requires_fields():
    with pytest.raises(ValueError):
        CanaryEvalResult.from_dict({"accuracy": 0.9})


def test_canary_eval_result_from_dict_parses_valid_payload():
    result = CanaryEvalResult.from_dict(
        {
            "accuracy": 0.83,
            "mean_confidence": 0.79,
            "mean_entropy": 0.41,
            "per_sample_confidence": [0.9, 0.4],
            "per_sample_correct": [True, False],
        }
    )
    assert result.accuracy == 0.83
    assert result.per_sample_correct == [True, False]


def test_to_run_metrics_adapts_confidence_and_correctness():
    result = CanaryEvalResult(
        accuracy=0.75,
        mean_confidence=0.7,
        mean_entropy=0.5,
        per_sample_confidence=[0.9, 0.2, 0.6],
        per_sample_correct=[True, False, True],
    )
    metrics = to_run_metrics(result)
    assert metrics.accuracy == 0.75
    assert list(metrics.per_image_confidence) == [0.9, 0.2, 0.6]
    assert list(metrics.per_image_correct) == [True, False, True]


def test_run_subprocess_canary_eval_parses_last_json_line(tmp_path):
    script = tmp_path / "fake_canary.py"
    script.write_text(
        textwrap.dedent(
            """
            import json
            print("some noisy log line that isn't JSON")
            print(json.dumps({
                "accuracy": 0.5,
                "mean_confidence": 0.6,
                "mean_entropy": 0.3,
                "per_sample_confidence": [0.5, 0.7],
                "per_sample_correct": [True, True]
            }))
            """
        )
    )
    result = run_subprocess_canary_eval(str(script))
    assert result.accuracy == 0.5
    assert result.per_sample_correct == [True, True]


def test_run_subprocess_canary_eval_raises_on_nonzero_exit(tmp_path):
    script = tmp_path / "broken.py"
    script.write_text("import sys; sys.exit(1)")
    with pytest.raises(RuntimeError, match="exited 1"):
        run_subprocess_canary_eval(str(script))


def test_run_subprocess_canary_eval_raises_on_invalid_json(tmp_path):
    script = tmp_path / "bad_output.py"
    script.write_text("print('not json')")
    with pytest.raises(RuntimeError, match="valid JSON"):
        run_subprocess_canary_eval(str(script))


@requires_checkpoint
def test_reference_cifar10_canary_eval_matches_pipeline_directly():
    from sera.canary_interface import reference_cifar10_canary_eval
    from sera.config import baseline_config
    from sera.pipeline.ingestion import build_canary_set
    from sera.pipeline.runner import run_pipeline

    result = reference_cifar10_canary_eval()
    direct = run_pipeline(baseline_config(), build_canary_set())
    assert result.accuracy == pytest.approx(direct.accuracy)
    assert len(result.per_sample_confidence) == len(direct.per_image_confidence)
