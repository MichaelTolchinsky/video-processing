import uuid
from datetime import UTC, datetime, timedelta
from pathlib import PurePath
from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from video_processing.api.schemas.video import CreateVideoRequest, CreateVideoResponse
from video_processing.common.db.session import get_db_session
from video_processing.common.models.video import Video
from video_processing.common.models.video_status import VideoStatus
from video_processing.common.config.settings import settings
from video_processing.common.storage.s3 import get_presigning_s3_client

router = APIRouter(prefix="/videos", tags=["videos"])

_UPLOAD_URL_EXPIRATION = timedelta(minutes=15)


@router.post("", response_model=CreateVideoResponse, status_code=status.HTTP_201_CREATED)
def create_video(
    request: CreateVideoRequest,
    db: Annotated[Session, Depends(get_db_session)],
) -> CreateVideoResponse:
    video_id = uuid.uuid4()
    object_key = f"uploads/{video_id}/original{PurePath(request.filename).suffix}"
    expires_at = datetime.now(UTC) + _UPLOAD_URL_EXPIRATION
    upload_url = get_presigning_s3_client().generate_presigned_url(
        "put_object",
        Params={
            "Bucket": settings.s3_bucket_name,
            "Key": object_key,
            "ContentType": request.content_type,
        },
        ExpiresIn=int(_UPLOAD_URL_EXPIRATION.total_seconds()),
    )
    video = Video(
        id=video_id,
        filename=request.filename,
        original_object_key=object_key,
        status=VideoStatus.PENDING_UPLOAD,
    )

    db.add(video)
    db.commit()

    return CreateVideoResponse(
        id=video.id,
        status=video.status,
        upload_url=upload_url,
        expires_at=expires_at,
    )
