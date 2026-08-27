"""B1 tests: the real acceptance test against the live demo-fraud-model
repo (network-dependent, skipped if unreachable), plus fast unit tests
for the AST/regex detection logic in isolation.
"""
import pytest

from sera.method.repo_scanner import ScanSignals, _contains_train_test_split_call


def test_contains_train_test_split_call_detects_direct_call():
    source = "from sklearn.model_selection import train_test_split\nX_train, X_test = train_test_split(X, y)\n"
    assert _contains_train_test_split_call(source) is True


def test_contains_train_test_split_call_detects_attribute_call():
    source = "import sklearn.model_selection as ms\nX_train, X_test = ms.train_test_split(X, y)\n"
    assert _contains_train_test_split_call(source) is True


def test_contains_train_test_split_call_false_when_absent():
    source = "def foo():\n    return 1\n"
    assert _contains_train_test_split_call(source) is False


def test_contains_train_test_split_call_handles_syntax_errors_gracefully():
    assert _contains_train_test_split_call("this is not ) python (") is False


def test_scan_signals_all_found_requires_all_three():
    signals = ScanSignals(model_artifact_found=True, sklearn_import_found=True, train_test_split_found=False, held_out_csv_found=False)
    assert signals.all_signals_found is False
    assert signals.missing_signals() == ["held_out_set"]


def test_scan_signals_held_out_set_accepts_either_detection_method():
    via_csv = ScanSignals(model_artifact_found=True, sklearn_import_found=True, held_out_csv_found=True)
    via_ast = ScanSignals(model_artifact_found=True, sklearn_import_found=True, train_test_split_found=True)
    assert via_csv.all_signals_found is True
    assert via_ast.all_signals_found is True


def test_scan_signals_missing_lists_every_gap():
    signals = ScanSignals()
    assert signals.missing_signals() == ["model_artifact", "sklearn_import", "held_out_set"]


@pytest.mark.network
def test_scanner_finds_all_signals_in_real_demo_fraud_model_repo():
    from sera.method.repo_scanner import scan_repo_for_sklearn_signals

    try:
        signals = scan_repo_for_sklearn_signals("ANANYASHAH29/Fraud-detection")
    except Exception as e:
        pytest.skip(f"network/GitHub API unavailable: {e}")

    assert signals.model_artifact_found is True
    assert signals.model_artifact_path == "model.pkl"
    assert signals.sklearn_import_found is True
    assert signals.train_test_split_found is True
    assert signals.held_out_csv_found is True
    assert signals.all_signals_found is True
