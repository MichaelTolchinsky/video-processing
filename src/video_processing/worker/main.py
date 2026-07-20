"""Worker entrypoint: long-polls SQS and processes uploaded videos.

This is a plain poll loop, not a web service — the worker has no HTTP
endpoints to serve, so it needs no FastAPI/Uvicorn, just a running process.
"""

import logging
import tempfile
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from video_processing.common.config.settings import settings
from video_processing.common.db.session import SessionFactory
from video_processing.common.models.job_status import JobStatus
from video_processing.common.models.job_type import JobType
from video_processing.common.models.processing_job import ProcessingJob
from video_processing.common.models.video import Video
from video_processing.common.queue.sqs import get_sqs_client
from video_processing.common.storage.s3 import get_s3_client
from video_processing.worker.jobs import (
    claim_job,
    complete_metadata_job,
    complete_thumbnail_job,
    complete_transcode_job,
    fail_job,
)
from video_processing.worker.processing import (
    VideoMetadata,
    extract_metadata,
    generate_thumbnail,
)
from video_processing.worker.s3_events import (
    parse_object_created_events,
    parse_video_id_from_key,
)
from video_processing.worker.transcode import renditions_for_source_height, transcode

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Generated assets live outside "uploads/" so they never re-trigger the
# bucket's ObjectCreated notification (which only watches "uploads/").
_ASSETS_PREFIX = "assets"


def _run_metadata_job(
    db: Session, job: ProcessingJob, video: Video, original_path: Path
) -> VideoMetadata:
    metadata = extract_metadata(original_path)
    complete_metadata_job(db, job, video, metadata)
    return metadata


def _run_thumbnail_job(
    db: Session,
    job: ProcessingJob,
    video: Video,
    video_id: uuid.UUID,
    original_path: Path,
    work_dir: Path,
) -> None:
    thumbnail_path = work_dir / "thumbnail.jpg"
    generate_thumbnail(original_path, thumbnail_path)

    thumbnail_key = f"{_ASSETS_PREFIX}/{video_id}/thumbnail.jpg"
    get_s3_client().upload_file(str(thumbnail_path), settings.s3_bucket_name, thumbnail_key)
    complete_thumbnail_job(db, job, video, thumbnail_key)


def _run_transcode_job(
    db: Session,
    job: ProcessingJob,
    video: Video,
    video_id: uuid.UUID,
    original_path: Path,
    work_dir: Path,
    metadata: VideoMetadata | None,
) -> None:
    # Prefer this run's freshly extracted height; fall back to the stored
    # value when only the transcode job needed a retry (metadata was
    # already completed in an earlier attempt).
    source_height = metadata.height if metadata is not None else video.height
    if source_height is None:
        raise RuntimeError(f"Video {video_id} has no known height to transcode against")

    renditions = []
    for rendition in renditions_for_source_height(source_height):
        rendition_path = work_dir / f"{rendition.asset_type.value}.mp4"
        transcode(original_path, rendition_path, rendition)

        rendition_key = f"{_ASSETS_PREFIX}/{video_id}/{rendition.asset_type.value}.mp4"
        get_s3_client().upload_file(str(rendition_path), settings.s3_bucket_name, rendition_key)
        renditions.append((rendition.asset_type, rendition_key))

    complete_transcode_job(db, job, video, renditions)


def process_uploaded_object(object_key: str) -> None:
    video_id = parse_video_id_from_key(object_key)
    if video_id is None:
        logger.warning("Ignoring unrecognized object key: %s", object_key)
        return

    with SessionFactory() as db:
        video = db.get(Video, video_id)
        # Compare against the artifact-free key (see s3_events.py) so this
        # still recognizes a legitimate match locally; `object_key` itself is
        # left untouched below since S3 downloads need the exact, real key.
        if video is None or object_key.removesuffix("\\") != video.original_object_key:
            # Defends against a stale or unexpected event that doesn't match
            # a known video record and its upload key.
            logger.warning("No matching video for key: %s", object_key)
            return

        # Each video gets one job per JobType, claimed independently so any
        # one of them can be retried/completed on its own -- claim_job
        # returns None for whichever is already done (handles SQS
        # redelivery). Metadata and thumbnail are independent of each other
        # (thumbnailing only needs the downloaded file); transcode is the
        # only one that depends on another job's output (metadata.height).
        metadata_job = claim_job(db, video, JobType.METADATA)
        thumbnail_job = claim_job(db, video, JobType.THUMBNAIL)
        transcode_job = claim_job(db, video, JobType.TRANSCODE)
        if metadata_job is None and thumbnail_job is None and transcode_job is None:
            logger.info("All jobs already completed for video %s; skipping", video_id)
            return

        try:
            with tempfile.TemporaryDirectory() as work_dir_str:
                work_dir = Path(work_dir_str)
                original_path = work_dir / "original"
                get_s3_client().download_file(
                    settings.s3_bucket_name, object_key, str(original_path)
                )

                metadata = None
                if metadata_job is not None:
                    metadata = _run_metadata_job(db, metadata_job, video, original_path)

                if thumbnail_job is not None:
                    _run_thumbnail_job(
                        db, thumbnail_job, video, video_id, original_path, work_dir
                    )

                if transcode_job is not None:
                    _run_transcode_job(
                        db, transcode_job, video, video_id, original_path, work_dir, metadata
                    )

            logger.info("Completed processing for video %s", video_id)
        except Exception:
            logger.exception("Processing failed for video %s", video_id)
            for job in (metadata_job, thumbnail_job, transcode_job):
                if job is not None and job.status != JobStatus.COMPLETED:
                    fail_job(db, job, video)
            # Re-raise so the poll loop knows not to delete the SQS message.
            raise


def process_message(message: dict[str, Any]) -> None:
    for event in parse_object_created_events(message["Body"]):
        process_uploaded_object(event.key)


def run() -> None:
    sqs = get_sqs_client()
    logger.info("Worker started; polling %s", settings.sqs_queue_url)

    while True:
        response = sqs.receive_message(
            QueueUrl=settings.sqs_queue_url,
            MaxNumberOfMessages=1,
            WaitTimeSeconds=20,  # long polling, matches the queue's configuration
        )
        for message in response.get("Messages", []):
            try:
                process_message(message)
            except Exception:
                # Leave the message in the queue: SQS makes it visible again
                # after the visibility timeout so it can be retried, and
                # eventually moves it to the dead-letter queue.
                continue
            sqs.delete_message(
                QueueUrl=settings.sqs_queue_url,
                ReceiptHandle=message["ReceiptHandle"],
            )


if __name__ == "__main__":
    run()
