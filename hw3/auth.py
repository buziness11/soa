import os

import grpc


def check_api_key(context):
    received = dict(context.invocation_metadata()).get('x-api-key')
    expected = os.environ['FLIGHT_API_KEY']
    if not received or received != expected:
        context.abort(grpc.StatusCode.UNAUTHENTICATED, 'Invalid API key')
