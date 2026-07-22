import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from video_processing.api.schemas.video_request import CreateVideoRequest
from video_processing.api.schemas.video_response import (
    CreateVideoResponse,
    GeneratedAssetResponse,
    GetVideoResponse,
    RetryVideoResponse,
    VideoMetadata,
)
from video_processing.api.services import video_service
from video_processing.api.services.video_service import VideoNotFailedError
from video_processing.common.db.session import get_db_session

router = APIRouter(prefix="/videos", tags=["videos"])


@router.post(
    "",
    response_model=CreateVideoResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Start a video upload",
    description=(
        "Creates a pending video record and returns a presigned S3 URL "
        "to upload the file to directly."
    ),
)
async def create_video(
    request: CreateVideoRequest,
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> CreateVideoResponse:
    created = await video_service.create_video(db, request.filename, request.content_type)
    return CreateVideoResponse(
        id=created.video.id,
        status=created.video.status,
        upload_url=created.upload_url,
        expires_at=created.expires_at,
    )


@router.get(
    "/{video_id}",
    response_model=GetVideoResponse,
    summary="Get video status and results",
    description=(
        "Returns processing status, extracted metadata, and presigned "
        "download URLs for any generated assets."
    ),
    responses={404: {"description": "Video not found"}},
)
async def get_video(
    video_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> GetVideoResponse:
    video = await video_service.get_video(db, video_id)
    if video is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Video not found")

    metadata = None
    if video.duration_ms is not None and video.width is not None and video.height is not None:
        metadata = VideoMetadata(
            duration_ms=video.duration_ms,
            width=video.width,
            height=video.height,
        )

    downloads = await video_service.get_asset_downloads(db, video_id)
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


@router.post(
    "/{video_id}/retry",
    response_model=RetryVideoResponse,
    summary="Retry a failed video",
    description=(
        "Re-publishes the original upload's S3 event to re-drive "
        "processing. Only allowed while status is 'failed'."
    ),
    responses={
        404: {"description": "Video not found"},
        409: {"description": "Video is not in a failed state"},
    },
)
async def retry_video(
    video_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> RetryVideoResponse:
    try:
        video = await video_service.retry_video(db, video_id)
    except VideoNotFailedError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error

    if video is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Video not found")

    return RetryVideoResponse(id=video.id, status=video.status)
