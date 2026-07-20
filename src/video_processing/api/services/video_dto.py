"""DTOs returned by video_service -- not the API request/response contract.

Kept separate from schemas/video.py (the Pydantic API schemas): these are
plain dataclasses describing what the service layer hands back to routes,
which then map them onto the actual response models.
"""

from dataclasses import dataclass
from datetime import datetime

from video_processing.common.models.generated_asset import GeneratedAsset
from video_processing.common.models.video import Video


@dataclass
class CreatedUpload:
    video: Video
    upload_url: str
    expires_at: datetime


@dataclass
class AssetDownload:
    asset: GeneratedAsset
    download_url: str
    expires_at: datetime
