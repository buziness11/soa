from http.server import BaseHTTPRequestHandler, HTTPServer


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        # Для всех адресов, кроме /health, возвращаем 404.
        if self.path != "/health":
            self.send_error(404)
            return

        # Отвечаем на /health: сервис работает.
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"OK\n")


# Запускаем сервер на порту 8080. Ctrl+C останавливает программу.
server = HTTPServer(("0.0.0.0", 8080), Handler)
print("Сервис запущен. Для остановки нажмите Ctrl+C.", flush=True)
try:
    server.serve_forever()
except KeyboardInterrupt:
    server.server_close()
