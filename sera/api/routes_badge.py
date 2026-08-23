"""Dynamic status badge, in the shields.io/Codecov/DeepSource style, for
embedding in a repo's README: `![SERA status](.../badge/owner/repo)`.

Looked up by repo_full_name alone (not by user_id) -- a badge URL is
meant to be publicly embeddable in a README without auth, same as every
other CI badge. If the same repo_full_name were ever connected by more
than one SERA user (a fork scenario), this shows whichever connection
was scanned most recently; that's a documented simplification, not a
tenant-isolation gap, since badges only ever expose a coarse
healthy/incident/pending status, never incident details or commit data.
"""
from __future__ import annotations

from fastapi import APIRouter, Response

from sera.db.models import ConnectedRepo, ScanResult
from sera.db.session import session_scope

router = APIRouter(tags=["badge"])

COLORS = {
    "healthy": "#2da44e",
    "incident": "#cf222e",
    "pending": "#9a6700",
    "never_scanned": "#6e7781",
}

LABELS = {
    "healthy": "healthy",
    "incident": "regression detected",
    "pending": "scan pending",
    "never_scanned": "not yet scanned",
}


def _svg(status_text: str, color: str) -> str:
    label = "sera"
    label_width = 34
    status_width = 12 + len(status_text) * 6
    total_width = label_width + status_width

    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{total_width}" height="20">
  <linearGradient id="s" x2="0" y2="100%">
    <stop offset="0" stop-color="#bbb" stop-opacity=".1"/>
    <stop offset="1" stop-opacity=".1"/>
  </linearGradient>
  <clipPath id="r"><rect width="{total_width}" height="20" rx="3" fill="#fff"/></clipPath>
  <g clip-path="url(#r)">
    <rect width="{label_width}" height="20" fill="#555"/>
    <rect x="{label_width}" width="{status_width}" height="20" fill="{color}"/>
    <rect width="{total_width}" height="20" fill="url(#s)"/>
  </g>
  <g fill="#fff" text-anchor="middle" font-family="Verdana,Geneva,sans-serif" font-size="11">
    <text x="{label_width / 2}" y="14">{label}</text>
    <text x="{label_width + status_width / 2}" y="14">{status_text}</text>
  </g>
</svg>"""


@router.get("/badge/{owner}/{repo}")
def get_badge(owner: str, repo: str):
    repo_full_name = f"{owner}/{repo}"
    with session_scope() as session:
        connected = (
            session.query(ConnectedRepo)
            .filter_by(repo_full_name=repo_full_name)
            .order_by(ConnectedRepo.connected_at.desc())
            .first()
        )
        if connected is None:
            status = "never_scanned"
        else:
            latest_scan = (
                session.query(ScanResult)
                .filter_by(repo_id=connected.id)
                .order_by(ScanResult.created_at.desc())
                .first()
            )
            status = latest_scan.status if latest_scan else "never_scanned"

    color = COLORS.get(status, COLORS["never_scanned"])
    label = LABELS.get(status, status)
    svg = _svg(label, color)
    return Response(
        content=svg,
        media_type="image/svg+xml",
        headers={"Cache-Control": "no-cache, max-age=0"},
    )
