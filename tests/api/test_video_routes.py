import uuid
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from tests.conftest import fake_async_client
from video_processing.api.main import app
from video_processing.api.services import video_service
from video_processing.common.db.repositories import generated_asset_repository, video_repository
from video_processing.common.db.session import get_db_session
from video_processing.common.models.asset_type import AssetType
from video_processing.common.models.generated_asset import GeneratedAsset
from video_processing.common.models.video import Video
from video_processing.common.models.video_status import VideoStatus


@pytest.fixture
def client(db, monkeypatch) -> TestClient:
    fake_client = AsyncMock()
    fake_client.generate_presigned_url.return_value = "https://example.com/presigned"
    monkeypatch.setattr(
        video_service, "get_async_presigning_s3_client", lambda: fake_async_client(fake_client)
    )
    monkeypatch.setattr(
        video_service, "get_async_sqs_client", lambda: fake_async_client(AsyncMock())
    )

    async def _override_db():
        yield db

    app.dependency_overrides[get_db_session] = _override_db
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_create_video_returns_201_with_upload_url(client):
    response = client.post("/videos", json={"filename": "clip.mp4", "content_type": "video/mp4"})

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == VideoStatus.PENDING_UPLOAD.value
    assert body["upload_url"] == "https://example.com/presigned"
    assert "expires_at" in body


def test_create_video_rejects_invalid_content_type(client):
    response = client.post("/videos", json={"filename": "clip.mp4", "content_type": "image/png"})

    assert response.status_code == 422


def test_get_video_returns_404_for_unknown_id(client):
    response = client.get(f"/videos/{uuid.uuid4()}")

    assert response.status_code == 404


async def test_get_video_returns_metadata_and_assets(client, db):
    video = Video(
        id=uuid.uuid4(),
        filename="clip.mp4",
        original_object_key=f"uploads/{uuid.uuid4()}/original.mp4",
        status=VideoStatus.COMPLETED,
        duration_ms=5000,
        width=1920,
        height=1080,
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

    response = client.get(f"/videos/{video.id}")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == VideoStatus.COMPLETED.value
    assert body["metadata"] == {"duration_ms": 5000, "width": 1920, "height": 1080}
    assert len(body["assets"]) == 1
    assert body["assets"][0]["type"] == AssetType.THUMBNAIL.value
    assert body["assets"][0]["download_url"] == "https://example.com/presigned"


async def test_get_video_returns_null_metadata_when_not_yet_extracted(client, db):
    video = Video(
        id=uuid.uuid4(),
        filename="clip.mp4",
        original_object_key=f"uploads/{uuid.uuid4()}/original.mp4",
        status=VideoStatus.PROCESSING,
    )
    video_repository.create(db, video)
    await db.commit()

    response = client.get(f"/videos/{video.id}")

    assert response.status_code == 200
    assert response.json()["metadata"] is None
    assert response.json()["assets"] == []


def test_retry_video_returns_404_for_unknown_id(client):
    response = client.post(f"/videos/{uuid.uuid4()}/retry")

    assert response.status_code == 404


async def test_retry_video_returns_409_when_not_failed(client, db):
    video = Video(
        id=uuid.uuid4(),
        filename="clip.mp4",
        original_object_key=f"uploads/{uuid.uuid4()}/original.mp4",
        status=VideoStatus.COMPLETED,
    )
    video_repository.create(db, video)
    await db.commit()

    response = client.post(f"/videos/{video.id}/retry")

    assert response.status_code == 409


async def test_retry_video_moves_failed_video_to_processing(client, db):
    video = Video(
        id=uuid.uuid4(),
        filename="clip.mp4",
        original_object_key=f"uploads/{uuid.uuid4()}/original.mp4",
        status=VideoStatus.FAILED,
    )
    video_repository.create(db, video)
    await db.commit()

    response = client.post(f"/videos/{video.id}/retry")

    assert response.status_code == 200
    assert response.json() == {"id": str(video.id), "status": VideoStatus.PROCESSING.value}
