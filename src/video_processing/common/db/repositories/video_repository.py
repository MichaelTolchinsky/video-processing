"""Data access for the `videos` table.

Plain functions, not a class/interface -- there is exactly one backing
implementation (SQLAlchemy + Postgres). Transaction control (commit/rollback)
stays with the calling business logic, not here.
"""

import uuid

from sqlalchemy.orm import Session

from video_processing.common.models.video import Video


def get_by_id(db: Session, video_id: uuid.UUID) -> Video | None:
    return db.get(Video, video_id)


def create(db: Session, video: Video) -> None:
    db.add(video)
