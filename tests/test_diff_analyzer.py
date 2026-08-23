from datetime import datetime

from sera.github_integration.commit_types import CommitInfo
from sera.github_integration.diff_analyzer import classify_commit, classify_commits, classify_files


def test_classify_files_maps_preprocessing_config_to_f3_only():
    # preprocessing_config.yaml is F3's (normalization) pattern. F1 (resize)
    # deliberately uses a distinct "resize_config" pattern so a single file
    # can't ambiguously match both categories.
    cats = classify_files(["config/preprocessing_config.yaml"])
    assert cats == ["F3"]


def test_classify_files_maps_resize_config_to_f1_only():
    cats = classify_files(["config/resize_config.yaml"])
    assert cats == ["F1"]


def test_classify_files_maps_checkpoint_to_f5():
    cats = classify_files(["registry/model_checkpoint_pointer.txt"])
    assert cats == ["F5"]


def test_classify_files_harmless_file_yields_no_category():
    cats = classify_files(["README.md", "utils/logging.py"])
    assert cats == []


def test_classify_commit_fills_risk_categories_in_place():
    commit = CommitInfo(
        sha="abc123",
        message="bump channel_order handling",
        author="alice",
        timestamp=datetime.utcnow(),
        files_changed=["input_prep/channel_order.py"],
    )
    classify_commit(commit)
    assert commit.risk_categories == ["F2"]


def test_classify_commits_batch():
    commits = [
        CommitInfo("s1", "m1", "a", datetime.utcnow(), ["README.md"]),
        CommitInfo("s2", "m2", "a", datetime.utcnow(), ["ingestion_validation.py"]),
    ]
    classify_commits(commits)
    assert commits[0].risk_categories == []
    assert commits[1].risk_categories == ["F4"]
