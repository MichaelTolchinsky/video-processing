import uuid

from video_processing.common.db.repositories import generated_asset_repository, video_repository
from video_processing.common.models.asset_type import AssetType
from video_processing.common.models.generated_asset import GeneratedAsset
from video_processing.common.models.video import Video
from video_processing.common.models.video_status import VideoStatus


async def _make_video(db) -> Video:
    video = Video(
        id=uuid.uuid4(),
        filename="clip.mp4",
        original_object_key=f"uploads/{uuid.uuid4()}/original.mp4",
        status=VideoStatus.PENDING_UPLOAD,
    )
    video_repository.create(db, video)
    await db.commit()
    return video


async def test_create_and_get_by_video_and_type_round_trip(db):
    video = await _make_video(db)
    asset = GeneratedAsset(
        video_id=video.id,
        asset_type=AssetType.THUMBNAIL,
        object_key=f"assets/{video.id}/thumbnail.jpg",
    )

    generated_asset_repository.create(db, asset)
    await db.commit()

    fetched = await generated_asset_repository.get_by_video_and_type(
        db, video.id, AssetType.THUMBNAIL
    )
    assert fetched is not None
    assert fetched.object_key == f"assets/{video.id}/thumbnail.jpg"


async def test_get_by_video_and_type_returns_none_when_missing(db):
    video = await _make_video(db)

    assert (
        await generated_asset_repository.get_by_video_and_type(db, video.id, AssetType.THUMBNAIL)
        is None
    )


async def test_list_for_video_returns_all_assets(db):
    video = await _make_video(db)
    for asset_type in (AssetType.THUMBNAIL, AssetType.PREVIEW_720P, AssetType.PREVIEW_480P):
        generated_asset_repository.create(
            db,
            GeneratedAsset(
                video_id=video.id,
                asset_type=asset_type,
                object_key=f"assets/{video.id}/{asset_type.value}",
            ),
        )
    await db.commit()

    assets = await generated_asset_repository.list_for_video(db, video.id)

    assert {asset.asset_type for asset in assets} == {
        AssetType.THUMBNAIL,
        AssetType.PREVIEW_720P,
        AssetType.PREVIEW_480P,
    }


async def test_list_for_video_empty_when_no_assets(db):
    video = await _make_video(db)

    assert await generated_asset_repository.list_for_video(db, video.id) == []
