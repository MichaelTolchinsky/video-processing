import pytest
from pydantic import ValidationError

from video_processing.api.schemas.video_request import CreateVideoRequest


def test_create_video_request_accepts_valid_input():
    request = CreateVideoRequest(filename="clip.mp4", content_type="video/mp4")

    assert request.filename == "clip.mp4"
    assert request.content_type == "video/mp4"


def test_create_video_request_rejects_filename_without_extension():
    with pytest.raises(ValidationError):
        CreateVideoRequest(filename="clip", content_type="video/mp4")


def test_create_video_request_rejects_path_in_filename():
    # PurePath("../clip.mp4").name != "../clip.mp4" -- catches path
    # traversal attempts disguised as a filename.
    with pytest.raises(ValidationError):
        CreateVideoRequest(filename="../clip.mp4", content_type="video/mp4")


def test_create_video_request_rejects_non_video_content_type():
    with pytest.raises(ValidationError):
        CreateVideoRequest(filename="clip.mp4", content_type="image/png")
