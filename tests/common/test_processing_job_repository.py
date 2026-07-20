import uuid

from video_processing.common.db.repositories import processing_job_repository, video_repository
from video_processing.common.models.job_status import JobStatus
from video_processing.common.models.job_type import JobType
from video_processing.common.models.processing_job import ProcessingJob
from video_processing.common.models.video import Video
from video_processing.common.models.video_status import VideoStatus


def _make_video(db) -> Video:
    video = Video(
        id=uuid.uuid4(),
        filename="clip.mp4",
        original_object_key=f"uploads/{uuid.uuid4()}/original.mp4",
        status=VideoStatus.PENDING_UPLOAD,
    )
    video_repository.create(db, video)
    db.commit()
    return video


def test_create_and_get_by_video_and_type_round_trip(db):
    video = _make_video(db)
    job = ProcessingJob(video_id=video.id, job_type=JobType.METADATA)

    processing_job_repository.create(db, job)
    db.commit()

    fetched = processing_job_repository.get_by_video_and_type(db, video.id, JobType.METADATA)
    assert fetched is not None
    assert fetched.video_id == video.id
    assert fetched.status == JobStatus.PENDING


def test_get_by_video_and_type_returns_none_when_missing(db):
    video = _make_video(db)

    assert processing_job_repository.get_by_video_and_type(db, video.id, JobType.THUMBNAIL) is None


def test_count_completed_for_video_only_counts_completed_status(db):
    video = _make_video(db)
    for job_type, status in (
        (JobType.METADATA, JobStatus.COMPLETED),
        (JobType.THUMBNAIL, JobStatus.COMPLETED),
        (JobType.TRANSCODE, JobStatus.PROCESSING),
    ):
        processing_job_repository.create(
            db, ProcessingJob(video_id=video.id, job_type=job_type, status=status)
        )
    db.commit()

    assert processing_job_repository.count_completed_for_video(db, video.id) == 2


def test_count_completed_for_video_sees_uncommitted_status_change(db):
    """Regression test for the autoflush bug.

    SessionFactory disables autoflush, so a status change made earlier in
    the same transaction must be visible to this query without an explicit
    commit -- count_completed_for_video flushes internally to guarantee this.
    """
    video = _make_video(db)
    job = ProcessingJob(video_id=video.id, job_type=JobType.METADATA, status=JobStatus.PROCESSING)
    processing_job_repository.create(db, job)
    db.commit()

    job.status = JobStatus.COMPLETED  # not committed, not explicitly flushed

    assert processing_job_repository.count_completed_for_video(db, video.id) == 1
