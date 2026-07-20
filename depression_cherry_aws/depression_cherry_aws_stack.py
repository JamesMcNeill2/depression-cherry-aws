from aws_cdk import (
    Stack,
    Duration,
    RemovalPolicy,
    aws_lambda as _lambda,
    aws_logs as logs,
    aws_ssm as ssm
)
from constructs import Construct

class DepressionCherryAwsStack(Stack):

    def __init__(self, scope: Construct, construct_id: str, env_name: str, env_suffix: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        log_group = logs.LogGroup(
            self, "NasaLogGroup",
            retention=logs.RetentionDays.ONE_WEEK,
            removal_policy=RemovalPolicy.DESTROY,
        )

        prefix = f"/depression-cherry/shared"

        fn = _lambda.Function(
            self, "Nasa",
            function_name=f"Nasa-{env_suffix}",
            runtime=_lambda.Runtime.PYTHON_3_13,
            handler="nasa.lambda_handler",
            code=_lambda.Code.from_asset("lambda"),
            environment={
                "PARAM_PREFIX": prefix,
                "ENV_NAME": env_name
            },
            timeout=Duration.seconds(120),           # 2 min
            log_group=log_group
            )
        
        for name in ["nasa-api-key", "gmail-password", "email-from", "email-to"]:
            ssm.StringParameter.from_secure_string_parameter_attributes(
                self, f"Param{name.title().replace('-', '')}",
                parameter_name=f"/{prefix}/{name}"
            ).grant_read(fn)