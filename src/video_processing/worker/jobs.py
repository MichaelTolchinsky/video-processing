"""Database operations for claiming and finishing processing jobs.

Kept separate from S3/ffmpeg concerns so the retry/idempotency logic can be
read (and reasoned about) on its own.
"""

from datetime import UTC, datetime

from sqlalchemy import func, select
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


def _get_job(db: Session, video: Video, job_type: JobType) -> ProcessingJob | None:
    return db.execute(
        select(ProcessingJob).where(
            ProcessingJob.video_id == video.id,
            ProcessingJob.job_type == job_type,
        )
    ).scalar_one_or_none()


def claim_job(db: Session, video: Video, job_type: JobType) -> ProcessingJob | None:
    """Create or resume this video's job of the given type, atomically.

    S3 delivers ObjectCreated events at least once, and a message can also be
    redelivered after a failed attempt, so this must tolerate being called
    more than once for the same video and job type.

    Returns None if the job is already completed, so the caller can treat the
    message as a harmless duplicate and acknowledge it without reprocessing.
    """
    job = _get_job(db, video, job_type)
    if job is None:
        job = ProcessingJob(video_id=video.id, job_type=job_type)
        db.add(job)
        try:
            db.commit()
        except IntegrityError:
            # Another worker claimed it first (unique video_id + job_type);
            # fall back to the row it created instead of erroring out.
            db.rollback()
            job = _get_job(db, video, job_type)

    if job.status == JobStatus.COMPLETED:
        return None

    job.status = JobStatus.PROCESSING
    job.attempts += 1
    job.started_at = datetime.now(UTC)
    # Don't regress an already-completed video (e.g. the other job type
    # finished first) back to "processing" for display purposes.
    if video.status != VideoStatus.COMPLETED:
        video.status = VideoStatus.PROCESSING
    db.commit()
    return job


def _all_jobs_completed(db: Session, video: Video) -> bool:
    """Whether every job type this video should have has completed.

    Every upload triggers one ProcessingJob per JobType (see worker/main.py),
    so "all done" is simply "as many completed rows as there are job types".

    Flushes first because the session disables autoflush (see
    common/db/session.py) -- without it, the caller's own just-set
    `job.status = COMPLETED` wouldn't be visible to this SELECT yet, so the
    last job to finish would never see itself counted.
    """
    db.flush()
    completed_count = db.execute(
        select(func.count())
        .select_from(ProcessingJob)
        .where(
            ProcessingJob.video_id == video.id,
            ProcessingJob.status == JobStatus.COMPLETED,
        )
    ).scalar_one()
    return completed_count >= len(JobType.__members__)


def _upsert_asset(db: Session, video: Video, asset_type: AssetType, object_key: str) -> None:
    """Insert the generated asset, or update its key if retrying after a
    partial prior failure already wrote one (avoids the UNIQUE(video_id,
    asset_type) constraint rejecting the retry).
    """
    existing = db.execute(
        select(GeneratedAsset).where(
            GeneratedAsset.video_id == video.id,
            GeneratedAsset.asset_type == asset_type,
        )
    ).scalar_one_or_none()
    if existing is not None:
        existing.object_key = object_key
    else:
        db.add(GeneratedAsset(video_id=video.id, asset_type=asset_type, object_key=object_key))


def complete_metadata_job(
    db: Session,
    job: ProcessingJob,
    video: Video,
    metadata: VideoMetadata,
) -> None:
    """Persist extracted metadata and this job's completion."""
    video.duration_ms = metadata.duration_ms
    video.width = metadata.width
    video.height = metadata.height
    job.status = JobStatus.COMPLETED
    job.completed_at = datetime.now(UTC)
    if _all_jobs_completed(db, video):
        video.status = VideoStatus.COMPLETED
    db.commit()


def complete_thumbnail_job(
    db: Session,
    job: ProcessingJob,
    video: Video,
    thumbnail_object_key: str,
) -> None:
    """Persist the thumbnail asset and this job's completion.

    Independent of the metadata job: generating a thumbnail only needs the
    downloaded file, not the extracted duration/dimensions.
    """
    job.status = JobStatus.COMPLETED
    job.completed_at = datetime.now(UTC)
    _upsert_asset(db, video, AssetType.THUMBNAIL, thumbnail_object_key)
    if _all_jobs_completed(db, video):
        video.status = VideoStatus.COMPLETED
    db.commit()


def complete_transcode_job(
    db: Session,
    job: ProcessingJob,
    video: Video,
    renditions: list[tuple[AssetType, str]],
) -> None:
    """Persist each transcoded rendition asset and this job's completion.

    `renditions` may be empty (e.g. the source is already at or below the
    smallest target resolution) -- the job still completes, it just produces
    nothing.
    """
    job.status = JobStatus.COMPLETED
    job.completed_at = datetime.now(UTC)
    for asset_type, object_key in renditions:
        _upsert_asset(db, video, asset_type, object_key)
    if _all_jobs_completed(db, video):
        video.status = VideoStatus.COMPLETED
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
