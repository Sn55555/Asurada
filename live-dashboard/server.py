from __future__ import annotations

import argparse
import json
import mimetypes
import socket
import sys
from http import HTTPStatus
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CORE_ROOT = REPO_ROOT / "asurada-core"
SRC_ROOT = CORE_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from asurada.live_dashboard_payload import placeholder_dashboard_payload


STATIC_DIR = Path(__file__).resolve().parent / "static"
DEFAULT_FEED_PATH = CORE_ROOT / "runtime_logs" / "dashboard" / "live_payload.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the local live dashboard static server.")
    parser.add_argument("--http-port", type=int, default=8766, help="Static HTTP server port.")
    parser.add_argument("--feed-path", type=Path, default=DEFAULT_FEED_PATH, help="Path to the latest dashboard payload JSON.")
    parser.add_argument("--udp-host", default="0.0.0.0", help="Deprecated. Ignored; UDP is handled by asurada-core.")
    parser.add_argument("--udp-port", type=int, default=20778, help="Deprecated. Ignored; UDP is handled by asurada-core.")
    parser.add_argument("--ws-port", type=int, default=8765, help="Deprecated. Ignored; dashboard now polls the payload feed.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    print(f"[LIVE-DASHBOARD] HTTP http://127.0.0.1:{args.http_port}")
    print(f"[LIVE-DASHBOARD] FEED {args.feed_path}")
    print("[LIVE-DASHBOARD] Source runtime: asurada-core --live-udp")
    _serve_http(args.http_port, args.feed_path)
    return 0


def _serve_http(port: int, feed_path: Path) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(("127.0.0.1", port))
        server.listen(8)
        while True:
            conn, _addr = server.accept()
            with conn:
                request = conn.recv(4096)
                if not request:
                    continue
                first_line = request.splitlines()[0].decode("utf-8", errors="ignore")
                parts = first_line.split()
                path = "/" if len(parts) < 2 else parts[1].split("?", 1)[0]
                if path == "/api/latest":
                    body = _load_latest_payload(feed_path)
                    _send_response(conn, HTTPStatus.OK, body, "application/json; charset=utf-8")
                    continue
                relative = "index.html" if path in {"/", ""} else path.lstrip("/")
                file_path = (STATIC_DIR / relative).resolve()
                if not str(file_path).startswith(str(STATIC_DIR.resolve())) or not file_path.exists():
                    _send_response(conn, HTTPStatus.NOT_FOUND, b"Not found", "text/plain; charset=utf-8")
                    continue
                body = file_path.read_bytes()
                content_type = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"
                _send_response(conn, HTTPStatus.OK, body, content_type)


def _load_latest_payload(feed_path: Path) -> bytes:
    if feed_path.exists():
        try:
            return feed_path.read_bytes()
        except OSError:
            pass
    return json.dumps(placeholder_dashboard_payload(), ensure_ascii=False).encode("utf-8")


def _send_response(conn: socket.socket, status: HTTPStatus, body: bytes, content_type: str) -> None:
    headers = [
        f"HTTP/1.1 {status.value} {status.phrase}",
        f"Content-Length: {len(body)}",
        f"Content-Type: {content_type}",
        "Cache-Control: no-store",
        "Connection: close",
        "",
        "",
    ]
    conn.sendall("\r\n".join(headers).encode("utf-8") + body)


if __name__ == "__main__":
    raise SystemExit(main())
