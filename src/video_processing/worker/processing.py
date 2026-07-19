"""ffprobe/ffmpeg wrappers for metadata extraction and thumbnail generation.

Kept separate from database and SQS/S3 concerns so this module is just
"local file in, local file/data out" and easy to reason about on its own.
"""

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

# Frame to grab for the thumbnail. Most uploads will be longer than this,
# and a fixed offset keeps the logic simple for this learning project.
_THUMBNAIL_OFFSET = "00:00:01"


@dataclass
class VideoMetadata:
    duration_ms: int
    width: int
    height: int


def extract_metadata(video_path: Path) -> VideoMetadata:
    """Run ffprobe to read duration and the first video stream's dimensions."""
    result = subprocess.run(
        [
            "ffprobe",
            "-v", "error",
            "-print_format", "json",
            "-show_entries", "format=duration:stream=width,height",
            "-select_streams", "v:0",
            str(video_path),
        ],
        capture_output=True,
        check=True,
        text=True,
    )
    probe = json.loads(result.stdout)
    stream = probe["streams"][0]
    duration_seconds = float(probe["format"]["duration"])
    return VideoMetadata(
        duration_ms=round(duration_seconds * 1000),
        width=stream["width"],
        height=stream["height"],
    )


def generate_thumbnail(video_path: Path, thumbnail_path: Path) -> None:
    """Extract a single frame near the start of the video as a JPEG thumbnail."""
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i", str(video_path),
            "-ss", _THUMBNAIL_OFFSET,
            "-frames:v", "1",
            str(thumbnail_path),
        ],
        capture_output=True,
        check=True,
    )
