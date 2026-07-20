"""ffmpeg wrapper for generating resolution renditions of an uploaded video.

Kept separate from processing.py (metadata/thumbnail) since it has its own
resolution-selection logic — matches the project's one-concern-per-file split.
"""

import subprocess
from dataclasses import dataclass
from pathlib import Path

from video_processing.common.models.asset_type import AssetType


@dataclass(frozen=True)
class Rendition:
    asset_type: AssetType
    height: int
    # Target video bitrate, sized to the resolution rather than reusing the
    # source's bitrate -- what a real encode ladder does (e.g. YouTube/Netflix
    # style bitrate-per-resolution), even though we keep the output a plain
    # MP4 file rather than an adaptive-bitrate (HLS/DASH) package.
    bitrate_kbps: int


# Ordered largest to smallest. Only resolutions strictly below the source's
# are produced (see renditions_for_source_height) -- re-encoding at the same
# or a larger resolution than the original wastes storage/compute for no
# quality gain, so e.g. a 1080p upload only produces 720p and 480p.
_RENDITIONS = [
    Rendition(AssetType.PREVIEW_1080P, height=1080, bitrate_kbps=5000),
    Rendition(AssetType.PREVIEW_720P, height=720, bitrate_kbps=2500),
    Rendition(AssetType.PREVIEW_480P, height=480, bitrate_kbps=1000),
]


def renditions_for_source_height(source_height: int) -> list[Rendition]:
    return [rendition for rendition in _RENDITIONS if rendition.height < source_height]


def transcode(video_path: Path, output_path: Path, rendition: Rendition) -> None:
    """Scale to `rendition.height` (preserving aspect ratio) at its target bitrate."""
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i", str(video_path),
            "-vf", f"scale=-2:{rendition.height}",
            "-c:v", "libx264",
            "-b:v", f"{rendition.bitrate_kbps}k",
            "-c:a", "aac",
            str(output_path),
        ],
        capture_output=True,
        check=True,
    )
