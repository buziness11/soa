"""Каркас сервиса заказов: только проверка доступности, без бизнес-логики."""

import json
import os
import signal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/health":
            status = 200
            payload = {"status": "ok", "service": "orders"}
        else:
            status = 404
            payload = {"error": "not_found"}

        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def stop_server(signum, frame):
    raise KeyboardInterrupt


def main():
    signal.signal(signal.SIGTERM, stop_server)
    port = int(os.environ.get("HTTP_PORT", "8080"))
    with ThreadingHTTPServer(("0.0.0.0", port), HealthHandler) as server:
        print(f"Orders service: http://0.0.0.0:{port}/health", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
