"""Shared pytest fixtures.

Required settings (aws_region, s3_bucket_name) must exist before any
video_processing module is imported, since Settings() is instantiated at
import time -- hence the env vars are set before the imports below.
"""

import os

os.environ.setdefault("AWS_REGION", "us-east-1")
os.environ.setdefault("S3_BUCKET_NAME", "test-bucket")
# common/db/session.py builds a real engine at import time (lazily connects,
# but needs a syntactically valid URL) -- routes import it transitively even
# though tests override get_db_session with the in-memory `db` fixture.
os.environ.setdefault(
    "DATABASE_URL", "postgresql+psycopg://unused:unused@localhost:5432/unused"
)

import pytest  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from video_processing.common.db.base import Base  # noqa: E402
from video_processing.common.models import (  # noqa: E402, F401 -- registers tables on Base
    generated_asset,
    processing_job,
    video,
)


@pytest.fixture
def db() -> Session:
    """A fresh in-memory SQLite database per test.

    `enum_type()` uses `native_enum=False` (a plain VARCHAR + CHECK
    constraint), so it behaves the same on SQLite as on Postgres -- no
    container needed for repository/business-logic tests.

    StaticPool + check_same_thread=False: FastAPI's TestClient runs sync
    route handlers in a worker thread, and a bare in-memory SQLite connection
    is otherwise single-connection-per-thread (and a new connection to
    ":memory:" is a distinct, empty database).
    """
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with session_factory() as session:
        yield session
    engine.dispose()
