from enum import StrEnum


class VideoStatus(StrEnum):
    PENDING_UPLOAD = "pending_upload"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"