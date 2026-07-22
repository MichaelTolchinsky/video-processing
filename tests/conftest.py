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
    "DATABASE_URL", "postgresql+psycopg://user:pass@localhost:5432/unused"
)

from collections.abc import AsyncIterator  # noqa: E402

import pytest  # noqa: E402
from sqlalchemy.ext.asyncio import (  # noqa: E402
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool  # noqa: E402

from video_processing.common.db.base import Base  # noqa: E402
from video_processing.common.models import (  # noqa: E402, F401 -- registers tables on Base
    generated_asset,
    processing_job,
    video,
)


@pytest.fixture
async def db() -> AsyncIterator[AsyncSession]:
    """A fresh in-memory SQLite database per test.

    `enum_type()` uses `native_enum=False` (a plain VARCHAR + CHECK
    constraint), so it behaves the same on SQLite as on Postgres -- no
    container needed for repository/business-logic tests.

    StaticPool: keeps the same in-memory ":memory:" connection alive across
    the whole test instead of a fresh, empty database per checkout.
    """
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    async with session_factory() as session:
        yield session
    await engine.dispose()


class _FakeAsyncClientContext:
    """Minimal async context manager wrapping a plain mock client.

    Lets tests monkeypatch `get_async_presigning_s3_client`/`get_async_sqs_client`
    with `lambda: fake_async_client(mock)` in place of a real
    `async with session.client(...) as c:` call.
    """

    def __init__(self, client: object) -> None:
        self._client = client

    async def __aenter__(self) -> object:
        return self._client

    async def __aexit__(self, *exc_info: object) -> None:
        return None


def fake_async_client(client: object) -> _FakeAsyncClientContext:
    return _FakeAsyncClientContext(client)
