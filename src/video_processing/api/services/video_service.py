"""Business logic for the /videos endpoints"""

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import PurePath

from sqlalchemy.orm import Session

from video_processing.api.services.video_dto import AssetDownloadDto, CreatedUploadDto
from video_processing.common.config.settings import settings
from video_processing.common.db.repositories import generated_asset_repository, video_repository
from video_processing.common.models.video import Video
from video_processing.common.models.video_status import VideoStatus
from video_processing.common.queue.s3_events import build_object_created_message
from video_processing.common.queue.sqs import get_sqs_client
from video_processing.common.storage.s3 import get_presigning_s3_client

_UPLOAD_URL_EXPIRATION = timedelta(minutes=15)
_DOWNLOAD_URL_EXPIRATION = timedelta(minutes=15)


class VideoNotFailedError(Exception):
    """Raised when a retry is requested for a video that isn't in "failed" status."""


def _build_upload_object_key(video_id: uuid.UUID, filename: str) -> str:
    return f"uploads/{video_id}/original{PurePath(filename).suffix}"


def _presign_upload_url(object_key: str, content_type: str) -> tuple[str, datetime]:
    upload_url = get_presigning_s3_client().generate_presigned_url(
        "put_object",
        Params={
            "Bucket": settings.s3_bucket_name,
            "Key": object_key,
            "ContentType": content_type,
        },
        ExpiresIn=int(_UPLOAD_URL_EXPIRATION.total_seconds()),
    )
    return upload_url, datetime.now(UTC) + _UPLOAD_URL_EXPIRATION


def _presign_download_url(object_key: str) -> tuple[str, datetime]:
    download_url = get_presigning_s3_client().generate_presigned_url(
        "get_object",
        Params={"Bucket": settings.s3_bucket_name, "Key": object_key},
        ExpiresIn=int(_DOWNLOAD_URL_EXPIRATION.total_seconds()),
    )
    return download_url, datetime.now(UTC) + _DOWNLOAD_URL_EXPIRATION


def create_video(db: Session, filename: str, content_type: str) -> CreatedUploadDto:
    """Create the pending Video row and a presigned S3 upload URL for it.

    The row is only committed after the presign call succeeds, so a broken
    S3/AWS configuration never leaves an unusable row behind.
    """
    video_id = uuid.uuid4()
    object_key = _build_upload_object_key(video_id, filename)
    upload_url, expires_at = _presign_upload_url(object_key, content_type)

    video = Video(
        id=video_id,
        filename=filename,
        original_object_key=object_key,
        status=VideoStatus.PENDING_UPLOAD,
    )
    video_repository.create(db, video)
    db.commit()

    return CreatedUploadDto(video=video, upload_url=upload_url, expires_at=expires_at)


def get_video(db: Session, video_id: uuid.UUID) -> Video | None:
    return video_repository.get_by_id(db, video_id)


def get_asset_downloads(db: Session, video_id: uuid.UUID) -> list[AssetDownloadDto]:
    """Load every generated asset for a video with a presigned download URL.

    S3 objects here are private, so a bare object_key is unusable by a
    client -- each asset needs its own signed, time-limited GET URL.
    """
    downloads = []
    for asset in generated_asset_repository.list_for_video(db, video_id):
        download_url, expires_at = _presign_download_url(asset.object_key)
        downloads.append(
            AssetDownloadDto(asset=asset, download_url=download_url, expires_at=expires_at)
        )
    return downloads


def retry_video(db: Session, video_id: uuid.UUID) -> Video | None:
    """Re-drive processing for a failed video.

    Re-publishes the original upload's S3 event to the processing queue
    instead of duplicating any claim/complete logic here -- the worker's
    existing `claim_job` already resumes any job not yet "completed", so
    this only needs to get that event back onto the queue.

    Returns None if the video doesn't exist. Raises VideoNotFailedError if
    it exists but isn't "failed" (nothing to retry).
    """
    video = video_repository.get_by_id(db, video_id)
    if video is None:
        return None
    if video.status != VideoStatus.FAILED:
        raise VideoNotFailedError(f"Video {video_id} is not in a failed state")

    message = build_object_created_message(settings.s3_bucket_name, video.original_object_key)
    get_sqs_client().send_message(QueueUrl=settings.sqs_queue_url, MessageBody=message)

    # Mirrors create_video's pattern: only mutate/commit after the AWS call
    # succeeds, so a broken queue never leaves the video silently stuck.
    video.status = VideoStatus.PROCESSING
    db.commit()
    return video
