from aws_cdk import CfnOutput, Stack, aws_ec2 as ec2, aws_ecr as ecr, aws_ecs as ecs, aws_elasticloadbalancingv2 as elbv2
from constructs import Construct

class ServicesStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, *, vpc: ec2.IVpc, container_repository: ecr.IRepository, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)
        
        self.vpc = vpc
        self.container_repository = container_repository
        
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
        
        api_container = self.api_task_definition.add_container(
            "ApiContainer",
            image=ecs.ContainerImage.from_ecr_repository(
                self.container_repository,
                tag="latest"
            ),
            logging=ecs.LogDrivers.aws_logs(stream_prefix="api")
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
        
        self.api_service = ecs.FargateService(
            self,
            "ApiService",
            cluster=self.cluster,
            task_definition=self.api_task_definition,
            desired_count=1,
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