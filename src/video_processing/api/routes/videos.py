import uuid
from datetime import UTC, datetime, timedelta
from pathlib import PurePath
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from video_processing.api.schemas.video import (
    CreateVideoRequest,
    CreateVideoResponse,
    GeneratedAssetResponse,
    GetVideoResponse,
    VideoMetadata,
)
from video_processing.common.config.settings import settings
from video_processing.common.db.session import get_db_session
from video_processing.common.models.generated_asset import GeneratedAsset
from video_processing.common.models.video import Video
from video_processing.common.models.video_status import VideoStatus
from video_processing.common.storage.s3 import get_presigning_s3_client

router = APIRouter(prefix="/videos", tags=["videos"])

_UPLOAD_URL_EXPIRATION = timedelta(minutes=15)
_DOWNLOAD_URL_EXPIRATION = timedelta(minutes=15)


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


@router.get("/{video_id}", response_model=GetVideoResponse)
def get_video(
    video_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db_session)],
) -> GetVideoResponse:
    video = db.get(Video, video_id)
    if video is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Video not found")

    metadata = None
    if video.duration_ms is not None and video.width is not None and video.height is not None:
        metadata = VideoMetadata(
            duration_ms=video.duration_ms,
            width=video.width,
            height=video.height,
        )

    assets = db.query(GeneratedAsset).filter(GeneratedAsset.video_id == video_id).all()
    expires_at = datetime.now(UTC) + _DOWNLOAD_URL_EXPIRATION
    asset_responses = [
        GeneratedAssetResponse(
            type=asset.asset_type,
            download_url=get_presigning_s3_client().generate_presigned_url(
                "get_object",
                Params={
                    "Bucket": settings.s3_bucket_name,
                    "Key": asset.object_key,
                },
                ExpiresIn=int(_DOWNLOAD_URL_EXPIRATION.total_seconds()),
            ),
            expires_at=expires_at,
        )
        for asset in assets
    ]

    return GetVideoResponse(
        id=video.id,
        filename=video.filename,
        status=video.status,
        metadata=metadata,
        assets=asset_responses,
    )
