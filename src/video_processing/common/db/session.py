from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from video_processing.common.config.settings import settings

engine = create_engine(
    settings.sqlalchemy_database_url,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=5,
    pool_recycle=300,
)

SessionFactory = sessionmaker(
    bind=engine,
    autoflush=False,
    expire_on_commit=False
)


def get_db_session() -> Generator[Session, None, None]:
    with SessionFactory() as session:
        yield session
