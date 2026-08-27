"""B2: generates a draft canary_eval.py for a detected scikit-learn
classifier + held-out set. Output is a reviewable draft ONLY -- this
module never executes the generated code, and neither does anything that
calls it. The repo owner reviews it, edits paths if needed, and runs it
themselves (locally or in their own CI) -- consistent with "never
auto-execute a stranger's code" everywhere else in this project.
"""
from __future__ import annotations

from sera.method.repo_scanner import ScanSignals

DRAFT_TEMPLATE = '''"""Auto-generated draft by SERA's repo scanner. Review before running --
this is a starting point, not a verified-correct script. Edit the model
path, test-set path, and label column name below if they're wrong for
your repo.
"""
import hashlib
import json

import joblib
import numpy as np
import pandas as pd

MODEL_PATH = "{model_path}"
TEST_SET_PATH = "{test_set_path}"
LABEL_COLUMN = "label"  # EDIT if your held-out CSV uses a different column name


def shannon_entropy(probs: np.ndarray) -> np.ndarray:
    eps = 1e-12
    return -(probs * np.log(probs + eps)).sum(axis=1)


def main():
    model = joblib.load(MODEL_PATH)

    with open(TEST_SET_PATH, "rb") as f:
        raw_bytes = f.read()
    canary_set_hash = hashlib.sha256(raw_bytes).hexdigest()

    test_df = pd.read_csv(TEST_SET_PATH)
    y_test = test_df[LABEL_COLUMN].values
    X_test = test_df.drop(columns=[LABEL_COLUMN]).values

    predictions = model.predict(X_test)
    probabilities = model.predict_proba(X_test)

    per_sample_correct = (predictions == y_test)
    per_sample_confidence = probabilities.max(axis=1)
    per_sample_entropy = shannon_entropy(probabilities)

    accuracy = float(per_sample_correct.mean())
    mean_confidence = float(per_sample_confidence.mean())
    mean_entropy = float(per_sample_entropy.mean())

    result = {{
        "task_type": "classification",
        "primary_metric": accuracy,
        "primary_metric_name": "accuracy",
        "secondary_metrics": {{
            "mean_confidence": mean_confidence,
            "mean_entropy": mean_entropy,
        }},
        "per_sample_scores": [int(x) for x in per_sample_correct],
        "n_samples": len(y_test),
        "canary_set_hash": canary_set_hash,
    }}

    print(json.dumps(result))


if __name__ == "__main__":
    main()
'''


def generate_canary_draft(signals: ScanSignals) -> str:
    """Requires all three signals to have been found -- callers should
    check `signals.all_signals_found` first (see routes_generic_scan.py,
    which returns 409 with the missing list instead of calling this).
    """
    if not signals.all_signals_found:
        raise ValueError(f"missing signals: {signals.missing_signals()}")

    test_set_path = signals.held_out_csv_path or "test_set.csv"
    return DRAFT_TEMPLATE.format(
        model_path=signals.model_artifact_path,
        test_set_path=test_set_path,
    )
