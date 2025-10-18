"""CDK stack defining the ECS Fargate infrastructure for the backend."""

from __future__ import annotations

from aws_cdk import CfnOutput, Duration, RemovalPolicy, Stack
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_ecr as ecr
from aws_cdk import aws_ecs as ecs
from aws_cdk import aws_ecs_patterns as ecs_patterns
from aws_cdk import aws_logs as logs
from constructs import Construct


class AieDxprojectBackendStack(Stack):
    """Provision network, container registry, and ECS Fargate service for the backend."""

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        vpc = ec2.Vpc(
            self,
            "Vpc",
            max_azs=2,
            nat_gateways=1,
            subnet_configuration=[
                ec2.SubnetConfiguration(
                    name="Public",
                    subnet_type=ec2.SubnetType.PUBLIC,
                    cidr_mask=24,
                ),
                ec2.SubnetConfiguration(
                    name="Private",
                    subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS,
                    cidr_mask=24,
                ),
            ],
        )

        repository = ecr.Repository(
            self,
            "Repository",
            repository_name="aie-dxproject-backend",
            image_scan_on_push=True,
            lifecycle_rules=[
                ecr.LifecycleRule(
                    description="Keep the 10 most recent images",
                    max_image_count=10,
                ),
            ],
            removal_policy=RemovalPolicy.RETAIN,
            empty_on_delete=False,
        )

        cluster = ecs.Cluster(
            self,
            "Cluster",
            vpc=vpc,
            container_insights=True,
        )

        use_sample_image = (
            str(self.node.try_get_context("use_sample_image")).lower() != "false"
        )
        image_tag = self.node.try_get_context("image_tag") or "latest"

        if use_sample_image:
            container_image = ecs.ContainerImage.from_registry(
                "public.ecr.aws/docker/library/nginx:stable-alpine"
            )
        else:
            container_image = ecs.ContainerImage.from_ecr_repository(
                repository,
                tag=image_tag,
            )

        fargate_service = ecs_patterns.ApplicationLoadBalancedFargateService(
            self,
            "FargateService",
            cluster=cluster,
            cpu=512,
            memory_limit_mib=1024,
            desired_count=1,
            public_load_balancer=True,
            listener_port=80,
            task_image_options=ecs_patterns.ApplicationLoadBalancedTaskImageOptions(
                image=container_image,
                container_port=8000,
                log_driver=ecs.LogDriver.aws_logs(
                    stream_prefix="backend",
                    log_retention=logs.RetentionDays.ONE_WEEK,
                ),
                environment={
                    "APP_ENV": "production",
                },
            ),
        )

        fargate_service.target_group.configure_health_check(
            path="/health",
            interval=Duration.seconds(30),
            healthy_http_codes="200-399",
        )

        CfnOutput(
            self,
            "EcrRepositoryUri",
            description="URI of the ECR repository for backend images",
            value=repository.repository_uri,
        )
        CfnOutput(
            self,
            "LoadBalancerDns",
            description="Public endpoint for the backend service",
            value=fargate_service.load_balancer.load_balancer_dns_name,
        )
        CfnOutput(
            self,
            "ClusterName",
            description="ECS cluster name",
            value=cluster.cluster_name,
        )
