"""Parsing for the S3 -> SQS `ObjectCreated` event notifications.

The bucket only publishes notifications for the `uploads/` prefix (configured
in PlatformStack), so every event this worker receives should reference an
original video upload, not a generated asset.
"""

import json
import re
import uuid
from dataclasses import dataclass
from urllib.parse import unquote_plus

# Matches the object key the API generates for uploads, e.g.
# "uploads/28e8c6e2-.../original.mp4". The extension is optional because we
# don't want a naming edge case to silently drop an otherwise valid event.
# The trailing "\\?" tolerates a LocalStack-only quirk (as of 3.8.1): it
# stores presigned-PUT uploads with a literal trailing backslash on the key,
# and reports that same real key in the ObjectCreated notification. Real AWS
# S3 never does this. We must keep that character when it's part of the
# actual key (S3 downloads need the exact key), so it's tolerated here rather
# than stripped from the key itself.
_UPLOAD_KEY_PATTERN = re.compile(
    r"^uploads/(?P<video_id>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/original(\.[A-Za-z0-9]+)?\\?$"
)


@dataclass
class ObjectCreatedEvent:
    bucket: str
    key: str


def parse_object_created_events(message_body: str) -> list[ObjectCreatedEvent]:
    """Extract ObjectCreated records from an SQS message body.

    S3 sends a one-off `s3:TestEvent` when a bucket notification is first
    configured; it has no "s3" section, so it's skipped rather than failed on.
    """
    body = json.loads(message_body)
    events = []
    for record in body.get("Records", []):
        s3_data = record.get("s3")
        if s3_data is None:
            continue
        events.append(
            ObjectCreatedEvent(
                bucket=s3_data["bucket"]["name"],
                # S3 URL-encodes object keys in event notifications. Keep the
                # decoded key exactly as reported (see the LocalStack note
                # above) so it still matches the real, stored object key.
                key=unquote_plus(s3_data["object"]["key"]),
            )
        )
    return events


def parse_video_id_from_key(object_key: str) -> uuid.UUID | None:
    """Recover the video ID the API embedded in the upload's object key."""
    match = _UPLOAD_KEY_PATTERN.match(object_key)
    if match is None:
        return None
    return uuid.UUID(match.group("video_id"))
