"""Alarms and a dashboard on the app's own metrics.

The backend publishes CloudWatch Embedded Metric Format lines (namespace Zonewatch) every
minute: per camera (dimension CameraId) FPS, Occupancy, Alerting and Reconnects, and for the
fleet Cameras, CamerasRunning, CamerasStalled, CamerasAlerting, IncidentsOpen, VideoViewers,
Inferences, InferenceMs and LockWaitMs. See backend/app/metrics.py.
"""

import aws_cdk as cdk
from aws_cdk import aws_cloudfront as cloudfront
from aws_cdk import aws_cloudwatch as cw
from aws_cdk import aws_cloudwatch_actions as cw_actions
from aws_cdk import aws_logs as logs
from aws_cdk import aws_sns as sns
from constructs import Construct

NAMESPACE = "Zonewatch"
MINUTE = cdk.Duration.minutes(1)


def app_metric(name: str, statistic: str = cw.Stats.MAXIMUM, period=MINUTE) -> cw.Metric:
    return cw.Metric(namespace=NAMESPACE, metric_name=name, statistic=statistic, period=period)


def per_camera(name: str, statistic: str = "Average") -> cw.MathExpression:
    """One line per camera, whatever cameras exist (they come and go in the demo)."""
    return cw.MathExpression(
        expression=f"SEARCH('{{{NAMESPACE},CameraId}} MetricName=\"{name}\"', '{statistic}', 60)",
        using_metrics={},
        label="",
        period=MINUTE,
    )


