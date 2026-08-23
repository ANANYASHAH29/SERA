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
    status = Column(String, default="open")  # open | validated

    baseline_run = relationship("Run", foreign_keys=[baseline_run_id])
    regressed_run = relationship("Run", foreign_keys=[regressed_run_id])
    candidates = relationship("Candidate", back_populates="incident")
    validations = relationship("ValidationResult", back_populates="incident")


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
