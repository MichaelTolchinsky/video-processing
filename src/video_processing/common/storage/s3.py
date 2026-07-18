import boto3
from botocore.client import BaseClient
from botocore.config import Config

from video_processing.common.config.settings import settings

_S3_CONFIG = Config(s3={"addressing_style": "path"})


def get_presigning_s3_client() -> BaseClient:
    return boto3.client(
        "s3",
        region_name=settings.aws_region,
        endpoint_url=settings.s3_public_endpoint_url or settings.s3_endpoint_url,
        config=_S3_CONFIG,
    )
