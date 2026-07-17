from aws_cdk import (
    Stack,
    Duration,
    RemovalPolicy,
    aws_lambda as _lambda,
    aws_logs as logs
)
from constructs import Construct

class DepressionCherryAwsStack(Stack):

    def __init__(self, scope: Construct, construct_id: str, env_name: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        log_group = logs.LogGroup(
            self, "NasaLogGroup",
            retention=logs.RetentionDays.ONE_WEEK,
            removal_policy=RemovalPolicy.DESTROY,
        )

        _lambda.Function(
            self, "Nasa",
            function_name=f"Nasa-{env_name}",
            runtime=_lambda.Runtime.PYTHON_3_13,
            handler="nasa.lambda_handler",
            code=_lambda.Code.from_asset("lambda"),
            timeout=Duration.seconds(120),           # 2 min
            log_group=log_group
            )