from aws_cdk import Duration, RemovalPolicy, Stack, aws_ec2 as ec2, aws_s3 as s3, aws_sqs as sqs, aws_s3_notifications as s3_notifications, aws_rds as rds, aws_ecr as ecr
from constructs import Construct

class PlatformStack(Stack):

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.vpc = ec2.Vpc(
            self,
            "VideoProcessingVpc",
            max_azs=2,
            nat_gateways=1,
            subnet_configuration=[
                ec2.SubnetConfiguration(
                    name="public",
                    subnet_type=ec2.SubnetType.PUBLIC
                ),
                ec2.SubnetConfiguration(
                    name="application",
                    subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS
                ),
                ec2.SubnetConfiguration(
                    name="database",
                    subnet_type=ec2.SubnetType.PRIVATE_ISOLATED
                ),
            ]
        )
        
        self.video_bucket = s3.Bucket(
            self,
            "VideoBucket",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            enforce_ssl=True,
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
        )
        
        self.dead_letter_queue = sqs.Queue(
            self,
            "ProcessingDeadLetterQueue",
            retention_period=Duration.days(7),
            encryption=sqs.QueueEncryption.SQS_MANAGED,
            enforce_ssl=True
        )
        
        self.processing_queue = sqs.Queue(
            self,
            "ProcessingQueue",
            visibility_timeout=Duration.minutes(15),
            receive_message_wait_time=Duration.seconds(20),
            encryption=sqs.QueueEncryption.SQS_MANAGED,
            enforce_ssl=True,
            dead_letter_queue=sqs.DeadLetterQueue(
                queue=self.dead_letter_queue,
                max_receive_count=3
            )
        )
        
        self.video_bucket.add_event_notification(
            s3.EventType.OBJECT_CREATED,
            s3_notifications.SqsDestination(self.processing_queue),
            s3.NotificationKeyFilter(prefix="uploads/")
        )
        
        self.database_security_group = ec2.SecurityGroup(
            self,
            "DatabaseSecurityGroup",
            vpc=self.vpc,
            description="Control access to PostgreSQL",
            allow_all_outbound=False
        )
        
        self.database = rds.DatabaseInstance(
            self,
            "VideoDatabase",
            engine=rds.DatabaseInstanceEngine.postgres(
                version=rds.PostgresEngineVersion.VER_16,
            ),
            credentials=rds.Credentials.from_generated_secret("video_processing"),
            database_name="video_processing",
            instance_type=ec2.InstanceType.of(
                ec2.InstanceClass.BURSTABLE4_GRAVITON,
                ec2.InstanceSize.MICRO
            ),
            allocated_storage=20,
            max_allocated_storage=50,
            storage_encrypted=True,
            backup_retention=Duration.days(1),
            multi_az=False,
            publicly_accessible=False,
            vpc=self.vpc,
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_ISOLATED),
            security_groups=[self.database_security_group],
            deletion_protection=False,
            removal_policy=RemovalPolicy.DESTROY,
            delete_automated_backups=True
        )
        
        self.container_repository = ecr.Repository(
            self,
            "ContainerRepository",
            repository_name="video-processing",
            image_scan_on_push=True,
            lifecycle_rules=[
                ecr.LifecycleRule(max_image_count=10)
            ],
            removal_policy=RemovalPolicy.DESTROY,
            empty_on_delete=True,
        )
