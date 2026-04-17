#!/usr/bin/env python3
"""
Minimal localhost HTTP target for Tool 1 (Streamlit) manual verification.

Binds 127.0.0.1 only. Three POST paths return fixed JSON bodies that match
system_tests/suites/tool1_local_starter_suite.json.

Usage (separate terminal before Streamlit):
    python tools/tool1_verify_server.py

Default port: 37641 (override: TOOL1_VERIFY_PORT=37642 python tools/tool1_verify_server.py)
"""

from __future__ import annotations

import json
import os
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import ClassVar

DEFAULT_PORT = 37641


class Tool1VerifyHandler(BaseHTTPRequestHandler):
    """POST-only tiny responder; paths mirror starter suite URLs."""

    _routes: ClassVar[dict[str, bytes]] = {
        "/tool1/health": json.dumps(
            {"result": "TOOL1_HEALTH_OK", "detail": "success path"}
        ).encode("utf-8"),
        "/tool1/structured": json.dumps(
            {"status": "ok", "message": "good"}
        ).encode("utf-8"),
        "/tool1/consistent": json.dumps(
            {"text": "TOOL1_CONSISTENCY_OK", "run": "sample"}
        ).encode("utf-8"),
    }

    def log_message(self, fmt: str, *args) -> None:
        # Quiet default stderr noise for operator UX.
        return

    def do_POST(self) -> None:
        body = self._routes.get(self.path)
        if body is None:
            self.send_response(404)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"error":"not_found"}')
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        msg = b"Tool1 verify server: POST /tool1/health, /tool1/structured, /tool1/consistent\n"
        self.send_header("Content-Length", str(len(msg)))
        self.end_headers()
        self.wfile.write(msg)


def main() -> int:
    port = int(os.environ.get("TOOL1_VERIFY_PORT", str(DEFAULT_PORT)))
    server = HTTPServer(("127.0.0.1", port), Tool1VerifyHandler)
    print(f"Tool 1 verify server listening on http://127.0.0.1:{port}", flush=True)
    print("POST paths: /tool1/health, /tool1/structured, /tool1/consistent", flush=True)
    print("Ctrl+C to stop.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.", flush=True)
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
