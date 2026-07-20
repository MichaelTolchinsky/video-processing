import uuid
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from video_processing.api.services import video_service
from video_processing.common.db.repositories import generated_asset_repository, video_repository
from video_processing.common.models.asset_type import AssetType
from video_processing.common.models.generated_asset import GeneratedAsset
from video_processing.common.models.video import Video
from video_processing.common.models.video_status import VideoStatus


@pytest.fixture
def fake_s3_client(monkeypatch) -> MagicMock:
    """Replaces the presigning client at the seam video_service calls
    through, so no real AWS credentials/network are needed."""
    client = MagicMock()
    client.generate_presigned_url.return_value = "https://example.com/presigned"
    monkeypatch.setattr(video_service, "get_presigning_s3_client", lambda: client)
    return client


class TestCreateVideo:
    def test_creates_pending_video_with_presigned_upload_url(self, db, fake_s3_client):
        created = video_service.create_video(db, "clip.mp4", "video/mp4")

        assert created.video.filename == "clip.mp4"
        assert created.video.status == VideoStatus.PENDING_UPLOAD
        assert created.video.original_object_key == f"uploads/{created.video.id}/original.mp4"
        assert created.upload_url == "https://example.com/presigned"
        assert created.expires_at > datetime.now(UTC)

    def test_persists_the_video_row(self, db, fake_s3_client):
        created = video_service.create_video(db, "clip.mov", "video/quicktime")

        assert video_repository.get_by_id(db, created.video.id) is not None

    def test_presigns_put_object_for_the_given_content_type(self, db, fake_s3_client):
        video_service.create_video(db, "clip.mp4", "video/mp4")

        _args, kwargs = fake_s3_client.generate_presigned_url.call_args
        assert fake_s3_client.generate_presigned_url.call_args[0][0] == "put_object"
        assert kwargs["Params"]["ContentType"] == "video/mp4"


class TestGetVideo:
    def test_returns_existing_video(self, db):
        video = Video(
            id=uuid.uuid4(),
            filename="clip.mp4",
            original_object_key=f"uploads/{uuid.uuid4()}/original.mp4",
            status=VideoStatus.COMPLETED,
        )
        video_repository.create(db, video)
        db.commit()

        assert video_service.get_video(db, video.id) is not None

    def test_returns_none_for_unknown_video(self, db):
        assert video_service.get_video(db, uuid.uuid4()) is None


class TestGetAssetDownloads:
    def test_returns_a_presigned_download_per_asset(self, db, fake_s3_client):
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
        db.commit()

        downloads = video_service.get_asset_downloads(db, video.id)

        assert len(downloads) == 1
        assert downloads[0].asset.asset_type == AssetType.THUMBNAIL
        assert downloads[0].download_url == "https://example.com/presigned"
        assert downloads[0].expires_at > datetime.now(UTC)

    def test_returns_empty_list_when_no_assets_exist(self, db, fake_s3_client):
        video = Video(
            id=uuid.uuid4(),
            filename="clip.mp4",
            original_object_key=f"uploads/{uuid.uuid4()}/original.mp4",
            status=VideoStatus.PROCESSING,
        )
        video_repository.create(db, video)
        db.commit()

        assert video_service.get_asset_downloads(db, video.id) == []
