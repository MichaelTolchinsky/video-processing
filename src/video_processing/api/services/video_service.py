"""Business logic for the /videos endpoints"""

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import PurePath

from sqlalchemy import select
from sqlalchemy.orm import Session

from video_processing.api.schemas.video_service import AssetDownload, CreatedUpload
from video_processing.common.config.settings import settings
from video_processing.common.models.generated_asset import GeneratedAsset
from video_processing.common.models.video import Video
from video_processing.common.models.video_status import VideoStatus
from video_processing.common.storage.s3 import get_presigning_s3_client

_UPLOAD_URL_EXPIRATION = timedelta(minutes=15)
_DOWNLOAD_URL_EXPIRATION = timedelta(minutes=15)


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


def _get_assets_for_video(db: Session, video_id: uuid.UUID) -> list[GeneratedAsset]:
    return list(
        db.execute(select(GeneratedAsset).where(GeneratedAsset.video_id == video_id))
        .scalars()
        .all()
    )


def create_video(db: Session, filename: str, content_type: str) -> CreatedUpload:
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
    db.add(video)
    db.commit()

    return CreatedUpload(video=video, upload_url=upload_url, expires_at=expires_at)


def get_video(db: Session, video_id: uuid.UUID) -> Video | None:
    return db.get(Video, video_id)


def get_asset_downloads(db: Session, video_id: uuid.UUID) -> list[AssetDownload]:
    """Load every generated asset for a video with a presigned download URL.

    S3 objects here are private, so a bare object_key is unusable by a
    client -- each asset needs its own signed, time-limited GET URL.
    """
    downloads = []
    for asset in _get_assets_for_video(db, video_id):
        download_url, expires_at = _presign_download_url(asset.object_key)
        downloads.append(
            AssetDownload(asset=asset, download_url=download_url, expires_at=expires_at)
        )
    return downloads
