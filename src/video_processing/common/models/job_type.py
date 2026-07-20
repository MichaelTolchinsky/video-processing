from enum import StrEnum


class JobType(StrEnum):
    METADATA = "metadata"
    THUMBNAIL = "thumbnail"
    TRANSCODE = "transcode"
