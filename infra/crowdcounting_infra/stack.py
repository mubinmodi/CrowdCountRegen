"""One-stack deployment of CrowdCounting: a single GPU instance behind CloudFront.

Request path: viewer --HTTPS--> CloudFront --HTTP:80--> EC2 (security group admits only
CloudFront's origin-facing ranges) --> nginx container --> FastAPI container.
"""

from pathlib import Path

import aws_cdk as cdk
from aws_cdk import aws_cloudfront as cloudfront
from aws_cdk import aws_cloudfront_origins as origins
from aws_cdk import aws_cloudwatch as cloudwatch
from aws_cdk import aws_cloudwatch_actions as cw_actions
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_events as events
from aws_cdk import aws_iam as iam
from aws_cdk import aws_logs as logs
from aws_cdk import aws_s3_assets as s3_assets
from aws_cdk import aws_scheduler as scheduler
from aws_cdk import aws_secretsmanager as secretsmanager
from aws_cdk import aws_sns as sns
from aws_cdk import aws_sns_subscriptions as subscriptions
from aws_cdk import custom_resources as cr
from constructs import Construct

from crowdcounting_infra.monitoring import Monitoring
from crowdcounting_infra.protection import add_budget, add_web_acl

REPO_ROOT = Path(__file__).resolve().parents[2]
BOOTSTRAP_SCRIPT = Path(__file__).with_name("bootstrap.sh")

# AWS Deep Learning Base OSS NVIDIA Driver GPU AMI (Amazon Linux 2023): NVIDIA driver, Docker
# and nvidia-container-toolkit preinstalled. CloudFormation resolves this at deploy time.
DLAMI_SSM_PARAMETER = (
    "/aws/service/deeplearning/ami/x86_64/"
    "base-oss-nvidia-driver-gpu-amazon-linux-2023/latest/ami-id"
)
CLOUDFRONT_PREFIX_LIST = "com.amazonaws.global.cloudfront.origin-facing"

# Everything in the repo that the instance does not need to build the two images. The asset
# hash covers whatever is left, so any change to it replaces the instance on the next deploy.
ASSET_EXCLUDES = [
    ".git",
    ".github",
    ".claude",
    ".env",
    "**/.env",
    ".DS_Store",
    "**/.DS_Store",
    "infra",
    "docs",
    "videos",
    "data",
    "models",
    "*.md",
    "**/node_modules",
    "**/.venv",
    "**/__pycache__",
    "**/.pytest_cache",
    "**/.ruff_cache",
    "**/*.db",
    "**/*.db-*",
    "**/*.tsbuildinfo",
    "frontend/dist",
    "backend/data",
    "backend/models",
    "backend/tests",
    # Local dev TLS certificate and key (`npm run dev:lan`); never ship a private key.
    "backend/*.crt",
    "backend/*.key",
]


def _context_flag(scope: Construct, key: str) -> bool:
    value = scope.node.try_get_context(key)
    return value is True or str(value).lower() in {"true", "1", "yes"}


def _context_number(scope: Construct, key: str, default: float) -> float:
    value = scope.node.try_get_context(key)
    return float(value) if value not in (None, "") else default


