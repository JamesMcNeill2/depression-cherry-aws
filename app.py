#!/usr/bin/env python3
import os
import aws_cdk as cdk
from depression_cherry_aws.depression_cherry_aws_stack import DepressionCherryAwsStack

app = cdk.App()

env=cdk.Environment(account=os.getenv("CDK_DEFAULT_ACCOUNT"),
                    region=os.getenv("CDK_DEFAULT_REGION", "eu-west-2"))

DepressionCherryAwsStack(app, "ProdStack", env=env)
DepressionCherryAwsStack(app, "DevStack", env=env)

app.synth()