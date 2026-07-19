import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from video_processing.common.db.base import Base
from video_processing.common.models.enum_type import enum_type
from video_processing.common.models.video_status import VideoStatus


class Video(Base):
    __tablename__ = "videos"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    filename: Mapped[str] = mapped_column(String(255))
    original_object_key: Mapped[str] = mapped_column(
        String(1024),
        unique=True,
    )
    status: Mapped[VideoStatus] = mapped_column(
        enum_type(VideoStatus),
        default=VideoStatus.PENDING_UPLOAD,
    )
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
