import uuid
from datetime import datetime

from pydantic import BaseModel

from video_processing.common.models.asset_type import AssetType
from video_processing.common.models.video_status import VideoStatus


class CreateVideoResponse(BaseModel):
    id: uuid.UUID
    status: VideoStatus
    upload_url: str
    expires_at: datetime


class VideoMetadata(BaseModel):
    duration_ms: int
    width: int
    height: int


class GeneratedAssetResponse(BaseModel):
    type: AssetType
    download_url: str
    expires_at: datetime


class GetVideoResponse(BaseModel):
    id: uuid.UUID
    filename: str
    status: VideoStatus
    metadata: VideoMetadata | None
    assets: list[GeneratedAssetResponse]


class RetryVideoResponse(BaseModel):
    id: uuid.UUID
    status: VideoStatus
