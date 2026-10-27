"""SQLite engine/session setup for SERA's case store."""
from __future__ import annotations

import threading
from contextlib import contextmanager

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

from sera.config import DB_PATH
from sera.db.models import Base


def _add_missing_columns(engine):
    """create_all() never alters an existing table, so a DB file created by an
    older version of the code lacks columns added since (e.g.
    scan_results.validation_json) and every query on that table 500s with
    "no such column". Add any missing nullable-compatible columns in place."""
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if table.name not in existing_tables:
                continue
            have = {c["name"] for c in inspector.get_columns(table.name)}
            for col in table.columns:
                if col.name in have:
                    continue
                col_type = col.type.compile(dialect=engine.dialect)
                ddl = f'ALTER TABLE "{table.name}" ADD COLUMN "{col.name}" {col_type}'
                if col.default is not None and getattr(col.default, "is_scalar", False):
                    arg = col.default.arg
                    if isinstance(arg, bool):
                        arg = int(arg)
                    ddl += f" DEFAULT {arg!r}" if isinstance(arg, str) else f" DEFAULT {arg}"
                conn.execute(text(ddl))


def make_engine(db_path=None):
    path = db_path or DB_PATH
    engine = create_engine(
        f"sqlite:///{path}",
        future=True,
        connect_args={"timeout": 30},  # wait on a locked DB instead of erroring
    )
    Base.metadata.create_all(engine)
    _add_missing_columns(engine)
    return engine


_default_engine = None
_default_session_factory = None
# FastAPI runs sync routes in a thread pool, so the very first requests after
# a cold start (e.g. Render waking from idle) can call get_session_factory()
# concurrently. Without this lock, two threads both see
# _default_session_factory is None, both call make_engine(), and both run
# create_all() against the same sqlite file at once -- SQLite has no
# transactional DDL isolation, so one CREATE TABLE wins and the other raises
# "table already exists" instead of the whole thing being a no-op.
_init_lock = threading.Lock()


def get_session_factory(db_path=None):
    global _default_engine, _default_session_factory
    if db_path is not None:
        engine = make_engine(db_path)
        return sessionmaker(bind=engine, future=True)
    if _default_session_factory is None:
        with _init_lock:
            if _default_session_factory is None:  # re-check: lost the race, someone else already built it
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
