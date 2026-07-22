import uuid

import pytest
from sqlalchemy import select

from video_processing.common.db.repositories import video_repository
from video_processing.common.models.asset_type import AssetType
from video_processing.common.models.generated_asset import GeneratedAsset
from video_processing.common.models.job_status import JobStatus
from video_processing.common.models.job_type import JobType
from video_processing.common.models.video import Video
from video_processing.common.models.video_status import VideoStatus
from video_processing.worker.jobs import (
    claim_job,
    complete_metadata_job,
    complete_thumbnail_job,
    complete_transcode_job,
    fail_job,
)
from video_processing.worker.processing import VideoMetadata


@pytest.fixture
async def video(db) -> Video:
    video = Video(
        id=uuid.uuid4(),
        filename="clip.mp4",
        original_object_key=f"uploads/{uuid.uuid4()}/original.mp4",
        status=VideoStatus.PENDING_UPLOAD,
    )
    video_repository.create(db, video)
    await db.commit()
    return video


class TestClaimJob:
    async def test_creates_job_and_marks_processing(self, db, video):
        job = await claim_job(db, video, JobType.METADATA)

        assert job is not None
        assert job.status == JobStatus.PROCESSING
        assert job.attempts == 1
        assert job.started_at is not None
        assert video.status == VideoStatus.PROCESSING

    async def test_second_call_resumes_same_job_and_increments_attempts(self, db, video):
        first = await claim_job(db, video, JobType.METADATA)
        first_id = first.id

        second = await claim_job(db, video, JobType.METADATA)

        assert second.id == first_id
        assert second.attempts == 2

    async def test_returns_none_when_job_already_completed(self, db, video):
        job = await claim_job(db, video, JobType.METADATA)
        metadata = VideoMetadata(duration_ms=1000, width=640, height=480)
        await complete_metadata_job(db, job, video, metadata)

        assert await claim_job(db, video, JobType.METADATA) is None

    async def test_does_not_regress_completed_video_status(self, db, video):
        # e.g. the other job type already finished and completed the video;
        # claiming a retried job type shouldn't flip it back to "processing"
        # for display purposes.
        video.status = VideoStatus.COMPLETED
        await db.commit()

        await claim_job(db, video, JobType.THUMBNAIL)

        assert video.status == VideoStatus.COMPLETED


class TestCompleteMetadataJob:
    async def test_persists_metadata_and_completes_job(self, db, video):
        job = await claim_job(db, video, JobType.METADATA)

        metadata = VideoMetadata(duration_ms=5000, width=1920, height=1080)
        await complete_metadata_job(db, job, video, metadata)

        assert job.status == JobStatus.COMPLETED
        assert job.completed_at is not None
        assert video.duration_ms == 5000
        assert video.width == 1920
        assert video.height == 1080

    async def test_video_stays_processing_until_every_job_type_completes(self, db, video):
        metadata_job = await claim_job(db, video, JobType.METADATA)
        await claim_job(db, video, JobType.THUMBNAIL)
        await claim_job(db, video, JobType.TRANSCODE)

        metadata = VideoMetadata(duration_ms=1, width=1, height=1)
        await complete_metadata_job(db, metadata_job, video, metadata)

        assert video.status == VideoStatus.PROCESSING

    async def test_video_completes_once_all_job_types_completed(self, db, video):
        metadata_job = await claim_job(db, video, JobType.METADATA)
        thumbnail_job = await claim_job(db, video, JobType.THUMBNAIL)
        transcode_job = await claim_job(db, video, JobType.TRANSCODE)

        await complete_thumbnail_job(db, thumbnail_job, video, f"assets/{video.id}/thumbnail.jpg")
        await complete_transcode_job(db, transcode_job, video, [])
        metadata = VideoMetadata(duration_ms=1, width=1, height=1)
        await complete_metadata_job(db, metadata_job, video, metadata)

        assert video.status == VideoStatus.COMPLETED


class TestCompleteThumbnailJob:
    async def test_creates_thumbnail_asset(self, db, video):
        job = await claim_job(db, video, JobType.THUMBNAIL)

        await complete_thumbnail_job(db, job, video, f"assets/{video.id}/thumbnail.jpg")

        asset = (
            await db.execute(
                select(GeneratedAsset).filter_by(
                    video_id=video.id, asset_type=AssetType.THUMBNAIL
                )
            )
        ).scalar_one()
        assert asset.object_key == f"assets/{video.id}/thumbnail.jpg"

    async def test_retry_updates_existing_asset_instead_of_duplicating(self, db, video):
        job = await claim_job(db, video, JobType.THUMBNAIL)
        await complete_thumbnail_job(db, job, video, f"assets/{video.id}/thumbnail-v1.jpg")

        # Simulates a retry after a partial prior failure already wrote one.
        await complete_thumbnail_job(db, job, video, f"assets/{video.id}/thumbnail-v2.jpg")

        assets = (
            (
                await db.execute(
                    select(GeneratedAsset).filter_by(
                        video_id=video.id, asset_type=AssetType.THUMBNAIL
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(assets) == 1
        assert assets[0].object_key == f"assets/{video.id}/thumbnail-v2.jpg"


class TestCompleteTranscodeJob:
    async def test_persists_each_rendition(self, db, video):
        job = await claim_job(db, video, JobType.TRANSCODE)

        await complete_transcode_job(
            db,
            job,
            video,
            [
                (AssetType.PREVIEW_720P, f"assets/{video.id}/720p.mp4"),
                (AssetType.PREVIEW_480P, f"assets/{video.id}/480p.mp4"),
            ],
        )

        assets = (
            (await db.execute(select(GeneratedAsset).filter_by(video_id=video.id)))
            .scalars()
            .all()
        )
        assert {asset.asset_type for asset in assets} == {
            AssetType.PREVIEW_720P,
            AssetType.PREVIEW_480P,
        }

    async def test_completes_job_with_no_renditions(self, db, video):
        # Source already at or below the smallest target resolution.
        job = await claim_job(db, video, JobType.TRANSCODE)

        await complete_transcode_job(db, job, video, [])

        assert job.status == JobStatus.COMPLETED
        count = len(
            (await db.execute(select(GeneratedAsset).filter_by(video_id=video.id)))
            .scalars()
            .all()
        )
        assert count == 0


class TestFailJob:
    async def test_marks_job_and_video_failed(self, db, video):
        job = await claim_job(db, video, JobType.METADATA)

        await fail_job(db, job, video)

        assert job.status == JobStatus.FAILED
        assert video.status == VideoStatus.FAILED
