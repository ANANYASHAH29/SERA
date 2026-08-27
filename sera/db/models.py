"""SQLAlchemy models: runs, incidents, ranked candidates, validation
results, and resolved cases (the "case memory").
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


def utcnow() -> dt.datetime:
    return dt.datetime.utcnow()


class Run(Base):
    __tablename__ = "runs"

    id = Column(Integer, primary_key=True)
    created_at = Column(DateTime, default=utcnow)
    seed = Column(Integer, nullable=True)
    is_baseline = Column(Boolean, default=False)
    config_json = Column(Text)
    accuracy = Column(Float)
    mean_confidence = Column(Float)
    mean_entropy = Column(Float)


class Incident(Base):
    __tablename__ = "incidents"

    id = Column(Integer, primary_key=True)
    created_at = Column(DateTime, default=utcnow)
    baseline_run_id = Column(Integer, ForeignKey("runs.id"))
    regressed_run_id = Column(Integer, ForeignKey("runs.id"))
    accuracy_drop = Column(Float)
    injected_condition = Column(String, nullable=True)  # ground truth, experiments only
    repo_full_name = Column(String, nullable=True)
    # nullable: single-tenant/demo incidents (Phase 1-2) have no tenant owner.
    # Multi-tenant incidents (Phase 3) always set this -- every tenant-scoped
    # query filters on it, see sera/method/tenancy.py.
    connected_repo_id = Column(Integer, ForeignKey("connected_repos.id"), nullable=True)
    status = Column(String, default="open")  # open | validated

    baseline_run = relationship("Run", foreign_keys=[baseline_run_id])
    regressed_run = relationship("Run", foreign_keys=[regressed_run_id])
    candidates = relationship("Candidate", back_populates="incident")
    validations = relationship("ValidationResult", back_populates="incident")
    connected_repo = relationship("ConnectedRepo", back_populates="incidents")


class Candidate(Base):
    __tablename__ = "candidates"

    id = Column(Integer, primary_key=True)
    incident_id = Column(Integer, ForeignKey("incidents.id"))
    candidate_id = Column(String)  # commit sha or the no-commit sentinel
    kind = Column(String)  # "commit" | "drift"
    hypothesized_category = Column(String, nullable=True)
    provenance_score = Column(Float)
    shape_match_score = Column(Float)
    combined_score = Column(Float)
    rank = Column(Integer)

    incident = relationship("Incident", back_populates="candidates")


class ValidationResult(Base):
    __tablename__ = "validation_results"

    id = Column(Integer, primary_key=True)
    incident_id = Column(Integer, ForeignKey("incidents.id"))
    candidate_id = Column(String)
    before_accuracy = Column(Float)
    after_accuracy = Column(Float)
    baseline_accuracy = Column(Float)
    recovered = Column(Boolean)
    confirmed = Column(Boolean)
    recovery_threshold = Column(Float)

    incident = relationship("Incident", back_populates="validations")


class Case(Base):
    """A resolved incident, kept for retrieval as prior evidence."""

    __tablename__ = "cases"

    id = Column(Integer, primary_key=True)
    incident_id = Column(Integer, ForeignKey("incidents.id"), unique=True)
    confirmed_cause = Column(String)  # commit sha, or "drift"
    category = Column(String, nullable=True)
    evidence_json = Column(Text)
    resolved_at = Column(DateTime, default=utcnow)


# --- Phase 3: multi-tenant "connect your repo" model ---------------------


class User(Base):
    """A GitHub account that has installed SERA's GitHub App. Identity is
    the App installation, not a password/session -- see
    sera/github_integration/github_app.py for why.
    """

    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    github_username = Column(String, unique=True, nullable=False)
    github_app_installation_id = Column(Integer, unique=True, nullable=True)
    created_at = Column(DateTime, default=utcnow)

    connected_repos = relationship("ConnectedRepo", back_populates="user")


class ConnectedRepo(Base):
    __tablename__ = "connected_repos"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    repo_full_name = Column(String, nullable=False)  # "owner/name"
    sera_yml_status = Column(String, default="missing")  # missing | present | invalid
    connected_at = Column(DateTime, default=utcnow)
    last_scan_at = Column(DateTime, nullable=True)

    # Push-based real-code scanning (see sera/api/routes_report.py): SERA
    # never clones or executes this repo's own code -- that would mean
    # running an arbitrary stranger's code on our infrastructure, a real
    # security liability, not just missing work. Instead the repo's own
    # CI runs its own canary_eval.py (already sandboxed by GitHub Actions,
    # already has the repo's real dependencies) and POSTs the result here,
    # authenticated by this per-repo secret token -- never the GitHub
    # installation token, which would be far too broad a credential to
    # embed in a repo's CI secrets.
    report_token = Column(String, nullable=True, unique=True)
    # Last known-good canary result from that real reporting pipeline,
    # JSON-encoded (accuracy/mean_confidence/mean_entropy/per_sample_*) --
    # the baseline every new report is diffed against. Bootstrapped by the
    # first report ever received for this repo.
    baseline_snapshot_json = Column(Text, nullable=True)

    __table_args__ = (UniqueConstraint("user_id", "repo_full_name", name="uq_user_repo"),)

    user = relationship("User", back_populates="connected_repos")
    scan_results = relationship("ScanResult", back_populates="repo")
    incidents = relationship("Incident", back_populates="connected_repo")


class ScanResult(Base):
    __tablename__ = "scan_results"

    id = Column(Integer, primary_key=True)
    repo_id = Column(Integer, ForeignKey("connected_repos.id"), nullable=False)
    run_id = Column(Integer, ForeignKey("runs.id"), nullable=True)
    status = Column(String, default="healthy")  # healthy | incident | pending | error
    summary_json = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utcnow)

    repo = relationship("ConnectedRepo", back_populates="scan_results")
