import uuid

from video_processing.common.db.repositories import video_repository
from video_processing.common.models.video import Video
from video_processing.common.models.video_status import VideoStatus


def _make_video(**overrides) -> Video:
    defaults = {
        "id": uuid.uuid4(),
        "filename": "clip.mp4",
        "original_object_key": f"uploads/{uuid.uuid4()}/original.mp4",
        "status": VideoStatus.PENDING_UPLOAD,
    }
    defaults.update(overrides)
    return Video(**defaults)


def test_create_and_get_by_id_round_trip(db):
    video = _make_video()

    video_repository.create(db, video)
    db.commit()

    fetched = video_repository.get_by_id(db, video.id)
    assert fetched is not None
    assert fetched.id == video.id
    assert fetched.filename == "clip.mp4"
    assert fetched.status == VideoStatus.PENDING_UPLOAD


def test_get_by_id_returns_none_for_unknown_id(db):
    assert video_repository.get_by_id(db, uuid.uuid4()) is None
