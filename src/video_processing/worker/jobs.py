"""Database operations for claiming and finishing the metadata/thumbnail job.

Kept separate from S3/ffmpeg concerns so the retry/idempotency logic can be
read (and reasoned about) on its own.
"""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from video_processing.common.models.asset_type import AssetType
from video_processing.common.models.generated_asset import GeneratedAsset
from video_processing.common.models.job_status import JobStatus
from video_processing.common.models.job_type import JobType
from video_processing.common.models.processing_job import ProcessingJob
from video_processing.common.models.video import Video
from video_processing.common.models.video_status import VideoStatus
from video_processing.worker.processing import VideoMetadata


def _get_job(db: Session, video: Video) -> ProcessingJob | None:
    return db.execute(
        select(ProcessingJob).where(
            ProcessingJob.video_id == video.id,
            ProcessingJob.job_type == JobType.METADATA_AND_THUMBNAIL,
        )
    ).scalar_one_or_none()


def claim_job(db: Session, video: Video) -> ProcessingJob | None:
    """Create or resume the job for this video, atomically.

    S3 delivers ObjectCreated events at least once, and a message can also be
    redelivered after a failed attempt, so this must tolerate being called
    more than once for the same video.

    Returns None if the job is already completed, so the caller can treat the
    message as a harmless duplicate and acknowledge it without reprocessing.
    """
    job = _get_job(db, video)
    if job is None:
        job = ProcessingJob(video_id=video.id, job_type=JobType.METADATA_AND_THUMBNAIL)
        db.add(job)
        try:
            db.commit()
        except IntegrityError:
            # Another worker claimed it first (unique video_id + job_type);
            # fall back to the row it created instead of erroring out.
            db.rollback()
            job = _get_job(db, video)

    if job.status == JobStatus.COMPLETED:
        return None

    job.status = JobStatus.PROCESSING
    job.attempts += 1
    job.started_at = datetime.now(UTC)
    video.status = VideoStatus.PROCESSING
    db.commit()
    return job


def complete_job(
    db: Session,
    job: ProcessingJob,
    video: Video,
    metadata: VideoMetadata,
    thumbnail_object_key: str,
) -> None:
    """Persist metadata, the generated asset, and completion status as one transaction."""
    video.duration_ms = metadata.duration_ms
    video.width = metadata.width
    video.height = metadata.height
    video.status = VideoStatus.COMPLETED
    job.status = JobStatus.COMPLETED
    job.completed_at = datetime.now(UTC)
    db.add(
        GeneratedAsset(
            video_id=video.id,
            asset_type=AssetType.THUMBNAIL,
            object_key=thumbnail_object_key,
        )
    )
    db.commit()


def fail_job(db: Session, job: ProcessingJob, video: Video) -> None:
    """Mark the job and video failed.

    The SQS message is left undeleted by the caller, so SQS will redeliver
    it and `claim_job` will retry — this status is not final until the
    queue's maxReceiveCount is exceeded and the message moves to the DLQ.
    """
    job.status = JobStatus.FAILED
    video.status = VideoStatus.FAILED
    db.commit()
