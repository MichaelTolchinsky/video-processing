import boto3
from botocore.client import BaseClient

from video_processing.common.config.settings import settings


def get_sqs_client() -> BaseClient:
    """Client the worker uses to long-poll and delete processing-queue messages."""
    return boto3.client(
        "sqs",
        region_name=settings.aws_region,
        endpoint_url=settings.sqs_endpoint_url,
    )
