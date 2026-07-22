import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from tests.conftest import fake_async_client
from video_processing.api.services import video_service
from video_processing.common.db.repositories import generated_asset_repository, video_repository
from video_processing.common.models.asset_type import AssetType
from video_processing.common.models.generated_asset import GeneratedAsset
from video_processing.common.models.video import Video
from video_processing.common.models.video_status import VideoStatus
from video_processing.common.queue.s3_events import parse_object_created_events


@pytest.fixture
def fake_s3_client(monkeypatch) -> AsyncMock:
    """Replaces the presigning client at the seam video_service calls
    through, so no real AWS credentials/network are needed."""
    client = AsyncMock()
    client.generate_presigned_url.return_value = "https://example.com/presigned"
    monkeypatch.setattr(
        video_service, "get_async_presigning_s3_client", lambda: fake_async_client(client)
    )
    return client


@pytest.fixture
def fake_sqs_client(monkeypatch) -> AsyncMock:
    """Replaces the SQS client at the seam video_service calls through."""
    client = AsyncMock()
    monkeypatch.setattr(video_service, "get_async_sqs_client", lambda: fake_async_client(client))
    return client


class TestCreateVideo:
    async def test_creates_pending_video_with_presigned_upload_url(self, db, fake_s3_client):
        created = await video_service.create_video(db, "clip.mp4", "video/mp4")

        assert created.video.filename == "clip.mp4"
        assert created.video.status == VideoStatus.PENDING_UPLOAD
        assert created.video.original_object_key == f"uploads/{created.video.id}/original.mp4"
        assert created.upload_url == "https://example.com/presigned"
        assert created.expires_at > datetime.now(UTC)

    async def test_persists_the_video_row(self, db, fake_s3_client):
        created = await video_service.create_video(db, "clip.mov", "video/quicktime")

        assert await video_repository.get_by_id(db, created.video.id) is not None

    async def test_presigns_put_object_for_the_given_content_type(self, db, fake_s3_client):
        await video_service.create_video(db, "clip.mp4", "video/mp4")

        _args, kwargs = fake_s3_client.generate_presigned_url.call_args
        assert fake_s3_client.generate_presigned_url.call_args[0][0] == "put_object"
        assert kwargs["Params"]["ContentType"] == "video/mp4"


class TestGetVideo:
    async def test_returns_existing_video(self, db):
        video = Video(
            id=uuid.uuid4(),
            filename="clip.mp4",
            original_object_key=f"uploads/{uuid.uuid4()}/original.mp4",
            status=VideoStatus.COMPLETED,
        )
        video_repository.create(db, video)
        await db.commit()

        assert await video_service.get_video(db, video.id) is not None

    async def test_returns_none_for_unknown_video(self, db):
        assert await video_service.get_video(db, uuid.uuid4()) is None


class TestGetAssetDownloads:
    async def test_returns_a_presigned_download_per_asset(self, db, fake_s3_client):
        video = Video(
            id=uuid.uuid4(),
            filename="clip.mp4",
            original_object_key=f"uploads/{uuid.uuid4()}/original.mp4",
            status=VideoStatus.COMPLETED,
        )
        video_repository.create(db, video)
        generated_asset_repository.create(
            db,
            GeneratedAsset(
                video_id=video.id,
                asset_type=AssetType.THUMBNAIL,
                object_key=f"assets/{video.id}/thumbnail.jpg",
            ),
        )
        await db.commit()

        downloads = await video_service.get_asset_downloads(db, video.id)

        assert len(downloads) == 1
        assert downloads[0].asset.asset_type == AssetType.THUMBNAIL
        assert downloads[0].download_url == "https://example.com/presigned"
        assert downloads[0].expires_at > datetime.now(UTC)

    async def test_returns_empty_list_when_no_assets_exist(self, db, fake_s3_client):
        video = Video(
            id=uuid.uuid4(),
            filename="clip.mp4",
            original_object_key=f"uploads/{uuid.uuid4()}/original.mp4",
            status=VideoStatus.PROCESSING,
        )
        video_repository.create(db, video)
        await db.commit()

        assert await video_service.get_asset_downloads(db, video.id) == []


class TestRetryVideo:
    async def _make_failed_video(self, db) -> Video:
        video = Video(
            id=uuid.uuid4(),
            filename="clip.mp4",
            original_object_key=f"uploads/{uuid.uuid4()}/original.mp4",
            status=VideoStatus.FAILED,
        )
        video_repository.create(db, video)
        await db.commit()
        return video

    async def test_re_publishes_the_original_upload_event(self, db, fake_sqs_client):
        video = await self._make_failed_video(db)

        await video_service.retry_video(db, video.id)

        _args, kwargs = fake_sqs_client.send_message.call_args
        events = parse_object_created_events(kwargs["MessageBody"])
        assert events[0].key == video.original_object_key

    async def test_moves_video_back_to_processing(self, db, fake_sqs_client):
        video = await self._make_failed_video(db)

        retried = await video_service.retry_video(db, video.id)

        assert retried.status == VideoStatus.PROCESSING

    async def test_returns_none_for_unknown_video(self, db, fake_sqs_client):
        assert await video_service.retry_video(db, uuid.uuid4()) is None

    async def test_raises_when_video_is_not_failed(self, db, fake_sqs_client):
        video = Video(
            id=uuid.uuid4(),
            filename="clip.mp4",
            original_object_key=f"uploads/{uuid.uuid4()}/original.mp4",
            status=VideoStatus.COMPLETED,
        )
        video_repository.create(db, video)
        await db.commit()

        with pytest.raises(video_service.VideoNotFailedError):
            await video_service.retry_video(db, video.id)

        fake_sqs_client.send_message.assert_not_called()
