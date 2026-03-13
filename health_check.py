import os
from http.server import BaseHTTPRequestHandler, HTTPServer
import threading

PORT = int(os.getenv("PORT", 8000))


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status":"ok"}')
        else:
            self.send_response(404)
            self.end_headers()

    # Suppress default request logs
    def log_message(self, format, *args):
        pass


def run_health_server():
    server = HTTPServer(("0.0.0.0", PORT), HealthHandler)
    print(f"✅ Health check server running on port {PORT}")
    server.serve_forever()


def start_health_server():
    """Start health server in a background daemon thread."""
    t = threading.Thread(target=run_health_server, daemon=True)
    t.start()
