#!/usr/bin/env python3
import os
import re
import aws_cdk as cdk
from depression_cherry_aws.depression_cherry_aws_stack import DepressionCherryAwsStack

app = cdk.App()

env=cdk.Environment(
    account=os.getenv("CDK_DEFAULT_ACCOUNT"),
    region=os.getenv("CDK_DEFAULT_REGION", "eu-west-2"))

def get_env_suffix(branch: str) -> str:
    if branch == "main":
        return "prod"
    if branch == "dev":
        return "dev"
    
    # feature/branch-name -> feature-branch-name
    suffix = branch.lower()
    suffix = re.sub(r"[^a-z0-9-]", "-", suffix)
    suffix = re.sub(r"-+", "-", suffix).strip("-")
    return suffix[:40]

branch_name = os.getenv("BRANCH_NAME", "dev")
print(branch_name)
env_suffix = get_env_suffix(branch_name)

env_name = env_suffix.replace("-", " ").title().replace(" ", "")

DepressionCherryAwsStack(
    app,
    f"DepressionCherryAwsStack-{env_suffix}",
    env_name=env_name,
    env_suffix=env_suffix,
    env=env
    )

app.synth()