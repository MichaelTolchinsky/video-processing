import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from video_processing.common.db.base import Base
from video_processing.common.models.enum_type import enum_type
from video_processing.common.models.job_status import JobStatus
from video_processing.common.models.job_type import JobType


class ProcessingJob(Base):
    __tablename__ = "processing_jobs"
    __table_args__ = (
        UniqueConstraint("video_id", "job_type"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    video_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("videos.id", ondelete="CASCADE"),
        index=True,
    )
    job_type: Mapped[JobType] = mapped_column(
        enum_type(JobType),
    )
    status: Mapped[JobStatus] = mapped_column(
        enum_type(JobStatus),
        default=JobStatus.PENDING,
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
    )