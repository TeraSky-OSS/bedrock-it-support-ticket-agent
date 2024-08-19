import json
import uuid
import boto3
from decimal import Decimal


dynamodb = boto3.resource('dynamodb')
table = dynamodb.Table('it_support_tickets')


def decimal_default(obj):
    if isinstance(obj, Decimal):
        return float(obj)
    raise TypeError

def get_name_parameter(event, name):
    """
    Get a parameter from the lambda event
    """
    return next((item['value'] for item in event['parameters'] if item['name'] == name), None)


def get_support_ticket_details(ticket_id):
    """
    Retrieve details of a support system support ticket
    
    Args:
        ticket_id (string): The ID of the support ticket to retrieve
    """
    try:
        response = table.get_item(Key={'ticket_id': ticket_id})
        if 'Item' in response:
            return response['Item']
        else:
            return {'message': f'No support ticket found with ID {ticket_id}'}
    except Exception as e:
        return {'error': str(e)}


def create_support_ticket(date_and_time_of_occurrence, name, error_messages_or_logs, priority_level):
    """
    Create a new support system support ticket
    
    Args:
        date_and_time_of_occurrence (string): The date_and_time_of_occurrence of the support ticket
        name (string): Name to identify your issue
        error_messages_or_logs (string): The error_messages_or_logs of the support ticket
        priority_level (integer): The priority level for the support ticket
    """
    try:
        ticket_id = str(uuid.uuid4())[:8]
        table.put_item(
            Item={
                'ticket_id': ticket_id,
                'date_and_time_of_occurrence': date_and_time_of_occurrence,
                'name': name,
                'error_messages_or_logs': error_messages_or_logs,
                'priority_level': int(priority_level)
            }
        )
        return {'ticket_id': ticket_id}
    except Exception as e:
        return {'error': str(e)}


def delete_support_ticket(ticket_id):
    """
    Delete an existing support system support ticket
    
    Args:
        ticket_id (str): The ID of the support ticket to delete
    """
    try:
        response = table.delete_item(Key={'ticket_id': ticket_id})
        if response['ResponseMetadata']['HTTPStatusCode'] == 200:
            return {'message': f'Support Ticket with ID {ticket_id} deleted successfully'}
        else:
            return {'message': f'Failed to delete support ticket with ID {ticket_id}'}
    except Exception as e:
        return {'error': str(e)}
    

def lambda_handler(event, context):
    # get the action group used during the invocation of the lambda function
    actionGroup = event.get('actionGroup', '')
    
    # name of the function that should be invoked
    function = event.get('function', '')
    
    # parameters to invoke function with
    parameters = event.get('parameters', [])

    if function == 'get_support_ticket_details':
        ticket_id = get_name_parameter(event, "ticket_id")
        if ticket_id:
            response = get_support_ticket_details(ticket_id)
            responseBody = {'TEXT': {'body': json.dumps(response, default=decimal_default)}}
        else:
            responseBody = {'TEXT': {'body': 'Missing ticket_id parameter'}}

    elif function == 'create_support_ticket':
        date_and_time_of_occurrence = get_name_parameter(event, "date_and_time_of_occurrence")
        name = get_name_parameter(event, "name")
        error_messages_or_logs = get_name_parameter(event, "error_messages_or_logs")
        priority_level = get_name_parameter(event, "priority_level")

        if date_and_time_of_occurrence and name and error_messages_or_logs and priority_level:
            response = create_support_ticket(date_and_time_of_occurrence, name, error_messages_or_logs, priority_level)
            responseBody = {'TEXT': {'body': json.dumps(response)}}
        else:
            responseBody = {'TEXT': {'body': 'Missing required parameters'}}

    elif function == 'delete_support_ticket':
        ticket_id = get_name_parameter(event, "ticket_id")
        if ticket_id:
            response = delete_support_ticket(ticket_id)
            responseBody = {'TEXT': {'body': json.dumps(response)}}
        else:
            responseBody = {'TEXT': {'body': 'Missing ticket_id parameter'}}

    else:
        responseBody = {'TEXT': {'body': 'Invalid function'}}

    action_response = {
        'actionGroup': actionGroup,
        'function': function,
        'functionResponse': {
            'responseBody': responseBody
        }
    }

    function_response = {'response': action_response, 'messageVersion': event['messageVersion']}
    print("Response: {}".format(function_response))

    return function_response
