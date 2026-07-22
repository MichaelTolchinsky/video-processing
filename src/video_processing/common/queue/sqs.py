import aioboto3
import boto3
from botocore.client import BaseClient

from video_processing.common.config.settings import settings

_async_session = aioboto3.Session()


def get_sqs_client() -> BaseClient:
    """Client the worker uses to long-poll and delete processing-queue
    messages. Stays sync/boto3 -- see get_s3_client for why."""
    return boto3.client(
        "sqs",
        region_name=settings.aws_region,
        endpoint_url=settings.sqs_endpoint_url,
    )


def get_async_sqs_client() -> aioboto3.session.ClientCreatorContext:
    """Async client the API uses to enqueue retry messages.

    Returns an async context manager -- `async with get_async_sqs_client() as sqs: ...`.
    """
    return _async_session.client(
        "sqs",
        region_name=settings.aws_region,
        endpoint_url=settings.sqs_endpoint_url,
    )
