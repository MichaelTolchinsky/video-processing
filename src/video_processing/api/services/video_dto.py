"""DTOs returned by video_service -- not the API request/response contract.

Lives next to video_service.py (the module that owns and returns these),
rather than in api/schemas/ alongside video_request.py/video_response.py --
those are the Pydantic API contract; these are plain dataclasses internal
to the service layer, which routes map onto the actual response models.
"""

from dataclasses import dataclass
from datetime import datetime

from video_processing.common.models.generated_asset import GeneratedAsset
from video_processing.common.models.video import Video


@dataclass
class CreatedUploadDto:
    video: Video
    upload_url: str
    expires_at: datetime


@dataclass
class AssetDownloadDto:
    asset: GeneratedAsset
    download_url: str
    expires_at: datetime
