import uuid
from datetime import datetime
from pathlib import PurePath

from pydantic import BaseModel, Field, field_validator

from video_processing.common.models.video_status import VideoStatus


class CreateVideoRequest(BaseModel):
    filename: str = Field(max_length=255)
    content_type: str = Field(max_length=255)

    @field_validator("filename")
    @classmethod
    def validate_filename(cls, filename: str) -> str:
        path = PurePath(filename)
        if path.name != filename or not path.suffix:
            raise ValueError("filename must be a basename with an extension")
        return filename

    @field_validator("content_type")
    @classmethod
    def validate_content_type(cls, content_type: str) -> str:
        if not content_type.startswith("video/"):
            raise ValueError("content_type must be a video type")
        return content_type


class CreateVideoResponse(BaseModel):
    id: uuid.UUID
    status: VideoStatus
    upload_url: str
    expires_at: datetime
