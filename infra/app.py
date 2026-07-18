#!/usr/bin/env python3
import os

import aws_cdk as cdk

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

ServicesStack(
    app,
    "ServicesStack",
    vpc=platform_stack.vpc,
    container_repository=platform_stack.container_repository,
    database=platform_stack.database,
    database_security_group=platform_stack.database_security_group,
    video_bucket=platform_stack.video_bucket,
    env=cdk.Environment(
        account=os.getenv("CDK_DEFAULT_ACCOUNT"),
        region=os.getenv("CDK_DEFAULT_REGION"),
    ),
)

app.synth()