class Monitoring(Construct):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        alerts: sns.ITopic,
        log_group: logs.ILogGroup,
        distribution: cloudfront.Distribution,
        max_video_viewers: int,
        expect_always_on: bool,
        extra_alarms: list[cw.IAlarm],
    ) -> None:
        super().__init__(scope, construct_id)
        notify = cw_actions.SnsAction(alerts)

        stalled = cw.Alarm(
            self,
            "CamerasStalled",
            alarm_description=(
                "A camera has been in error or reconnecting for 5 minutes. Check its stream "
                "health page and the app logs."
            ),
            metric=app_metric("CamerasStalled"),
            threshold=1,
            comparison_operator=cw.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
            evaluation_periods=5,
            treat_missing_data=cw.TreatMissingData.NOT_BREACHING,
        )
        # The backend reports every minute while it's up; silence means it's down (or, with
        # the nightly schedule, stopped on purpose, so then silence is ignored).
        down = cw.Alarm(
            self,
            "BackendDown",
            alarm_description=(
                "No camera has been running for 10 minutes, or the backend stopped reporting "
                "metrics. Check the instance and the backend container."
            ),
            metric=app_metric("CamerasRunning", period=cdk.Duration.minutes(5)),
            threshold=1,
            comparison_operator=cw.ComparisonOperator.LESS_THAN_THRESHOLD,
            evaluation_periods=2,
            treat_missing_data=(
                cw.TreatMissingData.BREACHING if expect_always_on else cw.TreatMissingData.IGNORE
            ),
        )
        # Cameras share one model behind a lock. Waiting more than twice as long for the
        # accelerator as using it means it is saturated: lower ZW_MAX_FPS or the image size.
        saturated = cw.Alarm(
            self,
            "DetectorSaturated",
            alarm_description=(
                "Cameras wait more than twice as long for the detector as inference takes. "
                "Lower ZW_MAX_FPS or ZW_DETECTOR_IMGSZ, or use a bigger GPU."
            ),
            metric=cw.MathExpression(
                expression="IF(infer > 0, wait / infer, 0)",
                using_metrics={
                    "wait": app_metric("LockWaitMs", cw.Stats.AVERAGE, cdk.Duration.minutes(5)),
                    "infer": app_metric("InferenceMs", cw.Stats.AVERAGE, cdk.Duration.minutes(5)),
                },
                label="Lock wait / inference time",
                period=cdk.Duration.minutes(5),
            ),
            threshold=2,
            comparison_operator=cw.ComparisonOperator.GREATER_THAN_THRESHOLD,
            evaluation_periods=3,
            treat_missing_data=cw.TreatMissingData.NOT_BREACHING,
        )
        busy = cw.Alarm(
            self,
            "ViewersNearLimit",
            alarm_description=(
                f"Video viewers reached 80% of the cap ({max_video_viewers}). Above the cap, "
                "visitors get counts but no video. Raise zonewatch:maxVideoViewers if "
                "egress cost allows."
            ),
            metric=app_metric("VideoViewers", period=cdk.Duration.minutes(5)),
            threshold=max(1, int(max_video_viewers * 0.8)),
            comparison_operator=cw.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
            evaluation_periods=1,
            treat_missing_data=cw.TreatMissingData.NOT_BREACHING,
        )
        alarms: list[cw.IAlarm] = [stalled, down, saturated, busy]
        for alarm in alarms:
            alarm.add_alarm_action(notify)
            alarm.add_ok_action(notify)

        # CloudFront metrics live in us-east-1 with Region=Global.
        def edge(name: str, statistic: str) -> cw.Metric:
            return cw.Metric(
                namespace="AWS/CloudFront",
                metric_name=name,
                dimensions_map={"DistributionId": distribution.distribution_id, "Region": "Global"},
                statistic=statistic,
                period=cdk.Duration.minutes(5),
                region="us-east-1",
            )

        dashboard = cw.Dashboard(
            self,
            "Dashboard",
            dashboard_name="Zonewatch",
            default_interval=cdk.Duration.hours(3),
        )
        dashboard.add_widgets(
            cw.AlarmStatusWidget(title="Alarms", alarms=alarms + extra_alarms, width=24, height=3),
        )
        dashboard.add_widgets(
            cw.GraphWidget(
                title="Cameras",
                left=[
                    app_metric(n)
                    for n in ("Cameras", "CamerasRunning", "CamerasStalled", "CamerasAlerting")
                ],
                width=8,
            ),
            cw.GraphWidget(
                title="Detector (ms): inference vs. waiting for the lock",
                left=[
                    app_metric("InferenceMs", cw.Stats.AVERAGE),
                    app_metric("LockWaitMs", cw.Stats.AVERAGE),
                ],
                right=[app_metric("Inferences", cw.Stats.SUM)],
                width=8,
            ),
            cw.GraphWidget(
                title="Video viewers and open incidents",
                left=[app_metric("VideoViewers"), app_metric("IncidentsOpen")],
                left_annotations=[
                    cw.HorizontalAnnotation(value=max_video_viewers, label="viewer cap")
                ],
                width=8,
            ),
        )
        dashboard.add_widgets(
            cw.GraphWidget(title="FPS per camera", left=[per_camera("FPS")], width=12),
            cw.GraphWidget(
                title="People in zone per camera", left=[per_camera("Occupancy")], width=12
            ),
        )
        dashboard.add_widgets(
            cw.GraphWidget(
                title="CloudFront egress (bytes / 5 min): the cost that grows with viewers",
                left=[edge("BytesDownloaded", cw.Stats.SUM)],
                width=8,
            ),
            cw.GraphWidget(
                title="CloudFront requests and error rates",
                left=[edge("Requests", cw.Stats.SUM)],
                right=[
                    edge("4xxErrorRate", cw.Stats.AVERAGE),
                    edge("5xxErrorRate", cw.Stats.AVERAGE),
                ],
                width=8,
            ),
            cw.LogQueryWidget(
                title="Recent errors",
                log_group_names=[log_group.log_group_name],
                query_lines=[
                    "fields @timestamp, @logStream, @message",
                    "filter @message like /(?i)(error|exception|traceback)/",
                    "filter @message not like /_aws/",
                    "sort @timestamp desc",
                    "limit 50",
                ],
                width=8,
            ),
        )

        self.dashboard_url = (
            f"https://{cdk.Aws.REGION}.console.aws.amazon.com/cloudwatch/home"
            f"?region={cdk.Aws.REGION}#dashboards/dashboard/Zonewatch"
        )
