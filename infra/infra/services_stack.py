from aws_cdk import CfnOutput, Stack, aws_ec2 as ec2, aws_ecr as ecr, aws_ecs as ecs, aws_elasticloadbalancingv2 as elbv2, aws_iam as iam, aws_rds as rds, aws_s3 as s3
from constructs import Construct

class ServicesStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, *, vpc: ec2.IVpc, container_repository: ecr.IRepository, database: rds.IDatabaseInstance, database_security_group: ec2.ISecurityGroup, video_bucket: s3.IBucket, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)
        
        self.vpc = vpc
        self.container_repository = container_repository
        self.database = database
        self.database_security_group = database_security_group
        self.video_bucket = video_bucket
        
        self.cluster = ecs.Cluster(
            self,
            "VideoProcessingCluster",
            vpc=self.vpc,
            container_insights_v2=ecs.ContainerInsights.ENABLED,
        )
        
        self.api_task_definition = ecs.FargateTaskDefinition(
            self,
            "ApiTaskDefinition",
            cpu=256,
            memory_limit_mib=512,
        )
        self.api_task_definition.task_role.add_to_principal_policy(
            iam.PolicyStatement(
                actions=["s3:PutObject"],
                resources=[self.video_bucket.arn_for_objects("uploads/*")],
            )
        )

        application_image = ecs.ContainerImage.from_ecr_repository(
            self.container_repository,
            tag="latest",
        )
        
        api_container = self.api_task_definition.add_container(
            "ApiContainer",
            image=application_image,
            logging=ecs.LogDrivers.aws_logs(stream_prefix="api"),
            environment={
                "AWS_REGION": self.region,
                "S3_BUCKET_NAME": self.video_bucket.bucket_name,
            },
        )

        database_secret = self.database.secret
        if database_secret is None:
            raise ValueError("The database must have a generated secret")

        database_secrets = {
            "DATABASE_HOST": ecs.Secret.from_secrets_manager(database_secret, "host"),
            "DATABASE_PORT": ecs.Secret.from_secrets_manager(database_secret, "port"),
            "DATABASE_USERNAME": ecs.Secret.from_secrets_manager(
                database_secret,
                "username",
            ),
            "DATABASE_PASSWORD": ecs.Secret.from_secrets_manager(
                database_secret,
                "password",
            ),
            "DATABASE_NAME": ecs.Secret.from_secrets_manager(
                database_secret,
                "dbname",
            ),
        }
        for name, secret in database_secrets.items():
            api_container.add_secret(name, secret)

        database_secret.grant_read(
            self.api_task_definition.execution_role,
        )
        
        api_container.add_port_mappings(
            ecs.PortMapping(container_port=8000)
        )
        
        self.api_security_group = ec2.SecurityGroup(
            self,
            "ApiSecurityGroup",
            vpc=self.vpc,
            description="Controls access to the API tasks",
            allow_all_outbound=True
        )
        ec2.CfnSecurityGroupIngress(
            self,
            "ApiToDatabaseIngress",
            group_id=self.database_security_group.security_group_id,
            ip_protocol="tcp",
            from_port=5432,
            to_port=5432,
            source_security_group_id=self.api_security_group.security_group_id,
        )

        self.migration_task_definition = ecs.FargateTaskDefinition(
            self,
            "MigrationTaskDefinition",
            cpu=256,
            memory_limit_mib=512,
        )
        self.migration_task_definition.add_container(
            "MigrationContainer",
            image=application_image,
            command=["alembic", "upgrade", "head"],
            logging=ecs.LogDrivers.aws_logs(stream_prefix="migration"),
            environment={
                "AWS_REGION": self.region,
                "S3_BUCKET_NAME": self.video_bucket.bucket_name,
            },
            secrets=database_secrets,
        )
        database_secret.grant_read(
            self.migration_task_definition.execution_role,
        )
        
        self.api_service = ecs.FargateService(
            self,
            "ApiService",
            cluster=self.cluster,
            task_definition=self.api_task_definition,
            desired_count=1,
            min_healthy_percent=100,
            assign_public_ip=False,
            vpc_subnets=ec2.SubnetSelection(
                subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS,
            ),
            security_groups=[self.api_security_group]
        )

        self.alb_security_group = ec2.SecurityGroup(
            self,
            "AlbSecurityGroup",
            vpc=self.vpc,
            description="Allows public HTTP traffic to the ALB",
        )

        self.alb_security_group.add_ingress_rule(
            ec2.Peer.any_ipv4(),
            ec2.Port.tcp(80),
        )

        self.load_balancer = elbv2.ApplicationLoadBalancer(
            self,
            "ApiLoadBalancer",
            vpc=self.vpc,
            internet_facing=True,
            vpc_subnets=ec2.SubnetSelection(
                subnet_type=ec2.SubnetType.PUBLIC,
            ),
            security_group=self.alb_security_group,
        )
        
        self.api_security_group.add_ingress_rule(
            self.alb_security_group,
            ec2.Port.tcp(8000)
        )
        
        listener = self.load_balancer.add_listener(
            "HttpListener",
            port=80,
            open=False,
        )
        
        listener.add_targets(
            "ApiTargets",
            port=8000,
            targets=[self.api_service],
            health_check=elbv2.HealthCheck(
                path="/health",
                healthy_http_codes="200"
            )
        )
        
        CfnOutput(self, "ApiUrl", value=f"http://{self.load_balancer.load_balancer_dns_name}")
        CfnOutput(
            self,
            "ApiSecurityGroupId",
            value=self.api_security_group.security_group_id,
        )
        CfnOutput(
            self,
            "MigrationTaskDefinitionArn",
            value=self.migration_task_definition.task_definition_arn,
        )