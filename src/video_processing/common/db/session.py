from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from video_processing.common.config.settings import settings

engine = create_async_engine(
    settings.async_sqlalchemy_database_url,
    pool_pre_ping=True,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    pool_timeout=settings.db_pool_timeout,
    pool_recycle=300,
)

SessionFactory = async_sessionmaker(
    bind=engine,
    autoflush=False,
    expire_on_commit=False
)


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    async with SessionFactory() as session:
        yield session
