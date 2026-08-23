"""Shared commit representation used by both real GitHub fetches and the
synthetic commit-history generator, so the ranker never has to know which
one it's looking at.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional


@dataclass
class CommitInfo:
    sha: str
    message: str
    author: str
    timestamp: datetime
    files_changed: List[str] = field(default_factory=list)
    pr_number: Optional[int] = None
    pr_html_url: Optional[str] = None
    # filled in by diff_analyzer.classify_commit
    risk_categories: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "sha": self.sha,
            "message": self.message,
            "author": self.author,
            "timestamp": self.timestamp.isoformat(),
            "files_changed": self.files_changed,
            "pr_number": self.pr_number,
            "pr_html_url": self.pr_html_url,
            "risk_categories": self.risk_categories,
        }
