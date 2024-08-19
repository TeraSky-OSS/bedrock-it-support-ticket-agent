import boto3
import json
import time
import zipfile
import logging
import pprint
from io import BytesIO

iam_client = boto3.client('iam')
sts_client = boto3.client('sts')
session = boto3.session.Session()
region = session.region_name
account_id = sts_client.get_caller_identity()["Account"]
dynamodb_client = boto3.client('dynamodb')
dynamodb_resource = boto3.resource('dynamodb')
lambda_client = boto3.client('lambda')
bedrock_agent_client = boto3.client('bedrock-agent')
bedrock_agent_runtime_client = boto3.client('bedrock-agent-runtime')
logging.basicConfig(format='[%(asctime)s] p%(process)s {%(filename)s:%(lineno)d} %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)


def create_dynamodb(table_name , attribute_name):
    try:
        table = dynamodb_resource.create_table(
            TableName=table_name,
            KeySchema=[
                {
                    'AttributeName': attribute_name,
                    'KeyType': 'HASH'
                }
            ],
            AttributeDefinitions=[
                {
                    'AttributeName': attribute_name,
                    'AttributeType': 'S'
                }
            ],
            BillingMode='PAY_PER_REQUEST'  # Use on-demand capacity mode
        )

        # Wait for the table to be created
        print(f'Creating table {table_name}...')
        table.wait_until_exists()
        print(f'Table {table_name} created successfully!')
    except dynamodb_client.exceptions.ResourceInUseException:
        print(f'Table {table_name} already exists, skipping table creation step')


def create_lambda(lambda_function_name, lambda_iam_role):
    # add to function

    # Package up the lambda function code
    s = BytesIO()
    z = zipfile.ZipFile(s, 'w')
    z.write("lambda_function.py")
    z.close()
    zip_content = s.getvalue()
    try:
        # Create Lambda Function
        lambda_function = lambda_client.create_function(
            FunctionName=lambda_function_name,
            Runtime='python3.12',
            Timeout=60,
            Role=lambda_iam_role['Role']['Arn'],
            Code={'ZipFile': zip_content},
            Handler='lambda_function.lambda_handler'
        )
    except lambda_client.exceptions.ResourceConflictException:
        print("Lambda function already exists, retrieving it")
        lambda_function = lambda_client.get_function(
            FunctionName=lambda_function_name
        )
        lambda_function = lambda_function['Configuration']

    return lambda_function


def create_lambda_role(agent_name, dynamodb_table_name):
    lambda_function_role = f'{agent_name}-lambda-role'
    dynamodb_access_policy_name = f'{agent_name}-dynamodb-policy'
    # Create IAM Role for the Lambda function
    try:
        assume_role_policy_document = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Principal": {
                        "Service": "lambda.amazonaws.com"
                    },
                    "Action": "sts:AssumeRole"
                }
            ]
        }

        assume_role_policy_document_json = json.dumps(assume_role_policy_document)

        lambda_iam_role = iam_client.create_role(
            RoleName=lambda_function_role,
            AssumeRolePolicyDocument=assume_role_policy_document_json
        )

        # Pause to make sure role is created
        time.sleep(10)
    except iam_client.exceptions.EntityAlreadyExistsException:
        lambda_iam_role = iam_client.get_role(RoleName=lambda_function_role)

    # Attach the AWSLambdaBasicExecutionRole policy
    iam_client.attach_role_policy(
        RoleName=lambda_function_role,
        PolicyArn='arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole'
    )

    # Create a policy to grant access to the DynamoDB table
    dynamodb_access_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": [
                    "dynamodb:GetItem",
                    "dynamodb:PutItem",
                    "dynamodb:DeleteItem"
                ],
                "Resource": "arn:aws:dynamodb:{}:{}:table/{}".format(
                    region, account_id, dynamodb_table_name
                )
            }
        ]
    }

    # Create the policy
    dynamodb_access_policy_json = json.dumps(dynamodb_access_policy)
    try:
        dynamodb_access_policy = iam_client.create_policy(
            PolicyName=dynamodb_access_policy_name,
            PolicyDocument=dynamodb_access_policy_json
        )
    except iam_client.exceptions.EntityAlreadyExistsException:
        dynamodb_access_policy = iam_client.get_policy(
            PolicyArn=f"arn:aws:iam::{account_id}:policy/{dynamodb_access_policy_name}"
        )

    # Attach the policy to the Lambda function's role
    iam_client.attach_role_policy(
        RoleName=lambda_function_role,
        PolicyArn=dynamodb_access_policy['Policy']['Arn']
    )
    return lambda_iam_role


def create_agent_role(agent_name, agent_foundation_model, kb_id=None):
    agent_bedrock_allow_policy_name = f"{agent_name}-ba"
    agent_role_name = f'AmazonBedrockExecutionRoleForAgents_{agent_name}'
    # Create IAM policies for agent
    statements = [
        {
            "Sid": "AmazonBedrockAgentBedrockFoundationModelPolicy",
            "Effect": "Allow",
            "Action": "bedrock:InvokeModel",
            "Resource": [
                f"arn:aws:bedrock:{region}::foundation-model/{agent_foundation_model}"
            ]
        }
    ]
    # add Knowledge Base retrieve and retrieve and generate permissions if agent has KB attached to it
    if kb_id:
        statements.append(
            {
                "Sid": "QueryKB",
                "Effect": "Allow",
                "Action": [
                    "bedrock:Retrieve",
                    "bedrock:RetrieveAndGenerate"
                ],
                "Resource": [
                    f"arn:aws:bedrock:{region}:{account_id}:knowledge-base/{kb_id}"
                ]
            }
        )

    bedrock_agent_bedrock_allow_policy_statement = {
        "Version": "2012-10-17",
        "Statement": statements
    }

    bedrock_policy_json = json.dumps(bedrock_agent_bedrock_allow_policy_statement)
    try:
        agent_bedrock_policy = iam_client.create_policy(
            PolicyName=agent_bedrock_allow_policy_name,
            PolicyDocument=bedrock_policy_json
        )
    except iam_client.exceptions.EntityAlreadyExistsException:
        agent_bedrock_policy = iam_client.get_policy(
            PolicyArn=f"arn:aws:iam::{account_id}:policy/{agent_bedrock_allow_policy_name}"
        )
                    
    # Create IAM Role for the agent and attach IAM policies
    assume_role_policy_document = {
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Principal": {
                "Service": "bedrock.amazonaws.com"
            },
            "Action": "sts:AssumeRole"
        }]
    }

    assume_role_policy_document_json = json.dumps(assume_role_policy_document)
    try:
        agent_role = iam_client.create_role(
            RoleName=agent_role_name,
            AssumeRolePolicyDocument=assume_role_policy_document_json
        )

        # Pause to make sure role is created
        time.sleep(10)
    except iam_client.exceptions.EntityAlreadyExistsException:
        agent_role = iam_client.get_role(
            RoleName=agent_role_name,
        )

    iam_client.attach_role_policy(
        RoleName=agent_role_name,
        PolicyArn=agent_bedrock_policy['Policy']['Arn']
    )
    return agent_role