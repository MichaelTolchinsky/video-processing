from aws_cdk import CfnOutput, Duration, Stack
from aws_cdk import aws_ecr as ecr
from aws_cdk import aws_ecs as ecs
from aws_cdk import aws_iam as iam
from constructs import Construct

# GitHub's OIDC issuer is a single, well-known URL — the same for every repo.
_GITHUB_OIDC_ISSUER_HOST = "token.actions.githubusercontent.com"
_GITHUB_OIDC_ISSUER_URL = f"https://{_GITHUB_OIDC_ISSUER_HOST}"


class PipelineStack(Stack):
    """IAM identity GitHub Actions assumes to build, push, and deploy.

    No AWS access keys are stored in GitHub: the workflow exchanges a
    short-lived OIDC token (scoped to this exact repo + branch) for
    temporary credentials via sts:AssumeRoleWithWebIdentity.
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        github_repository: str,
        github_repository_with_ids: str,
        container_repository: ecr.IRepository,
        cluster: ecs.ICluster,
        api_task_definition: ecs.FargateTaskDefinition,
        worker_task_definition: ecs.FargateTaskDefinition,
        migration_task_definition: ecs.FargateTaskDefinition,
        api_service: ecs.FargateService,
        worker_service: ecs.FargateService,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        github_oidc_provider = iam.OpenIdConnectProvider(
            self,
            "GitHubActionsOidcProvider",
            url=_GITHUB_OIDC_ISSUER_URL,
            client_ids=["sts.amazonaws.com"],
        )

        # StringLike on the "sub" claim restricts this role to workflows
        # running on `main` in this exact repo — a fork or a PR branch can't
        # assume it, even though the OIDC provider itself is account-wide.
        #
        # Two accepted forms because GitHub appends the owner/repo's
        # immutable numeric IDs to "sub" once either has ever been renamed
        # (verified via CloudTrail: this repo/owner triggers the ID-suffixed
        # form). Both list exact matches — no wildcards, so no broadening.
        self.deploy_role = iam.Role(
            self,
            "GitHubActionsDeployRole",
            role_name="video-processing-github-actions-deploy",
            max_session_duration=Duration.hours(1),
            assumed_by=iam.FederatedPrincipal(
                github_oidc_provider.open_id_connect_provider_arn,
                conditions={
                    "StringEquals": {
                        f"{_GITHUB_OIDC_ISSUER_HOST}:aud": "sts.amazonaws.com",
                    },
                    "StringLike": {
                        f"{_GITHUB_OIDC_ISSUER_HOST}:sub": [
                            f"repo:{github_repository}:ref:refs/heads/main",
                            f"repo:{github_repository_with_ids}:ref:refs/heads/main",
                        ],
                    },
                },
                assume_role_action="sts:AssumeRoleWithWebIdentity",
            ),
        )

        self.deploy_role.add_to_principal_policy(
            iam.PolicyStatement(
                actions=["ecr:GetAuthorizationToken"],
                resources=["*"],
            )
        )
        self.deploy_role.add_to_principal_policy(
            iam.PolicyStatement(
                actions=[
                    "ecr:BatchCheckLayerAvailability",
                    "ecr:GetDownloadUrlForLayer",
                    "ecr:BatchGetImage",
                    "ecr:PutImage",
                    "ecr:InitiateLayerUpload",
                    "ecr:UploadLayerPart",
                    "ecr:CompleteLayerUpload",
                ],
                resources=[container_repository.repository_arn],
            )
        )

        # ECS does not support resource-level permissions for these two
        # actions (they must be "*"); the cluster condition on RunTask is
        # the recommended way to still scope it to just this project.
        self.deploy_role.add_to_principal_policy(
            iam.PolicyStatement(
                actions=["ecs:RegisterTaskDefinition", "ecs:DescribeTaskDefinition"],
                resources=["*"],
            )
        )
        self.deploy_role.add_to_principal_policy(
            iam.PolicyStatement(
                actions=["ecs:RunTask", "ecs:DescribeTasks"],
                resources=["*"],
                conditions={"ArnEquals": {"ecs:cluster": cluster.cluster_arn}},
            )
        )
        self.deploy_role.add_to_principal_policy(
            iam.PolicyStatement(
                actions=["ecs:UpdateService", "ecs:DescribeServices"],
                resources=[api_service.service_arn, worker_service.service_arn],
            )
        )

        # Read-only; needed so the workflow can look up ECS/ECR resource
        # names dynamically instead of hardcoding CDK-generated values.
        # The trailing "/*" covers CloudFormation's per-stack unique suffix.
        self.deploy_role.add_to_principal_policy(
            iam.PolicyStatement(
                actions=["cloudformation:DescribeStacks"],
                resources=[
                    f"arn:aws:cloudformation:{self.region}:{self.account}:stack/PlatformStack/*",
                    f"arn:aws:cloudformation:{self.region}:{self.account}:stack/ServicesStack/*",
                ],
            )
        )

        # Needed because RegisterTaskDefinition takes the execution/task role
        # ARNs as plain parameters — AWS requires the caller to be allowed to
        # pass those specific roles to ECS, separately from ECS's own trust
        # policy on the roles themselves.
        passable_roles = [
            api_task_definition.task_role,
            api_task_definition.execution_role,
            worker_task_definition.task_role,
            worker_task_definition.execution_role,
            migration_task_definition.task_role,
            migration_task_definition.execution_role,
        ]
        if any(role is None for role in passable_roles):
            raise ValueError("Task definitions must have execution roles")

        self.deploy_role.add_to_principal_policy(
            iam.PolicyStatement(
                actions=["iam:PassRole"],
                resources=[role.role_arn for role in passable_roles],
                conditions={"StringEquals": {"iam:PassedToService": "ecs-tasks.amazonaws.com"}},
            )
        )

        CfnOutput(self, "GitHubActionsDeployRoleArn", value=self.deploy_role.role_arn)
