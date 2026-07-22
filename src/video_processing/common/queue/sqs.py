import aioboto3

from video_processing.common.config.settings import settings

_async_session = aioboto3.Session()


def get_async_sqs_client() -> aioboto3.session.ClientCreatorContext:
    """Async SQS client, shared by the API (enqueue retries) and the worker
    (long-poll/delete). Returns an async context manager --
    `async with get_async_sqs_client() as sqs: ...`.
    """
    return _async_session.client(
        "sqs",
        region_name=settings.aws_region,
        endpoint_url=settings.sqs_endpoint_url,
    )
