import json
import uuid

from video_processing.worker.s3_events import (
    parse_object_created_events,
    parse_video_id_from_key,
)

_VIDEO_ID = uuid.uuid4()


def _object_created_body(key: str, bucket: str = "test-bucket") -> str:
    return json.dumps(
        {
            "Records": [
                {"s3": {"bucket": {"name": bucket}, "object": {"key": key}}},
            ]
        }
    )


def test_parse_object_created_events_extracts_bucket_and_key():
    body = _object_created_body(f"uploads/{_VIDEO_ID}/original.mp4")

    events = parse_object_created_events(body)

    assert len(events) == 1
    assert events[0].bucket == "test-bucket"
    assert events[0].key == f"uploads/{_VIDEO_ID}/original.mp4"


def test_parse_object_created_events_url_decodes_key():
    # A space in a filename is URL-encoded as "+" in S3 event notifications.
    body = _object_created_body(f"uploads/{_VIDEO_ID}/original+file.mp4")

    events = parse_object_created_events(body)

    assert events[0].key == f"uploads/{_VIDEO_ID}/original file.mp4"


def test_parse_object_created_events_skips_test_event():
    # S3 sends a one-off s3:TestEvent (no "s3" key) when a notification is
    # first configured.
    body = json.dumps({"Records": [{"eventName": "s3:TestEvent"}]})

    events = parse_object_created_events(body)

    assert events == []


def test_parse_object_created_events_handles_multiple_records():
    other_id = uuid.uuid4()
    body = json.dumps(
        {
            "Records": [
                {
                    "s3": {
                        "bucket": {"name": "test-bucket"},
                        "object": {"key": f"uploads/{_VIDEO_ID}/original.mp4"},
                    }
                },
                {
                    "s3": {
                        "bucket": {"name": "test-bucket"},
                        "object": {"key": f"uploads/{other_id}/original.mov"},
                    }
                },
            ]
        }
    )

    events = parse_object_created_events(body)

    assert len(events) == 2


def test_parse_video_id_from_key_extracts_uuid():
    assert parse_video_id_from_key(f"uploads/{_VIDEO_ID}/original.mp4") == _VIDEO_ID


def test_parse_video_id_from_key_tolerates_localstack_trailing_backslash():
    # LocalStack (as of 3.8.1) appends a literal backslash to presigned-PUT
    # upload keys; real AWS S3 never does this.
    assert parse_video_id_from_key(f"uploads/{_VIDEO_ID}/original.mp4\\") == _VIDEO_ID


def test_parse_video_id_from_key_returns_none_for_generated_asset_key():
    assert parse_video_id_from_key(f"assets/{_VIDEO_ID}/thumbnail.jpg") is None


def test_parse_video_id_from_key_returns_none_for_unrecognized_key():
    assert parse_video_id_from_key("not-a-valid-key") is None