class CrowdCountingStack(cdk.Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # --- Network: public subnets only, no NAT gateway --------------------------------
        azs = [
            az.strip()
            for az in str(self.node.try_get_context("crowdcounting:availabilityZones") or "").split(
                ","
            )
            if az.strip()
        ]
        vpc = ec2.Vpc(
            self,
            "Vpc",
            ip_addresses=ec2.IpAddresses.cidr("10.40.0.0/16"),
            nat_gateways=0,
            **({"availability_zones": azs} if azs else {"max_azs": 2}),
            subnet_configuration=[
                ec2.SubnetConfiguration(
                    name="public", subnet_type=ec2.SubnetType.PUBLIC, cidr_mask=24
                )
            ],
        )

        # --- Security group: HTTP from CloudFront only, no SSH ----------------------------
        # The managed prefix list id differs per account/region, so look it up when the stack
        # deploys (not at synth time). DescribeManagedPrefixLists has no resource-level IAM.
        prefix_list = cr.AwsCustomResource(
            self,
            "CloudFrontPrefixList",
            on_update=cr.AwsSdkCall(
                service="EC2",
                action="describeManagedPrefixLists",
                parameters={
                    "Filters": [{"Name": "prefix-list-name", "Values": [CLOUDFRONT_PREFIX_LIST]}]
                },
                physical_resource_id=cr.PhysicalResourceId.of(CLOUDFRONT_PREFIX_LIST),
                output_paths=["PrefixLists.0.PrefixListId"],
            ),
            policy=cr.AwsCustomResourcePolicy.from_sdk_calls(
                resources=cr.AwsCustomResourcePolicy.ANY_RESOURCE
            ),
            install_latest_aws_sdk=False,
        )
        prefix_list_id = prefix_list.get_response_field("PrefixLists.0.PrefixListId")

        security_group = ec2.SecurityGroup(
            self,
            "InstanceSg",
            vpc=vpc,
            description="CrowdCounting: HTTP from CloudFront origin-facing servers only",
            # Outbound: image builds pull from PyPI/npm/Docker Hub, the backend downloads model
            # weights and demo videos, and the SSM agent talks to its endpoints.
            allow_all_outbound=True,
        )
        # One rule referencing the prefix list counts as its max size (~55 entries) against
        # the 60-rules-per-security-group quota, so keep it the only inbound rule.
        security_group.add_ingress_rule(
            ec2.Peer.prefix_list(prefix_list_id),
            ec2.Port.tcp(80),
            "HTTP from CloudFront origin-facing servers",
        )

        # --- Secret key -------------------------------------------------------------------
        secret = secretsmanager.Secret(
            self,
            "SecretKey",
            description="CrowdCounting CC_SECRET_KEY (signs sessions, encrypts camera passwords)",
            generate_secret_string=secretsmanager.SecretStringGenerator(
                password_length=64, exclude_punctuation=True
            ),
            removal_policy=cdk.RemovalPolicy.DESTROY,
        )

        # --- App code, delivered as a zip through the CDK assets bucket -------------------
        app_source = s3_assets.Asset(
            self,
            "AppSource",
            path=str(REPO_ROOT),
            exclude=ASSET_EXCLUDES,
            ignore_mode=cdk.IgnoreMode.GLOB,
        )

        # --- Instance role: SSM Session Manager + read the asset and the secret -----------
        role = iam.Role(
            self,
            "InstanceRole",
            assumed_by=iam.ServicePrincipal("ec2.amazonaws.com"),
            description="CrowdCounting instance: SSM Session Manager, app asset, secret key",
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name("AmazonSSMManagedInstanceCore")
            ],
        )
        app_source.grant_read(role)
        secret.grant_read(role)

        # --- Logs: both containers, via Docker's awslogs driver (docker-compose.aws.yml) ---
        # The backend's Embedded Metric Format lines become CloudWatch metrics on arrival.
        log_group = logs.LogGroup(
            self,
            "AppLogs",
            log_group_name="/crowdcounting/demo",
            retention=logs.RetentionDays.TWO_WEEKS,
            removal_policy=cdk.RemovalPolicy.DESTROY,
        )
        role.add_to_policy(
            iam.PolicyStatement(
                actions=["logs:CreateLogStream", "logs:PutLogEvents"],
                resources=[log_group.log_group_arn, f"{log_group.log_group_arn}:log-stream:*"],
            )
        )

        # --- Cost controls passed to the app --------------------------------------------
        max_viewers = int(_context_number(self, "crowdcounting:maxVideoViewers", 40))
        schedule = _context_flag(self, "crowdcounting:schedule")

        # --- User data --------------------------------------------------------------------
        user_data = ec2.UserData.for_linux()
        script = BOOTSTRAP_SCRIPT.read_text()
        for placeholder, value in {
            "{{REGION}}": self.region,
            "{{ASSET_BUCKET}}": app_source.s3_bucket_name,
            "{{ASSET_KEY}}": app_source.s3_object_key,
            "{{SECRET_ARN}}": secret.secret_arn,
            "{{LOG_GROUP}}": log_group.log_group_name,
            "{{MAX_VIDEO_VIEWERS}}": str(max_viewers),
            "{{VIDEO_SESSION_MAX_S}}": str(
                _context_number(self, "crowdcounting:videoSessionMaxS", 1800)
            ),
            "{{VIDEO_IDLE_TIMEOUT_S}}": str(
                _context_number(self, "crowdcounting:videoIdleTimeoutS", 600)
            ),
        }.items():
            script = script.replace(placeholder, value)

        # --- Instance ---------------------------------------------------------------------
        instance = ec2.Instance(
            self,
            "Instance",
            vpc=vpc,
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC),
            # g4dn isn't offered in every AZ: -c crowdcounting:availabilityZones=us-east-1b,...
            # puts the instance in the first one listed (default: the VPC's first public subnet).
            availability_zone=azs[0] if azs else None,
            instance_type=ec2.InstanceType("g4dn.xlarge"),
            machine_image=self._machine_image(),
            role=role,
            security_group=security_group,
            associate_public_ip_address=True,
            block_devices=[
                ec2.BlockDevice(
                    device_name="/dev/xvda",
                    volume=ec2.BlockDeviceVolume.ebs(
                        100,
                        volume_type=ec2.EbsDeviceVolumeType.GP3,
                        encrypted=True,
                        delete_on_termination=True,
                    ),
                )
            ],
            # IMDSv2 only, hop limit 1: the host can read instance credentials, containers can't.
            http_tokens=ec2.HttpTokens.REQUIRED,
            http_put_response_hop_limit=1,
            user_data=user_data,
            # Immutable deploys: new code (asset hash) or a new AMI means a new instance.
            user_data_causes_replacement=True,
            # Wait for the bootstrap's cfn-signal (images build in ~10-20 min on first boot).
            resource_signal_timeout=cdk.Duration.minutes(45),
        )
        user_data.add_signal_on_exit_command(instance)
        user_data.add_commands(script)

        # --- Elastic IP: a stable origin across stop/start and instance replacement -------
        # CloudFront needs a DNS name, not an IP; EC2 publishes one for every public IPv4.
        # Associated through the EIP's own InstanceId: on a replacement CloudFormation moves the
        # address to the new instance in place (after it has signalled healthy), and the old
        # instance's cleanup can't disassociate it again.
        eip = ec2.CfnEIP(self, "Eip", domain="vpc", instance_id=instance.instance_id)
        dns_suffix = (
            "compute-1.amazonaws.com"
            if self.region == "us-east-1"
            else f"{self.region}.compute.amazonaws.com"
        )
        origin_domain = cdk.Fn.join(
            "", ["ec2-", cdk.Fn.join("-", cdk.Fn.split(".", eip.attr_public_ip)), f".{dns_suffix}"]
        )

        # --- Alerts: alarms and the budget notify one topic (optionally an email) ----------
        alerts = sns.Topic(self, "Alerts", display_name="CrowdCounting alerts", enforce_ssl=True)
        alerts.add_to_resource_policy(
            # Setting any statement replaces the default policy, so allow both publishers.
            iam.PolicyStatement(
                actions=["sns:Publish"],
                principals=[
                    iam.ServicePrincipal("cloudwatch.amazonaws.com"),
                    iam.ServicePrincipal("budgets.amazonaws.com"),
                ],
                resources=[alerts.topic_arn],
                conditions={"StringEquals": {"aws:SourceAccount": self.account}},
            )
        )
        email = str(self.node.try_get_context("crowdcounting:alertEmail") or "").strip()
        if email:
            alerts.add_subscription(subscriptions.EmailSubscription(email))

        # --- Edge protection: rate limiting and AWS managed rules ---------------------------
        web_acl = add_web_acl(
            self,
            rate_limit=int(_context_number(self, "crowdcounting:wafRateLimit", 2000)),
        )

        # --- CloudFront -------------------------------------------------------------------
        origin = origins.HttpOrigin(
            origin_domain,
            protocol_policy=cloudfront.OriginProtocolPolicy.HTTP_ONLY,
            http_port=80,
            # Max without a quota increase. MJPEG and WebSockets keep sending data, so this
            # only bounds the gap between bytes, not the stream's length.
            read_timeout=cdk.Duration.seconds(60),
            keepalive_timeout=cdk.Duration.seconds(60),
        )
        distribution = cloudfront.Distribution(
            self,
            "Distribution",
            comment="CrowdCounting demo",
            web_acl_id=web_acl.attr_arn,
            price_class=cloudfront.PriceClass.PRICE_CLASS_100,
            http_version=cloudfront.HttpVersion.HTTP2_AND_3,
            default_behavior=cloudfront.BehaviorOptions(
                origin=origin,
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                allowed_methods=cloudfront.AllowedMethods.ALLOW_ALL,
                # API, MJPEG streams and WebSockets: never cache, forward everything.
                cache_policy=cloudfront.CachePolicy.CACHING_DISABLED,
                origin_request_policy=cloudfront.OriginRequestPolicy.ALL_VIEWER,
                compress=False,
            ),
            additional_behaviors={
                # Vite's content-hashed JS/CSS bundles.
                "/assets/*": cloudfront.BehaviorOptions(
                    origin=origin,
                    viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                    allowed_methods=cloudfront.AllowedMethods.ALLOW_GET_HEAD,
                    cache_policy=cloudfront.CachePolicy.CACHING_OPTIMIZED,
                    compress=True,
                ),
            },
        )

        # --- Health: reboot on a failed instance check, restart on a failed host check ----
        # EC2's CloudWatch "recover" action isn't supported on g4dn (it has instance store
        # volumes), so a failed system check runs AWS-RestartEC2Instance (stop + start), which
        # moves the instance to healthy hardware. The Elastic IP keeps the origin unchanged.
        def status_alarm(alarm_id: str, metric_name: str) -> cloudwatch.Alarm:
            return cloudwatch.Alarm(
                self,
                alarm_id,
                alarm_description=f"CrowdCounting instance {metric_name}",
                metric=cloudwatch.Metric(
                    namespace="AWS/EC2",
                    metric_name=metric_name,
                    dimensions_map={"InstanceId": instance.instance_id},
                    statistic=cloudwatch.Stats.MAXIMUM,
                    period=cdk.Duration.minutes(1),
                ),
                threshold=1,
                comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
                evaluation_periods=3,
                # A stopped instance (nightly schedule) reports nothing; that's not a failure.
                treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
            )

        instance_alarm = status_alarm("InstanceCheckAlarm", "StatusCheckFailed_Instance")
        instance_alarm.add_alarm_action(cw_actions.Ec2Action(cw_actions.Ec2InstanceAction.REBOOT))
        instance_alarm.add_alarm_action(cw_actions.SnsAction(alerts))

        system_alarm = status_alarm("SystemCheckAlarm", "StatusCheckFailed_System")
        system_alarm.add_alarm_action(cw_actions.SnsAction(alerts))
        restart_role = iam.Role(
            self,
            "RestartRole",
            assumed_by=iam.ServicePrincipal("events.amazonaws.com"),
            description="Lets EventBridge restart the CrowdCounting instance via SSM Automation",
        )

        def automation_definition(version: str) -> str:
            return self.format_arn(
                service="ssm",
                resource="automation-definition",
                resource_name=f"AWS-RestartEC2Instance:{version}",
                arn_format=cdk.ArnFormat.SLASH_RESOURCE_NAME,
            )

        automation_arn = automation_definition("$DEFAULT")
        instance_arn = self.format_arn(
            service="ec2", resource="instance", resource_name=instance.instance_id
        )
        restart_role.add_to_policy(
            iam.PolicyStatement(
                actions=["ssm:StartAutomationExecution"], resources=[automation_definition("*")]
            )
        )
        restart_role.add_to_policy(
            iam.PolicyStatement(
                actions=["ec2:StopInstances", "ec2:StartInstances"], resources=[instance_arn]
            )
        )
        restart_role.add_to_policy(
            # Describe calls have no resource-level permissions.
            iam.PolicyStatement(
                actions=["ec2:DescribeInstances", "ec2:DescribeInstanceStatus"], resources=["*"]
            )
        )
        events.CfnRule(
            self,
            "SystemCheckRestartRule",
            description="Stop and start the CrowdCounting instance when its host check fails",
            event_pattern={
                "source": ["aws.cloudwatch"],
                "detail-type": ["CloudWatch Alarm State Change"],
                "resources": [system_alarm.alarm_arn],
                "detail": {"state": {"value": ["ALARM"]}},
            },
            targets=[
                events.CfnRule.TargetProperty(
                    id="RestartInstance",
                    arn=automation_arn,
                    role_arn=restart_role.role_arn,
                    input=cdk.Fn.to_json_string({"InstanceId": [instance.instance_id]}),
                )
            ],
        )

        # --- Optional nightly stop / morning start ----------------------------------------
        if schedule:
            self._add_schedule(instance, instance_arn)

        # --- App metrics: alarms and a dashboard ------------------------------------------
        monitoring = Monitoring(
            self,
            "Monitoring",
            alerts=alerts,
            log_group=log_group,
            distribution=distribution,
            max_video_viewers=max_viewers,
            # A stopped instance sends no metrics; only treat silence as an outage when the
            # instance is meant to be on around the clock.
            expect_always_on=not schedule,
            extra_alarms=[instance_alarm, system_alarm],
        )

        # --- Monthly budget ---------------------------------------------------------------
        add_budget(
            self,
            monthly_usd=_context_number(self, "crowdcounting:monthlyBudgetUsd", 450),
            topic=alerts,
        )

        # --- Outputs ----------------------------------------------------------------------
        cdk.CfnOutput(
            self,
            "Url",
            value=f"https://{distribution.distribution_domain_name}",
            description="Public HTTPS URL of the demo",
        )
        cdk.CfnOutput(self, "InstanceId", value=instance.instance_id)
        cdk.CfnOutput(
            self,
            "SsmSessionCommand",
            value=f"aws ssm start-session --target {instance.instance_id} --region {self.region}",
            description="Shell on the instance (needs the Session Manager plugin for the AWS CLI)",
        )
        cdk.CfnOutput(self, "SecretArn", value=secret.secret_arn)
        cdk.CfnOutput(self, "AlertsTopicArn", value=alerts.topic_arn)
        cdk.CfnOutput(self, "DashboardUrl", value=monitoring.dashboard_url)

        self._acknowledge_findings(
            role=role,
            restart_role=restart_role,
            secret=secret,
            instance=instance,
            vpc=vpc,
            distribution=distribution,
            prefix_list=prefix_list,
            alerts=alerts,
        )

    def _machine_image(self) -> ec2.IMachineImage:
        # Default: the latest DLAMI, resolved by CloudFormation on every deploy (a newer AMI
        # replaces the instance). -c crowdcounting:amiId=ami-... pins one instead.
        ami_id = str(self.node.try_get_context("crowdcounting:amiId") or "").strip()
        if ami_id:
            return ec2.MachineImage.generic_linux({self.region: ami_id})
        return ec2.MachineImage.from_ssm_parameter(
            DLAMI_SSM_PARAMETER, os=ec2.OperatingSystemType.LINUX
        )

    def _add_schedule(self, instance: ec2.Instance, instance_arn: str) -> None:
        timezone = str(self.node.try_get_context("crowdcounting:timezone") or "America/New_York")
        role = iam.Role(
            self,
            "SchedulerRole",
            assumed_by=iam.ServicePrincipal(
                "scheduler.amazonaws.com",
                conditions={"StringEquals": {"aws:SourceAccount": self.account}},
            ),
            description="Lets EventBridge Scheduler stop and start the CrowdCounting instance",
        )
        role.add_to_policy(
            iam.PolicyStatement(
                actions=["ec2:StopInstances", "ec2:StartInstances"], resources=[instance_arn]
            )
        )
        for schedule_id, action, context_key, default in (
            ("StopSchedule", "stopInstances", "crowdcounting:stopCron", "cron(0 23 * * ? *)"),
            ("StartSchedule", "startInstances", "crowdcounting:startCron", "cron(0 8 * * ? *)"),
        ):
            scheduler.CfnSchedule(
                self,
                schedule_id,
                description=f"CrowdCounting: {action} on a schedule",
                schedule_expression=str(self.node.try_get_context(context_key) or default),
                schedule_expression_timezone=timezone,
                flexible_time_window=scheduler.CfnSchedule.FlexibleTimeWindowProperty(mode="OFF"),
                target=scheduler.CfnSchedule.TargetProperty(
                    arn=f"arn:{self.partition}:scheduler:::aws-sdk:ec2:{action}",
                    role_arn=role.role_arn,
                    input=cdk.Fn.to_json_string({"InstanceIds": [instance.instance_id]}),
                ),
            )

    def _acknowledge_findings(
        self,
        *,
        role: iam.Role,
        restart_role: iam.Role,
        secret: secretsmanager.Secret,
        instance: ec2.Instance,
        vpc: ec2.Vpc,
        distribution: cloudfront.Distribution,
        prefix_list: cr.AwsCustomResource,
        alerts: sns.Topic,
    ) -> None:
        """cdk-nag findings that are deliberate trade-offs for a single-instance demo."""

        def ack(construct: Construct, rule_id: str, reason: str) -> None:
            cdk.Validations.of(construct).acknowledge(cdk.Acknowledgment(id=rule_id, reason=reason))

        ack(
            role,
            "AwsSolutions-IAM4[Policy::arn:<AWS::Partition>:iam::aws:policy/AmazonSSMManagedInstanceCore]",
            "AmazonSSMManagedInstanceCore is the AWS-maintained minimum for Session Manager, which "
            "replaces SSH on this instance.",
        )
        for finding in (
            "Action::s3:GetBucket*",
            "Action::s3:GetObject*",
            "Action::s3:List*",
            "Resource::arn:<AWS::Partition>:s3:::cdk-hnb659fds-assets-<AWS::AccountId>-us-east-1/*",
        ):
            ack(
                role,
                f"AwsSolutions-IAM5[{finding}]",
                "Generated by Asset.grant_read: read-only access to the CDK assets bucket, which "
                "the instance needs to download the app source zip.",
            )
        ack(
            role,
            "AwsSolutions-IAM5[Resource::<AppLogsC5DF83A6.Arn>:log-stream:*]",
            "Docker's awslogs driver creates one stream per container (named after the container "
            "id), so stream names aren't known in advance. Scoped to this app's own log group.",
        )
        ack(
            restart_role,
            "AwsSolutions-IAM5[Resource::arn:<AWS::Partition>:ssm:us-east-1:<AWS::AccountId>:"
            "automation-definition/AWS-RestartEC2Instance:*]",
            "Any version of the one AWS-owned AWS-RestartEC2Instance runbook.",
        )
        ack(
            restart_role,
            "AwsSolutions-IAM5[Resource::*]",
            "ec2:DescribeInstances/DescribeInstanceStatus (used by AWS-RestartEC2Instance) have "
            "no resource-level permissions. Stop/Start are scoped to this instance.",
        )
        ack(
            secret,
            "AwsSolutions-SMG4",
            "Not rotated: CC_SECRET_KEY signs sessions and derives the key that encrypts stored "
            "camera passwords, so rotating it would invalidate both. It is read once at boot.",
        )
        ack(
            instance,
            "AwsSolutions-EC28",
            "Basic (5-minute) monitoring is enough for a single demo instance; the status-check "
            "alarms use the 1-minute status metrics, which are free.",
        )
        ack(
            instance,
            "AwsSolutions-EC29",
            "Immutable deploys replace the instance on every code change; termination protection "
            "would block that. It is a single stateless-by-design demo (data is reseeded on boot), "
            "not part of an Auto Scaling group.",
        )
        ack(
            alerts,
            "AwsSolutions-SNS2",
            "Alert notifications carry no sensitive data (alarm names and budget figures). "
            "Server-side encryption would need a customer managed KMS key, since CloudWatch "
            "and Budgets can't publish to topics encrypted with the AWS managed SNS key.",
        )
        ack(
            vpc,
            "AwsSolutions-VPC7",
            "No VPC flow logs for the demo: the VPC holds one instance whose only inbound path is "
            "CloudFront. Enable flow logs before production use.",
        )
        for rule_id, reason in (
            (
                "AwsSolutions-CFR1",
                "Public demo meant to be reachable worldwide; no geo restriction.",
            ),
            (
                "AwsSolutions-CFR3",
                "No CloudFront access logs for the demo (cost, and the stream traffic would make "
                "them large). Enable standard logging for production.",
            ),
            (
                "AwsSolutions-CFR4",
                "Uses the default *.cloudfront.net certificate (no custom domain), which cannot "
                "enforce a minimum viewer TLS version. Add a domain + ACM cert to require TLS 1.2.",
            ),
            (
                "AwsSolutions-CFR5",
                "The origin is plain HTTP on port 80, reachable only from CloudFront's "
                "origin-facing ranges (security group + managed prefix list). The instance has no "
                "certificate.",
            ),
        ):
            ack(distribution, rule_id, reason)

        # The AwsCustomResource that looks up the CloudFront prefix list runs on a CDK-managed
        # singleton Lambda function.
        provider = self.node.try_find_child(
            "AWS" + cr.AwsCustomResource.PROVIDER_FUNCTION_UUID.replace("-", "")
        )
        targets: list[Construct] = [prefix_list]
        if provider is not None:
            targets.append(provider)
        for target in targets:
            ack(
                target,
                "AwsSolutions-IAM5[Resource::*]",
                "ec2:DescribeManagedPrefixLists has no resource-level permissions; the call is "
                "read-only and runs once per deploy.",
            )
        if provider is not None:
            ack(
                provider,
                "AwsSolutions-IAM4[Policy::arn:<AWS::Partition>:iam::aws:policy/service-role/"
                "AWSLambdaBasicExecutionRole]",
                "CDK-managed provider function for AwsCustomResource; the AWS managed basic "
                "execution policy only grants writing its own CloudWatch Logs.",
            )
