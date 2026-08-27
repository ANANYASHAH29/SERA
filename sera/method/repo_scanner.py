"""B1: scans a connected repo for signals that it's a scikit-learn
tabular classifier SERA could auto-generate a canary_eval.py draft for.

Deliberately static analysis only -- filenames, text search, and AST
parsing of source code. Never downloads and executes a repo's model
artifact (e.g. via `joblib.load`) to "verify" it, and never runs any
repo's own .py files. Unpickling an untrusted .pkl/.joblib file is a
known arbitrary-code-execution vector (pickle's `__reduce__` protocol can
run anything on load) -- that would violate the exact "never execute a
stranger's code" principle this whole project is built on. So a model
artifact is detected by extension only: a plausible signal, not a
verified one. Scoped narrowly to sklearn/tabular classifiers by design;
PyTorch/TensorFlow model formats, non-tabular data, and non-classification
tasks are out of scope for this scanner (flagged, not built).
"""
from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from typing import List, Optional

from github import Github, GithubException

MODEL_EXTENSIONS = (".pkl", ".joblib")
MAX_FILES_SCANNED = 300
SKLEARN_IMPORT_RE = re.compile(r"^\s*(import sklearn\b|from sklearn\b)", re.MULTILINE)
HELD_OUT_CSV_RE = re.compile(r"(^|/)(test|val|holdout|eval)[_\-]?\w*\.csv$", re.IGNORECASE)


@dataclass
class ScanSignals:
    model_artifact_found: bool = False
    model_artifact_path: Optional[str] = None

    sklearn_import_found: bool = False
    sklearn_import_files: List[str] = field(default_factory=list)

    train_test_split_found: bool = False
    train_test_split_file: Optional[str] = None

    held_out_csv_found: bool = False
    held_out_csv_path: Optional[str] = None

    scan_truncated: bool = False  # hit MAX_FILES_SCANNED before finishing

    @property
    def held_out_set_detected(self) -> bool:
        """Either detection method counts -- an AST-visible split call, or
        a separate test/val CSV sitting alongside the code."""
        return self.train_test_split_found or self.held_out_csv_found

    @property
    def all_signals_found(self) -> bool:
        return self.model_artifact_found and self.sklearn_import_found and self.held_out_set_detected

    def missing_signals(self) -> List[str]:
        missing = []
        if not self.model_artifact_found:
            missing.append("model_artifact")
        if not self.sklearn_import_found:
            missing.append("sklearn_import")
        if not self.held_out_set_detected:
            missing.append("held_out_set")
        return missing

    def to_dict(self) -> dict:
        return {
            "model_artifact": {"found": self.model_artifact_found, "path": self.model_artifact_path},
            "sklearn_import": {"found": self.sklearn_import_found, "files": self.sklearn_import_files},
            "train_test_split": {
                "found": self.train_test_split_found,
                "file": self.train_test_split_file,
            },
            "held_out_csv": {"found": self.held_out_csv_found, "path": self.held_out_csv_path},
            "held_out_set_detected": self.held_out_set_detected,
            "all_signals_found": self.all_signals_found,
            "missing_signals": self.missing_signals(),
            "scan_truncated": self.scan_truncated,
        }


def _contains_train_test_split_call(source: str) -> bool:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name) and func.id == "train_test_split":
            return True
        if isinstance(func, ast.Attribute) and func.attr == "train_test_split":
            return True
    return False


def scan_repo_for_sklearn_signals(
    repo_full_name: str, token: Optional[str] = None, client: Optional[Github] = None
) -> ScanSignals:
    """Fetches the repo's file tree (default branch, HEAD) and inspects
    filenames + .py file contents. Read-only GitHub API calls only.
    """
    if client is not None:
        gh_client = client
    elif token:
        gh_client = Github(token)
    else:
        gh_client = Github()
    repo = gh_client.get_repo(repo_full_name)

    signals = ScanSignals()
    try:
        default_branch = repo.default_branch
        tree = repo.get_git_tree(default_branch, recursive=True)
        entries = [e for e in tree.tree if e.type == "blob"]
    except GithubException:
        signals.scan_truncated = True
        return signals

    if len(entries) > MAX_FILES_SCANNED:
        signals.scan_truncated = True
    entries = entries[:MAX_FILES_SCANNED]

    for entry in entries:
        path = entry.path

        if path.lower().endswith(MODEL_EXTENSIONS) and not signals.model_artifact_found:
            signals.model_artifact_found = True
            signals.model_artifact_path = path

        if HELD_OUT_CSV_RE.search(path) and not signals.held_out_csv_found:
            signals.held_out_csv_found = True
            signals.held_out_csv_path = path

        if path.endswith(".py"):
            try:
                content_file = repo.get_contents(path, ref=default_branch)
                source = content_file.decoded_content.decode("utf-8", errors="ignore")
            except (GithubException, UnicodeDecodeError):
                continue

            if SKLEARN_IMPORT_RE.search(source):
                signals.sklearn_import_found = True
                signals.sklearn_import_files.append(path)

            if not signals.train_test_split_found and _contains_train_test_split_call(source):
                signals.train_test_split_found = True
                signals.train_test_split_file = path

    return signals
