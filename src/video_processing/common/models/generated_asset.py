import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from video_processing.common.db.base import Base
from video_processing.common.models.enum_type import enum_type
from video_processing.common.models.asset_type import AssetType


class GeneratedAsset(Base):
    __tablename__ = "generated_assets"
    __table_args__ = (
        UniqueConstraint("video_id", "asset_type"),
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
    asset_type: Mapped[AssetType] = mapped_column(
        enum_type(AssetType),
    )
    object_key: Mapped[str] = mapped_column(
        String(1024),
        unique=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )