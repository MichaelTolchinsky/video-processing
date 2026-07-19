#!/usr/bin/env python3
import os

import aws_cdk as cdk
from infra.pipeline_stack import PipelineStack
from infra.platform_stack import PlatformStack
from infra.services_stack import ServicesStack

app = cdk.App()
platform_stack = PlatformStack(
    app,
    "PlatformStack",
    env=cdk.Environment(
        account=os.getenv("CDK_DEFAULT_ACCOUNT"),
        region=os.getenv("CDK_DEFAULT_REGION"),
    ),
)

services_stack = ServicesStack(
    app,
    "ServicesStack",
    vpc=platform_stack.vpc,
    container_repository=platform_stack.container_repository,
    database=platform_stack.database,
    database_security_group=platform_stack.database_security_group,
    video_bucket=platform_stack.video_bucket,
    processing_queue=platform_stack.processing_queue,
    env=cdk.Environment(
        account=os.getenv("CDK_DEFAULT_ACCOUNT"),
        region=os.getenv("CDK_DEFAULT_REGION"),
    ),
)

PipelineStack(
    app,
    "PipelineStack",
    github_repository="MichaelTolchinsky/video-processing",
    container_repository=platform_stack.container_repository,
    cluster=services_stack.cluster,
    api_task_definition=services_stack.api_task_definition,
    worker_task_definition=services_stack.worker_task_definition,
    api_service=services_stack.api_service,
    worker_service=services_stack.worker_service,
    env=cdk.Environment(
        account=os.getenv("CDK_DEFAULT_ACCOUNT"),
        region=os.getenv("CDK_DEFAULT_REGION"),
    ),
)

app.synth()
