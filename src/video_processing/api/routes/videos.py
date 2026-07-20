import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from video_processing.api.schemas.video_request import CreateVideoRequest
from video_processing.api.schemas.video_response import (
    CreateVideoResponse,
    GeneratedAssetResponse,
    GetVideoResponse,
    VideoMetadata,
)
from video_processing.api.services import video_service
from video_processing.common.db.session import get_db_session

router = APIRouter(prefix="/videos", tags=["videos"])


@router.post("", response_model=CreateVideoResponse, status_code=status.HTTP_201_CREATED)
def create_video(
    request: CreateVideoRequest,
    db: Annotated[Session, Depends(get_db_session)],
) -> CreateVideoResponse:
    created = video_service.create_video(db, request.filename, request.content_type)
    return CreateVideoResponse(
        id=created.video.id,
        status=created.video.status,
        upload_url=created.upload_url,
        expires_at=created.expires_at,
    )


@router.get("/{video_id}", response_model=GetVideoResponse)
def get_video(
    video_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db_session)],
) -> GetVideoResponse:
    video = video_service.get_video(db, video_id)
    if video is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Video not found")

    metadata = None
    if video.duration_ms is not None and video.width is not None and video.height is not None:
        metadata = VideoMetadata(
            duration_ms=video.duration_ms,
            width=video.width,
            height=video.height,
        )

    downloads = video_service.get_asset_downloads(db, video_id)
    asset_responses = [
        GeneratedAssetResponse(
            type=download.asset.asset_type,
            download_url=download.download_url,
            expires_at=download.expires_at,
        )
        for download in downloads
    ]

    return GetVideoResponse(
        id=video.id,
        filename=video.filename,
        status=video.status,
        metadata=metadata,
        assets=asset_responses,
    )
