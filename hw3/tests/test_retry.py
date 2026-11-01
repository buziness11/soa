import unittest
from unittest.mock import Mock, call, patch

import grpc

from grpc_client import call_flight


class RpcError(grpc.RpcError):
    def __init__(self, status):
        self.status = status

    def code(self):
        return self.status


class RetryTest(unittest.TestCase):
    def test_retry_then_success(self):
        request = object()
        response = object()
        metadata = (('x-api-key', 'test-key'),)
        for code in [grpc.StatusCode.UNAVAILABLE, grpc.StatusCode.DEADLINE_EXCEEDED]:
            method = Mock(side_effect=[RpcError(code), RpcError(code), response])
            with patch('grpc_client.time.sleep') as sleep:
                self.assertIs(call_flight(method, request, metadata), response)
            self.assertEqual(method.call_args_list, [call(request, metadata=metadata, timeout=2)] * 3)
            self.assertEqual(sleep.call_args_list, [call(0.1), call(0.2)])

    def test_stop_after_three_attempts(self):
        for code in [grpc.StatusCode.UNAVAILABLE, grpc.StatusCode.DEADLINE_EXCEEDED]:
            method = Mock(side_effect=RpcError(code))
            with patch('grpc_client.time.sleep') as sleep:
                with self.assertRaises(grpc.RpcError) as error:
                    call_flight(method, object(), ())
            self.assertEqual(error.exception.code(), code)
            self.assertEqual(method.call_count, 3)
            self.assertEqual(sleep.call_args_list, [call(0.1), call(0.2)])

    def test_other_errors_are_not_retried(self):
        for code in [grpc.StatusCode.INVALID_ARGUMENT, grpc.StatusCode.NOT_FOUND,
                     grpc.StatusCode.RESOURCE_EXHAUSTED, grpc.StatusCode.UNAUTHENTICATED,
                     grpc.StatusCode.UNKNOWN, grpc.StatusCode.CANCELLED]:
            method = Mock(side_effect=RpcError(code))
            with patch('grpc_client.time.sleep') as sleep:
                with self.assertRaises(grpc.RpcError) as error:
                    call_flight(method, object(), ())
            self.assertEqual(error.exception.code(), code)
            self.assertEqual(method.call_count, 1)
            sleep.assert_not_called()


if __name__ == '__main__':
    unittest.main()
