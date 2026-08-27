import pytest

from sera.method.canary_draft_generator import generate_canary_draft
from sera.method.repo_scanner import ScanSignals


def test_generate_canary_draft_requires_all_signals():
    incomplete = ScanSignals(model_artifact_found=True)
    with pytest.raises(ValueError, match="missing signals"):
        generate_canary_draft(incomplete)


def test_generate_canary_draft_substitutes_detected_paths():
    signals = ScanSignals(
        model_artifact_found=True,
        model_artifact_path="artifacts/my_model.joblib",
        sklearn_import_found=True,
        held_out_csv_found=True,
        held_out_csv_path="data/holdout.csv",
    )
    draft = generate_canary_draft(signals)
    assert 'MODEL_PATH = "artifacts/my_model.joblib"' in draft
    assert 'TEST_SET_PATH = "data/holdout.csv"' in draft


def test_generate_canary_draft_falls_back_to_default_test_set_name():
    signals = ScanSignals(
        model_artifact_found=True,
        model_artifact_path="model.pkl",
        sklearn_import_found=True,
        train_test_split_found=True,  # held out via AST detection, no CSV path
    )
    draft = generate_canary_draft(signals)
    assert 'TEST_SET_PATH = "test_set.csv"' in draft


def test_generate_canary_draft_is_syntactically_valid_python():
    signals = ScanSignals(
        model_artifact_found=True,
        model_artifact_path="model.pkl",
        sklearn_import_found=True,
        held_out_csv_found=True,
        held_out_csv_path="test_set.csv",
    )
    draft = generate_canary_draft(signals)
    compile(draft, "<draft>", "exec")  # raises SyntaxError if malformed
