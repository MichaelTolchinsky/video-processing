"""Worker entrypoint: long-polls SQS and processes uploaded videos.

This is a plain poll loop, not a web service — the worker has no HTTP
endpoints to serve, so it needs no FastAPI/Uvicorn, just a running process.
"""

import asyncio
import logging
import tempfile
import uuid
from pathlib import Path
from typing import Any

from aiobotocore.client import AioBaseClient
from sqlalchemy.ext.asyncio import AsyncSession

from video_processing.common.config.settings import settings
from video_processing.common.db.session import SessionFactory
from video_processing.common.models.job_status import JobStatus
from video_processing.common.models.job_type import JobType
from video_processing.common.models.processing_job import ProcessingJob
from video_processing.common.models.video import Video
from video_processing.common.queue.s3_events import (
    parse_object_created_events,
    parse_video_id_from_key,
)
from video_processing.common.queue.sqs import get_async_sqs_client
from video_processing.common.storage.s3 import get_async_s3_client
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
from video_processing.worker.transcode import renditions_for_source_height, transcode

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Generated assets live outside "uploads/" so they never re-trigger the
# bucket's ObjectCreated notification (which only watches "uploads/").
_ASSETS_PREFIX = "assets"


async def _run_metadata_job(
    db: AsyncSession, job: ProcessingJob, video: Video, original_path: Path
) -> VideoMetadata:
    metadata = await extract_metadata(original_path)
    await complete_metadata_job(db, job, video, metadata)
    return metadata


async def _run_thumbnail_job(
    s3: AioBaseClient,
    db: AsyncSession,
    job: ProcessingJob,
    video: Video,
    video_id: uuid.UUID,
    original_path: Path,
    work_dir: Path,
) -> None:
    thumbnail_path = work_dir / "thumbnail.jpg"
    await generate_thumbnail(original_path, thumbnail_path)

    thumbnail_key = f"{_ASSETS_PREFIX}/{video_id}/thumbnail.jpg"
    await s3.upload_file(str(thumbnail_path), settings.s3_bucket_name, thumbnail_key)
    await complete_thumbnail_job(db, job, video, thumbnail_key)


async def _run_transcode_job(
    s3: AioBaseClient,
    db: AsyncSession,
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
        await transcode(original_path, rendition_path, rendition)

        rendition_key = f"{_ASSETS_PREFIX}/{video_id}/{rendition.asset_type.value}.mp4"
        await s3.upload_file(str(rendition_path), settings.s3_bucket_name, rendition_key)
        renditions.append((rendition.asset_type, rendition_key))

    await complete_transcode_job(db, job, video, renditions)


async def _download_original(s3: AioBaseClient, object_key: str, work_dir: Path) -> Path:
    original_path = work_dir / "original"
    await s3.download_file(settings.s3_bucket_name, object_key, str(original_path))
    return original_path


async def _fail_incomplete_jobs(
    db: AsyncSession, jobs: tuple[ProcessingJob | None, ...], video: Video
) -> None:
    for job in jobs:
        if job is not None and job.status != JobStatus.COMPLETED:
            await fail_job(db, job, video)


async def process_uploaded_object(object_key: str) -> None:
    video_id = parse_video_id_from_key(object_key)
    if video_id is None:
        logger.warning("Ignoring unrecognized object key: %s", object_key)
        return

    async with SessionFactory() as db:
        video = await db.get(Video, video_id)
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
        metadata_job = await claim_job(db, video, JobType.METADATA)
        thumbnail_job = await claim_job(db, video, JobType.THUMBNAIL)
        transcode_job = await claim_job(db, video, JobType.TRANSCODE)
        if metadata_job is None and thumbnail_job is None and transcode_job is None:
            logger.info("All jobs already completed for video %s; skipping", video_id)
            return

        try:
            async with get_async_s3_client() as s3:
                with tempfile.TemporaryDirectory() as work_dir_str:
                    work_dir = Path(work_dir_str)
                    original_path = await _download_original(s3, object_key, work_dir)

                    metadata = None
                    if metadata_job is not None:
                        metadata = await _run_metadata_job(db, metadata_job, video, original_path)

                    if thumbnail_job is not None:
                        await _run_thumbnail_job(
                            s3, db, thumbnail_job, video, video_id, original_path, work_dir
                        )

                    if transcode_job is not None:
                        await _run_transcode_job(
                            s3,
                            db,
                            transcode_job,
                            video,
                            video_id,
                            original_path,
                            work_dir,
                            metadata,
                        )

            logger.info("Completed processing for video %s", video_id)
        except Exception:
            logger.exception("Processing failed for video %s", video_id)
            await _fail_incomplete_jobs(db, (metadata_job, thumbnail_job, transcode_job), video)
            # Re-raise so the poll loop knows not to delete the SQS message.
            raise


async def process_message(message: dict[str, Any]) -> None:
    for event in parse_object_created_events(message["Body"]):
        await process_uploaded_object(event.key)


async def _handle_message(sqs: AioBaseClient, message: dict[str, Any]) -> None:
    """Process one message and delete it on success.

    Isolated per-message (own try/except) so `asyncio.gather` on a batch
    lets every other in-flight video finish even if this one fails --
    failures here just leave the message for SQS to redeliver/DLQ, same as
    the previous single-message loop.
    """
    try:
        await process_message(message)
    except Exception:
        # Leave the message in the queue: SQS makes it visible again after
        # the visibility timeout so it can be retried, and eventually moves
        # it to the dead-letter queue.
        return
    await sqs.delete_message(
        QueueUrl=settings.sqs_queue_url,
        ReceiptHandle=message["ReceiptHandle"],
    )


async def run() -> None:
    # SQS caps a single receive_message call at 10 messages.
    batch_size = min(settings.worker_concurrency, 10)
    logger.info(
        "Worker started; polling %s (concurrency=%d)", settings.sqs_queue_url, batch_size
    )

    async with get_async_sqs_client() as sqs:
        while True:
            response = await sqs.receive_message(
                QueueUrl=settings.sqs_queue_url,
                MaxNumberOfMessages=batch_size,
                WaitTimeSeconds=20,  # long polling, matches the queue's configuration
            )
            messages = response.get("Messages", [])
            if messages:
                # Each video's ffmpeg/ffprobe calls are separate OS
                # processes, so this is genuine parallelism, not just
                # interleaved I/O waits -- bounded by batch_size (see
                # Settings.worker_concurrency) to match the task's CPU
                # budget instead of thrashing it.
                await asyncio.gather(*(_handle_message(sqs, message) for message in messages))


if __name__ == "__main__":
    asyncio.run(run())
