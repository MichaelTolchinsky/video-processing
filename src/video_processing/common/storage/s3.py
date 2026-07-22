import aioboto3
import boto3
from botocore.client import BaseClient
from botocore.config import Config

from video_processing.common.config.settings import settings

_S3_CONFIG = Config(s3={"addressing_style": "path"})

_async_session = aioboto3.Session()


def get_s3_client() -> BaseClient:
    """Client for direct S3 access from inside the VPC.

    Used by the worker to download originals and upload generated assets;
    unlike the API, it never hands URLs to an external client, so it has
    no need for the public/presigning endpoint. Stays sync/boto3 -- the
    worker's poll loop is strictly sequential, so there's nothing async
    would buy it (see worker/main.py).
    """
    return boto3.client(
        "s3",
        region_name=settings.aws_region,
        endpoint_url=settings.s3_endpoint_url,
        config=_S3_CONFIG,
    )


def get_async_presigning_s3_client() -> aioboto3.session.ClientCreatorContext:
    """Async client for the API's presigned upload/download URLs.

    Returns an async context manager (aioboto3 clients are used via
    `async with`, not returned directly) -- callers do
    `async with get_async_presigning_s3_client() as s3: ...`.
    """
    return _async_session.client(
        "s3",
        region_name=settings.aws_region,
        endpoint_url=settings.s3_public_endpoint_url or settings.s3_endpoint_url,
        config=_S3_CONFIG,
    )
