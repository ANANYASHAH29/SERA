"""SQLite engine/session setup for SERA's case store."""
from __future__ import annotations

from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from sera.config import DB_PATH
from sera.db.models import Base


def make_engine(db_path=None):
    path = db_path or DB_PATH
    engine = create_engine(f"sqlite:///{path}", future=True)
    Base.metadata.create_all(engine)
    return engine


_default_engine = None
_default_session_factory = None


def get_session_factory(db_path=None):
    global _default_engine, _default_session_factory
    if db_path is not None:
        engine = make_engine(db_path)
        return sessionmaker(bind=engine, future=True)
    if _default_session_factory is None:
        _default_engine = make_engine()
        _default_session_factory = sessionmaker(bind=_default_engine, future=True)
    return _default_session_factory


@contextmanager
def session_scope(db_path=None):
    factory = get_session_factory(db_path)
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
