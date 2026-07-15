import aws_cdk as core
import aws_cdk.assertions as assertions

from depression_cherry_aws.depression_cherry_aws_stack import DepressionCherryAwsStack

# example tests. To run these tests, uncomment this file along with the example
# resource in depression_cherry_aws/depression_cherry_aws_stack.py
def test_sqs_queue_created():
    app = core.App()
    stack = DepressionCherryAwsStack(app, "depression-cherry-aws")
    template = assertions.Template.from_stack(stack)

#     template.has_resource_properties("AWS::SQS::Queue", {
#         "VisibilityTimeout": 300
#     })
