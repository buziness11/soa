"""Проверки HTTP-контракта через настоящий локальный TCP-сервер."""

import json
import threading
import unittest
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer

from app import HealthHandler


class HealthEndpointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), HealthHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)

    def get(self, path):
        connection = HTTPConnection(*self.server.server_address, timeout=5)
        try:
            connection.request("GET", path)
            response = connection.getresponse()
            body = response.read()
            return response.status, dict(response.getheaders()), body
        finally:
            connection.close()

    def test_health_returns_200_and_service_identity(self):
        status, headers, body = self.get("/health")
        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Type"], "application/json; charset=utf-8")
        self.assertEqual(int(headers["Content-Length"]), len(body))
        self.assertEqual(json.loads(body), {"status": "ok", "service": "orders"})

    def test_unknown_and_business_routes_are_absent(self):
        for path in ("/missing", "/orders", "/payments"):
            with self.subTest(path=path):
                status, _, body = self.get(path)
                self.assertEqual(status, 404)
                self.assertEqual(json.loads(body), {"error": "not_found"})


if __name__ == "__main__":
    unittest.main()
