"""A stand-in for your app: three endpoints for the smoke checks to hit.

Replace it with your own; the template's tests use it to prove the smoke
script works end to end.
"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/healthz":
            self._send(200, json.dumps({"status": "ok"}).encode(), "application/json")
        elif self.path == "/":
            self._send(200, b"<!doctype html><title>App</title><p>Hello</p>", "text/html")
        elif self.path == "/api/me":
            self._send(401, json.dumps({"error": "sign in"}).encode(), "application/json")
        else:
            self._send(404, b"not found", "text/plain")

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: Any) -> None:
        pass


def serve(port: int = 8000) -> HTTPServer:
    return HTTPServer(("127.0.0.1", port), Handler)


if __name__ == "__main__":
    serve().serve_forever()
