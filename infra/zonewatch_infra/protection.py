"""Edge protection (AWS WAF on CloudFront) and the monthly cost budget."""

import aws_cdk as cdk
from aws_cdk import aws_budgets as budgets
from aws_cdk import aws_sns as sns
from aws_cdk import aws_wafv2 as wafv2
from constructs import Construct


def _visibility(name: str) -> wafv2.CfnWebACL.VisibilityConfigProperty:
    return wafv2.CfnWebACL.VisibilityConfigProperty(
        cloud_watch_metrics_enabled=True, metric_name=name, sampled_requests_enabled=True
    )


def _managed(name: str, priority: int) -> wafv2.CfnWebACL.RuleProperty:
    return wafv2.CfnWebACL.RuleProperty(
        name=name,
        priority=priority,
        statement=wafv2.CfnWebACL.StatementProperty(
            managed_rule_group_statement=wafv2.CfnWebACL.ManagedRuleGroupStatementProperty(
                vendor_name="AWS", name=name
            )
        ),
        override_action=wafv2.CfnWebACL.OverrideActionProperty(none={}),
        visibility_config=_visibility(name),
    )


def add_web_acl(scope: cdk.Stack, *, rate_limit: int) -> wafv2.CfnWebACL:
    """A web ACL for the distribution. CLOUDFRONT-scoped ACLs must live in us-east-1, which
    is where this stack deploys.

    Rules, in order: a per-IP rate limit (a 429 for anyone over `rate_limit` requests in 5
    minutes), then AWS's IP reputation list and known-bad-inputs rules. The common rule set
    is left out on purpose: its body-size and size-restriction rules flag legitimate API
    calls, and WAF only ever sees a WebSocket's opening request, not its frames.

    Budget for rate_limit: a page load is about 15 requests, the incidents page fetches up
    to 200 cached thumbnails once, and video/status are a handful of long-lived connections.
    """
    if not cdk.Token.is_unresolved(scope.region) and scope.region != "us-east-1":
        raise ValueError("A CloudFront web ACL must be created in us-east-1")
    return wafv2.CfnWebACL(
        scope,
        "WebAcl",
        scope="CLOUDFRONT",
        description="Zonewatch demo: per-IP rate limit and AWS managed rules",
        default_action=wafv2.CfnWebACL.DefaultActionProperty(allow={}),
        visibility_config=_visibility("Zonewatch"),
        rules=[
            wafv2.CfnWebACL.RuleProperty(
                name="RateLimitPerIp",
                priority=0,
                statement=wafv2.CfnWebACL.StatementProperty(
                    rate_based_statement=wafv2.CfnWebACL.RateBasedStatementProperty(
                        limit=rate_limit, aggregate_key_type="IP", evaluation_window_sec=300
                    )
                ),
                action=wafv2.CfnWebACL.RuleActionProperty(
                    block=wafv2.CfnWebACL.BlockActionProperty(
                        custom_response=wafv2.CfnWebACL.CustomResponseProperty(response_code=429)
                    )
                ),
                visibility_config=_visibility("RateLimitPerIp"),
            ),
            _managed("AWSManagedRulesAmazonIpReputationList", 1),
            _managed("AWSManagedRulesKnownBadInputsRuleSet", 2),
        ],
    )


def add_budget(scope: Construct, *, monthly_usd: float, topic: sns.ITopic) -> None:
    """A monthly cost budget for resources tagged Project=Zonewatch, notifying the alerts
    topic when actual spend passes 80% or the month's forecast passes 100%.

    The tag filter only works once Project is activated as a cost allocation tag (Billing
    console → Cost allocation tags); until then the budget sees no costs, so the doc says to
    activate it. Budgets are account-wide and free for the first two.
    """

    def notify(kind: str, percent: float) -> budgets.CfnBudget.NotificationWithSubscribersProperty:
        return budgets.CfnBudget.NotificationWithSubscribersProperty(
            notification=budgets.CfnBudget.NotificationProperty(
                notification_type=kind,
                comparison_operator="GREATER_THAN",
                threshold=percent,
                threshold_type="PERCENTAGE",
            ),
            subscribers=[
                budgets.CfnBudget.SubscriberProperty(
                    subscription_type="SNS", address=topic.topic_arn
                )
            ],
        )

    budgets.CfnBudget(
        scope,
        "Budget",
        budget=budgets.CfnBudget.BudgetDataProperty(
            budget_name="Zonewatch-monthly",
            budget_type="COST",
            time_unit="MONTHLY",
            budget_limit=budgets.CfnBudget.SpendProperty(amount=monthly_usd, unit="USD"),
            cost_filters={"TagKeyValue": ["user:Project$Zonewatch"]},
        ),
        notifications_with_subscribers=[notify("ACTUAL", 80), notify("FORECASTED", 100)],
    )
