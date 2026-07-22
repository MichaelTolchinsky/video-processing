"""Data access for the `videos` table.

Plain functions, not a class/interface -- there is exactly one backing
implementation (SQLAlchemy + Postgres). Transaction control (commit/rollback)
stays with the calling business logic, not here.
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from video_processing.common.models.video import Video


async def get_by_id(db: AsyncSession, video_id: uuid.UUID) -> Video | None:
    return await db.get(Video, video_id)


def create(db: AsyncSession, video: Video) -> None:
    db.add(video)
