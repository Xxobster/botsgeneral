"""Local HTTP agent: keys stay on this VPS; hub pulls JSON over SSH to localhost."""

from __future__ import annotations

import json
import os
import threading
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from botsgeneral.hmi.jsonutil import dumps
from botsgeneral.hmi.snapshot import build_host_only, build_snapshot

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8788


def load_token() -> str:
    env = os.environ.get("BOTSGENERAL_HMI_TOKEN")
    if env:
        return env.strip()
    for p in (Path("/etc/botsgeneral/hmi_token"), Path.home() / ".botsgeneral" / "hmi_token"):
        if p.exists():
            return p.read_text(encoding="utf-8", errors="ignore").strip()
    return ""


class AgentState:
    def __init__(self) -> None:
        self.token = load_token()
        self.lock = threading.Lock()
        self.latest: dict[str, Any] | None = None
        self.latest_error: str | None = None


STATE = AgentState()


def _authorized(handler: BaseHTTPRequestHandler) -> bool:
    token = STATE.token
    if not token:
        return True
    got = handler.headers.get("Authorization") or handler.headers.get("X-HMI-Token") or ""
    if got.lower().startswith("bearer "):
        got = got[7:].strip()
    return got == token


def _send(handler: BaseHTTPRequestHandler, code: int, payload: dict[str, Any], *, raw: str | None = None) -> None:
    body = (raw if raw is not None else dumps(payload)).encode("utf-8")
    handler.send_response(code)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(body)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args: Any) -> None:
        return

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path.rstrip("/") or "/"
        if path in ("/v1/health", "/health"):
            _send(self, 200, {"ok": True, "role": "agent"})
            return
        if not _authorized(self):
            _send(self, 401, {"ok": False, "error": "unauthorized"})
            return
        if path in ("/v1/host", "/host"):
            try:
                _send(self, 200, build_host_only())
            except Exception as e:
                _send(self, 500, {"ok": False, "error": str(e)})
            return
        if path in ("/v1/snapshot", "/snapshot", "/"):
            try:
                snap = build_snapshot()
                with STATE.lock:
                    STATE.latest = snap
                    STATE.latest_error = None
                _send(self, 200, snap)
            except Exception as e:
                err = f"{e}\n{traceback.format_exc()}"
                with STATE.lock:
                    STATE.latest_error = str(e)
                _send(self, 500, {"ok": False, "error": str(e), "detail": err[-2000:]})
            return
        _send(self, 404, {"ok": False, "error": "not found"})


def warmup() -> None:
    try:
        snap = build_snapshot()
        with STATE.lock:
            STATE.latest = snap
            STATE.latest_error = None
    except Exception as e:
        with STATE.lock:
            STATE.latest_error = str(e)


def serve(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> None:
    threading.Thread(target=warmup, name="hmi-warmup", daemon=True).start()
    httpd = ThreadingHTTPServer((host, int(port)), Handler)
    print(json.dumps({"ok": True, "role": "agent", "listen": f"{host}:{port}"}), flush=True)
    httpd.serve_forever()


def main(argv: list[str] | None = None) -> int:
    import argparse

    p = argparse.ArgumentParser(prog="botsgeneral hmi-agent")
    p.add_argument("--host", default=os.environ.get("BOTSGENERAL_HMI_AGENT_HOST", DEFAULT_HOST))
    p.add_argument("--port", type=int, default=int(os.environ.get("BOTSGENERAL_HMI_AGENT_PORT", DEFAULT_PORT)))
    args = p.parse_args(argv)
    serve(args.host, args.port)
    return 0
