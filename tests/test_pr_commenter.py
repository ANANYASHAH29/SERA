from datetime import date

from sera.github_integration.pr_commenter import format_comment


def test_format_comment_includes_accuracy_and_evidence():
    body = format_comment(
        before_accuracy=0.92,
        after_accuracy=0.65,
        detected_date=date(2026, 8, 22),
        evidence=["diff touches preprocessing_config.yaml", "confidence collapsed broadly"],
    )
    assert "92%" in body
    assert "65%" in body
    assert "2026-08-22" in body
    assert "diff touches preprocessing_config.yaml" in body
    assert "confidence collapsed broadly" in body
