"""Reference implementation of the subprocess canary-evaluation contract
(see sera/canary_interface.py). Runs SERA's own CIFAR-10/ResNet-18
pipeline and prints one JSON object as the last line of stdout.

Any repo can model its own canary entrypoint on this file: load your
labeled canary set, run your inference code, and print the same JSON
shape. SERA's PR bot and scheduled-run scripts run this exact script for
SERA's own repo (declared in .sera.yml's `canary.entrypoint`) -- it's not
just an example, it's what SERA uses on itself.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sera.canary_interface import reference_cifar10_canary_eval


def main():
    result = reference_cifar10_canary_eval()
    print(
        json.dumps(
            {
                "accuracy": result.accuracy,
                "mean_confidence": result.mean_confidence,
                "mean_entropy": result.mean_entropy,
                "per_sample_confidence": result.per_sample_confidence,
                "per_sample_correct": result.per_sample_correct,
            }
        )
    )


if __name__ == "__main__":
    main()
