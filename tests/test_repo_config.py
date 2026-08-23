from sera.github_integration.diff_analyzer import classify_files
from sera.repo_config import _normalize_category_key, _parse_config_text, load_repo_config_from_path

SAMPLE_YAML = """
risk_categories:
  F1_resize:
    - "config/preprocessing.yaml"
    - "**/resize_params.py"
  F3_normalization:
    - "config/normalize_constants.py"
  F5_checkpoint:
    - "models/*.checkpoint_ref"
  not_a_category:
    - "some/file.py"
canary:
  entrypoint: "canary_eval.py"
"""


def test_normalize_category_key_variants():
    assert _normalize_category_key("F1_resize") == "F1"
    assert _normalize_category_key("F1-resize") == "F1"
    assert _normalize_category_key("F1") == "F1"
    assert _normalize_category_key("D1_drift") == "D1"


def test_normalize_category_key_rejects_unrecognized():
    assert _normalize_category_key("not_a_category") is None
    assert _normalize_category_key("") is None


def test_parse_config_text_extracts_patterns_and_entrypoint():
    cfg = _parse_config_text(SAMPLE_YAML)
    assert cfg.risk_patterns["F1"] == ["config/preprocessing.yaml", "**/resize_params.py"]
    assert cfg.risk_patterns["F3"] == ["config/normalize_constants.py"]
    assert cfg.risk_patterns["F5"] == ["models/*.checkpoint_ref"]
    assert "not_a_category" not in cfg.risk_patterns  # unrecognized key dropped, not crashed on
    assert cfg.canary_entrypoint == "canary_eval.py"


def test_load_repo_config_from_path_returns_none_when_absent(tmp_path):
    assert load_repo_config_from_path(tmp_path) is None


def test_load_repo_config_from_path_reads_real_file(tmp_path):
    (tmp_path / ".sera.yml").write_text(SAMPLE_YAML)
    cfg = load_repo_config_from_path(tmp_path)
    assert cfg is not None
    assert cfg.risk_patterns["F1"] == ["config/preprocessing.yaml", "**/resize_params.py"]
    assert cfg.source == f"path:{tmp_path / '.sera.yml'}"


def test_classify_files_uses_repo_config_glob_patterns_when_given():
    cfg = _parse_config_text(SAMPLE_YAML)
    # "models/*.checkpoint_ref" is root-anchored (no leading "**/"), so it
    # matches a file directly under models/, not arbitrarily nested -- glob
    # matching here is plain fnmatch, not gitignore-style implicit anywhere
    # matching, so patterns must opt into "**/..." for that.
    cats = classify_files(["models/resnet.checkpoint_ref"], repo_config=cfg)
    assert cats == ["F5"]


def test_classify_files_root_anchored_pattern_does_not_match_nested_path():
    cfg = _parse_config_text(SAMPLE_YAML)
    cats = classify_files(["src/models/resnet.checkpoint_ref"], repo_config=cfg)
    assert cats == []


def test_classify_files_glob_does_not_match_unrelated_files():
    cfg = _parse_config_text(SAMPLE_YAML)
    cats = classify_files(["README.md", "utils/logging.py"], repo_config=cfg)
    assert cats == []


def test_classify_files_falls_back_to_builtin_patterns_without_repo_config():
    # unchanged behavior when no .sera.yml is present, per README guarantee
    cats = classify_files(["config/resize_config.yaml"])
    assert cats == ["F1"]


def test_classify_files_double_star_glob_matches_nested_paths():
    cfg = _parse_config_text(SAMPLE_YAML)
    cats = classify_files(["a/b/c/resize_params.py"], repo_config=cfg)
    assert cats == ["F1"]
