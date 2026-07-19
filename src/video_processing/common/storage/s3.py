import boto3
from botocore.client import BaseClient
from botocore.config import Config

from video_processing.common.config.settings import settings

_S3_CONFIG = Config(s3={"addressing_style": "path"})


def get_s3_client() -> BaseClient:
    """Client for direct S3 access from inside the VPC.

    Used by the worker to download originals and upload generated assets;
    unlike the API, it never hands URLs to an external client, so it has
    no need for the public/presigning endpoint.
    """
    return boto3.client(
        "s3",
        region_name=settings.aws_region,
        endpoint_url=settings.s3_endpoint_url,
        config=_S3_CONFIG,
    )


def get_presigning_s3_client() -> BaseClient:
    return boto3.client(
        "s3",
        region_name=settings.aws_region,
        endpoint_url=settings.s3_public_endpoint_url or settings.s3_endpoint_url,
        config=_S3_CONFIG,
    )
