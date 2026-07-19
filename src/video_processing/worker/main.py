"""Worker entrypoint: long-polls SQS and processes uploaded videos.

This is a plain poll loop, not a web service — the worker has no HTTP
endpoints to serve, so it needs no FastAPI/Uvicorn, just a running process.
"""

import logging
import tempfile
from pathlib import Path
from typing import Any

from video_processing.common.config.settings import settings
from video_processing.common.db.session import SessionFactory
from video_processing.common.models.video import Video
from video_processing.common.queue.sqs import get_sqs_client
from video_processing.common.storage.s3 import get_s3_client
from video_processing.worker.jobs import claim_job, complete_job, fail_job
from video_processing.worker.processing import extract_metadata, generate_thumbnail
from video_processing.worker.s3_events import (
    parse_object_created_events,
    parse_video_id_from_key,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Generated assets live outside "uploads/" so they never re-trigger the
# bucket's ObjectCreated notification (which only watches "uploads/").
_ASSETS_PREFIX = "assets"


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

        job = claim_job(db, video)
        if job is None:
            logger.info("Job already completed for video %s; skipping", video_id)
            return

        try:
            with tempfile.TemporaryDirectory() as work_dir:
                original_path = Path(work_dir) / "original"
                thumbnail_path = Path(work_dir) / "thumbnail.jpg"

                get_s3_client().download_file(
                    settings.s3_bucket_name, object_key, str(original_path)
                )
                metadata = extract_metadata(original_path)
                generate_thumbnail(original_path, thumbnail_path)

                thumbnail_key = f"{_ASSETS_PREFIX}/{video_id}/thumbnail.jpg"
                get_s3_client().upload_file(
                    str(thumbnail_path), settings.s3_bucket_name, thumbnail_key
                )

            complete_job(db, job, video, metadata, thumbnail_key)
            logger.info("Completed processing for video %s", video_id)
        except Exception:
            logger.exception("Processing failed for video %s", video_id)
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
