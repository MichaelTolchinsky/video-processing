from video_processing.common.models.asset_type import AssetType
from video_processing.worker.transcode import renditions_for_source_height


def test_renditions_for_source_height_excludes_resolutions_at_or_above_source():
    renditions = renditions_for_source_height(1080)

    asset_types = [rendition.asset_type for rendition in renditions]
    assert asset_types == [AssetType.PREVIEW_720P, AssetType.PREVIEW_480P]


def test_renditions_for_source_height_only_includes_smaller_resolutions():
    renditions = renditions_for_source_height(720)

    asset_types = [rendition.asset_type for rendition in renditions]
    assert asset_types == [AssetType.PREVIEW_480P]


def test_renditions_for_source_height_empty_when_source_is_smallest():
    assert renditions_for_source_height(480) == []


def test_renditions_for_source_height_includes_all_when_source_is_largest():
    renditions = renditions_for_source_height(2160)

    asset_types = [rendition.asset_type for rendition in renditions]
    assert asset_types == [
        AssetType.PREVIEW_1080P,
        AssetType.PREVIEW_720P,
        AssetType.PREVIEW_480P,
    ]
