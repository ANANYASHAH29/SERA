"""Regression test for a real bug found while manually validating
scripts/pr_check.py against SERA's own repo: evaluate_at_ref restored the
original commit's bare SHA instead of the branch name, which left the
repo in detached HEAD after every call -- silently detaching whatever
branch the caller had checked out. Uses a throwaway local git repo, not
SERA's own, so it's safe to run in any environment/order.
"""
import textwrap

import pytest

from scripts.pr_check import evaluate_at_ref


def _make_repo_with_two_commits(tmp_path):
    import git

    repo = git.Repo.init(tmp_path)
    with repo.config_writer() as cw:
        cw.set_value("user", "name", "test")
        cw.set_value("user", "email", "test@example.com")

    entrypoint = tmp_path / "canary_eval.py"
    entrypoint.write_text(
        textwrap.dedent(
            """
            import json
            print(json.dumps({
                "accuracy": 0.9,
                "mean_confidence": 0.85,
                "mean_entropy": 0.2,
                "per_sample_confidence": [0.9],
                "per_sample_correct": [True]
            }))
            """
        )
    )
    (tmp_path / ".sera.yml").write_text('canary:\n  entrypoint: "canary_eval.py"\n')
    repo.index.add(["canary_eval.py", ".sera.yml"])
    first_commit = repo.index.commit("initial")

    (tmp_path / "other_file.txt").write_text("hello")
    repo.index.add(["other_file.txt"])
    repo.index.commit("second")

    return repo, first_commit.hexsha


def test_evaluate_at_ref_restores_original_branch_not_detached_head(tmp_path):
    repo, first_sha = _make_repo_with_two_commits(tmp_path)
    assert not repo.head.is_detached
    original_branch = repo.active_branch.name

    result = evaluate_at_ref(tmp_path, first_sha)

    assert result.accuracy == 0.9
    assert not repo.head.is_detached
    assert repo.active_branch.name == original_branch


def test_evaluate_at_ref_refuses_dirty_working_tree(tmp_path):
    repo, first_sha = _make_repo_with_two_commits(tmp_path)
    (tmp_path / "other_file.txt").write_text("uncommitted change")

    with pytest.raises(RuntimeError, match="uncommitted changes"):
        evaluate_at_ref(tmp_path, first_sha)
