import time

import grpc


def call_flight(method, request, metadata):
    for attempt in range(3):
        try:
            return method(request, metadata=metadata, timeout=2)
        except grpc.RpcError as error:
            if error.code() not in (grpc.StatusCode.UNAVAILABLE, grpc.StatusCode.DEADLINE_EXCEEDED) or attempt == 2:
                raise
            delay = 0.1 * 2 ** attempt
            print(f'gRPC retry {attempt + 2}/3: {error.code().name}, wait {delay}s', flush=True)
            time.sleep(delay)
