"""Local web server: serves the dashboard and the chat endpoint. Standard library only.

Run:
    python -m api.server                # http://127.0.0.1:8000
    python -m api.server --port 8080

Settings are read from the environment, or from a .env file in the project root (never committed):
    LLM_API_KEY=...            your provider key (required for free-text questions)
    LLM_MODEL=...              the model name your provider expects (required with the key)
    LLM_BASE_URL=...           optional; defaults to the Anthropic messages endpoint

The server binds to 127.0.0.1 unless --host is given. The key is only read here and is never sent to
the browser.
"""

from __future__ import annotations

import argparse
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from api import chat as chat_service

ROOT = Path(__file__).resolve().parents[1]
MAX_BODY_BYTES = 65536   # room for a conversation history of up to 12 messages


def load_dotenv(path: Path, env: dict) -> None:
    """Read KEY=VALUE lines into env without overriding variables that are already set."""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in env:
            env[key] = value


def make_handler(dashboard_path: Path, payload: dict, env: dict, llm_call=None, llm_stream=None):
    class Handler(BaseHTTPRequestHandler):
        server_version = "AxiomDashboard/1.0"

        def _send(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status: int, obj: dict) -> None:
            self._send(status, json.dumps(obj).encode("utf-8"), "application/json; charset=utf-8")

        def _read_body(self):
            """Return the parsed JSON object, or None after sending an error response."""
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                length = 0
            if length <= 0 or length > MAX_BODY_BYTES:
                self._json(400, {"mode": "error", "answer": "Request body missing or too large."})
                return None
            try:
                body = json.loads(self.rfile.read(length).decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                self._json(400, {"mode": "error", "answer": "Send a JSON object."})
                return None
            if not isinstance(body, dict):
                self._json(400, {"mode": "error", "answer": "Send a JSON object."})
                return None
            return body

        def _stream(self, body: dict) -> None:
            """Server-sent events: one {"delta": ...} per piece of text, then a final done or error event."""
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Accel-Buffering", "no")
            self.send_header("Connection", "close")
            self.end_headers()
            self.close_connection = True
            try:
                for event in chat_service.stream(body, payload, env, llm_stream):
                    self.wfile.write(f"data: {json.dumps(event)}\n\n".encode("utf-8"))
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                return  # the browser closed the stream; nothing else to send

        def do_GET(self):  # noqa: N802
            if self.path in ("/", "/index.html"):
                if not dashboard_path.exists():
                    self._send(404, b"Dashboard not built. Run: python -m pipeline.run --input <data>", "text/plain")
                    return
                self._send(200, dashboard_path.read_bytes(), "text/html; charset=utf-8")
            elif self.path == "/api/health":
                configured = bool(env.get("LLM_API_KEY") and env.get("LLM_MODEL"))
                self._json(200, {"status": "ok", "llm_configured": configured})
            else:
                self._send(404, b"Not found", "text/plain")

        def do_POST(self):  # noqa: N802
            if self.path not in ("/api/chat", "/api/chat/stream"):
                self._send(404, b"Not found", "text/plain")
                return
            body = self._read_body()
            if body is None:
                return
            if self.path == "/api/chat/stream":
                self._stream(body)
            else:
                self._json(200, chat_service.answer(body, payload, env, llm_call))

        def log_message(self, format, *args):  # keep the console quiet; the chat never logs questions or keys
            return

    return Handler


def build_server(host: str, port: int, dashboard_path: Path, payload: dict, env: dict, llm_call=None,
                 llm_stream=None):
    handler = make_handler(dashboard_path, payload, env, llm_call, llm_stream)
    return ThreadingHTTPServer((host, port), handler)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Axiom dashboard server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--kpis", default=str(ROOT / "data" / "processed" / "kpis.json"))
    parser.add_argument("--dashboard", default=str(ROOT / "dashboard" / "index.html"))
    args = parser.parse_args(argv)

    env = dict(os.environ)
    load_dotenv(ROOT / ".env", env)
    payload = json.loads(Path(args.kpis).read_text(encoding="utf-8"))
    server = build_server(args.host, args.port, Path(args.dashboard), payload, env)
    configured = bool(env.get("LLM_API_KEY") and env.get("LLM_MODEL"))
    print(f"Dashboard: http://{args.host}:{server.server_address[1]}")
    print("Chat: " + ("LLM configured" if configured else "LLM not configured; leadership questions use pipeline answers"))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
