"""ffprobe/ffmpeg wrappers for metadata extraction and thumbnail generation.

Kept separate from database and SQS/S3 concerns so this module is just
"local file in, local file/data out" and easy to reason about on its own.
"""

import asyncio
import json
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


async def _run(*args: str) -> bytes:
    """Run a subprocess without blocking the event loop.

    Required for real concurrency: `subprocess.run` blocks the single
    worker event loop, which would serialize every "concurrent" video
    behind whichever one is currently probing/encoding.
    """
    process = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    if process.returncode != 0:
        raise RuntimeError(
            f"Command {args!r} exited with {process.returncode}: {stderr.decode()}"
        )
    return stdout


async def extract_metadata(video_path: Path) -> VideoMetadata:
    """Run ffprobe to read duration and the first video stream's dimensions."""
    stdout = await _run(
        "ffprobe",
        "-v", "error",
        "-print_format", "json",
        "-show_entries", "format=duration:stream=width,height",
        "-select_streams", "v:0",
        str(video_path),
    )
    probe = json.loads(stdout)
    stream = probe["streams"][0]
    duration_seconds = float(probe["format"]["duration"])
    return VideoMetadata(
        duration_ms=round(duration_seconds * 1000),
        width=stream["width"],
        height=stream["height"],
    )


async def generate_thumbnail(video_path: Path, thumbnail_path: Path) -> None:
    """Extract a single frame near the start of the video as a JPEG thumbnail."""
    await _run(
        "ffmpeg",
        "-y",
        "-i", str(video_path),
        "-ss", _THUMBNAIL_OFFSET,
        "-frames:v", "1",
        str(thumbnail_path),
    )
