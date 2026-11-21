from __future__ import annotations

import argparse
import base64
import hashlib
import json
import mimetypes
import socket
import sys
import threading
import time
from urllib.parse import parse_qs, urlsplit
from http import HTTPStatus
from websockets.server import ServerProtocol
from websockets.http11 import Request
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
CORE_ROOT = REPO_ROOT / "asurada-core"
SRC_ROOT = CORE_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from ws_client import LatestStateClient, ProtocolStateClient
from asurada.limits import DASHBOARD_HANDSHAKE_MAX
from asurada.live_dashboard_payload import placeholder_dashboard_payload, dashboard_source_status
from asurada.speech_client import SharedSpeechClient
from asurada.voice_meter import (
    DEFAULT_VOICE_METER_SOCKET_HOST,
    DEFAULT_VOICE_METER_SOCKET_PORT,
    VOICE_METER_STALE_MS,
    load_voice_meter_snapshot,
)


STATIC_DIR = Path(__file__).resolve().parent / "static"
DEFAULT_FEED_PATH = CORE_ROOT / "runtime_logs" / "dashboard" / "live_payload.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the local live dashboard static server.")
    parser.add_argument("--http-port", type=int, default=8766, help="Static HTTP server port.")
    parser.add_argument("--feed-path", type=Path, default=DEFAULT_FEED_PATH, help="Path to the latest dashboard payload JSON.")
    parser.add_argument("--speech-socket", type=Path, help="Local shared speech socket for personality controls.")
    parser.add_argument("--udp-host", default="0.0.0.0", help="Deprecated. Ignored; UDP is handled by asurada-core.")
    parser.add_argument("--udp-port", type=int, default=20778, help="Deprecated. Ignored; UDP is handled by asurada-core.")
    parser.add_argument("--ws-port", type=int, default=8765, help="Deprecated. Ignored; dashboard now polls the payload feed.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    meter_cache = VoiceMeterSocketCache()
    state_source = DashboardStateSource(args.feed_path, meter_cache, speech_socket=getattr(args, "speech_socket", None))
    ws_server = DashboardWebSocketServer("127.0.0.1", args.ws_port, state_source)
    try:
        meter_cache.start()
        ws_server.start()
        print(f"[LIVE-DASHBOARD] HTTP http://127.0.0.1:{args.http_port}")
        print(f"[LIVE-DASHBOARD] FEED {args.feed_path}")
        print(f"[LIVE-DASHBOARD] WS ws://127.0.0.1:{args.ws_port}")
        print(f"[LIVE-DASHBOARD] VOICE_METER udp://{meter_cache.host}:{meter_cache.port}")
        print("[LIVE-DASHBOARD] Source runtime: asurada-core --live-udp")
        _serve_http(args.http_port, state_source)
    finally:
        try:
            ws_server.close()
        finally:
            meter_cache.close()
    return 0


class VoiceMeterSocketCache:
    def __init__(self, host: str = DEFAULT_VOICE_METER_SOCKET_HOST, port: int = DEFAULT_VOICE_METER_SOCKET_PORT) -> None:
        self.host = host
        self.port = int(port)
        self._socket: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._snapshot: dict | None = None
        self._stop = threading.Event()

    def start(self) -> None:
        sock = None
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind((self.host, self.port))
            sock.settimeout(.2)
        except OSError as exc:
            if sock is not None:
                sock.close()
            print(f"[LIVE-DASHBOARD] voice meter socket disabled: {exc}")
            return
        self._socket = sock
        self._thread = threading.Thread(target=self._run, name="voice-meter-udp-listener", daemon=True)
        self._thread.start()

    def close(self):
        self._stop.set()
        if self._socket is not None:
            try:
                self._socket.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            self._socket.close()
        if self._thread is not None:
            self._thread.join(timeout=1)
        return self._thread is None or not self._thread.is_alive()

    def latest_snapshot(self) -> dict | None:
        with self._lock:
            if self._snapshot is None:
                return None
            snapshot = dict(self._snapshot)
        updated_at_ms = int(snapshot.get("updated_at_ms") or 0)
        now_ms = int(time.time() * 1000)
        if updated_at_ms <= 0 or now_ms - updated_at_ms > VOICE_METER_STALE_MS:
            return None
        return snapshot

    def _run(self) -> None:
        assert self._socket is not None
        while not self._stop.is_set():
            try:
                data, _addr = self._socket.recvfrom(65535)
            except socket.timeout:
                continue
            except OSError:
                return
            try:
                payload = json.loads(data.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
            if not isinstance(payload, dict):
                continue
            with self._lock:
                self._snapshot = payload


class DashboardStateSource:
    def __init__(self, feed_path: Path, meter_cache: VoiceMeterSocketCache, *, speech_socket=None) -> None:
        self.feed_path = feed_path
        self.meter_cache = meter_cache
        self.speech = SharedSpeechClient(speech_socket, timeout_s=.25) if speech_socket else None

    def personality_control(self, changes=None):
        if self.speech is None:
            raise ConnectionError("speech_socket_not_configured")
        if changes is not None:
            self.speech.personality_preferences(**changes)
        return self.speech.call("personality_control_status")

    def latest_payload_dict(self) -> dict[str, Any]:
        payload = placeholder_dashboard_payload()
        if self.feed_path.exists():
            try:
                payload = json.loads(self.feed_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                payload = placeholder_dashboard_payload()
        if not isinstance(payload, dict) or payload.get('payload_version') != 'v1':
            payload = placeholder_dashboard_payload()
        payload['source_status'] = dashboard_source_status(payload)
        meter = self.meter_cache.latest_snapshot() or load_voice_meter_snapshot()
        return _merge_voice_meter(payload, meter)

    def latest_payload_bytes(self) -> bytes:
        return json.dumps(self.latest_payload_dict(), ensure_ascii=False).encode("utf-8")


class DashboardWebSocketServer:
    def __init__(self, host: str, port: int, state_source: DashboardStateSource) -> None:
        self.host = host
        self.port = int(port)
        self.state_source = state_source
        self._clients: set[LatestStateClient] = set()
        self.max_clients = 16
        self._stop = threading.Event()
        self._server = None
        self._threads = []
        self._disconnected = 0
        self._send_errors = 0
        self._oversized_payloads = 0
        self._lock = threading.Lock()

    def start(self) -> None:
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server.bind((self.host, self.port))
            server.listen(8)
            server.settimeout(.2)
        except Exception:
            server.close()
            raise
        self._server = server
        self.port = server.getsockname()[1]
        self._threads = [threading.Thread(target=target, name=name, daemon=True)
                         for target, name in ((self._accept_loop, 'dashboard-ws-accept'),
                                              (self._broadcast_loop, 'dashboard-ws-broadcast'))]
        for thread in self._threads:
            thread.start()

    def _remove_client(self, client):
        with self._lock:
            self._clients.discard(client)
            self._disconnected += 1
            self._send_errors += int(client.error is not None)

    def _accept_loop(self) -> None:
        while not self._stop.is_set():
            try:
                conn, _addr = self._server.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            conn.settimeout(.5)
            with self._lock:
                full = len(self._clients) >= self.max_clients
            try:
                protocol = None if full else self._handshake(conn)
                if protocol is None or self._stop.is_set():
                    conn.close()
                    continue
                client = ProtocolStateClient(conn, protocol, on_close=self._remove_client)
                with self._lock:
                    self._clients.add(client)
                client.start()
                initial = self.state_source.latest_payload_bytes()
                if len(initial) <= ProtocolStateClient.MAX_PAYLOAD:
                    client.offer(initial)
                else:
                    self._oversized_payloads += 1
            except OSError:
                conn.close()

    def _broadcast_loop(self) -> None:
        last_payload = b""
        while not self._stop.is_set():
            payload = self.state_source.latest_payload_bytes()
            if payload != last_payload:
                self._broadcast_text(payload)
                last_payload = payload
            self._stop.wait(.016)

    def _broadcast_text(self, payload: bytes) -> None:
        if len(payload) > ProtocolStateClient.MAX_PAYLOAD:
            self._oversized_payloads += 1
            return
        with self._lock:
            clients = list(self._clients)
        for client in clients:
            client.offer(payload)

    def snapshot(self):
        with self._lock:
            return dict(clients=[client.snapshot() for client in self._clients],
                        disconnected=self._disconnected, send_errors=self._send_errors,
                        max_clients=self.max_clients, oversized_payloads=self._oversized_payloads)

    def close(self):
        self._stop.set()
        if self._server is not None:
            self._server.close()
        for thread in self._threads:
            thread.join(timeout=1)
        with self._lock:
            clients = list(self._clients)
        closed = [client.close() for client in clients]
        return all(closed) and all(not thread.is_alive() for thread in self._threads)

    def _handshake(self, conn):
        protocol = ServerProtocol(max_size=4096)
        deadline = time.monotonic() + .5
        received = 0
        while time.monotonic() < deadline:
            conn.settimeout(max(.001, deadline - time.monotonic()))
            data = conn.recv(4096)
            if not data:
                return None
            received += len(data)
            if received > DASHBOARD_HANDSHAKE_MAX:
                return None
            protocol.receive_data(data)
            for event in protocol.events_received():
                if isinstance(event, Request):
                    response = protocol.accept(event)
                    protocol.send_response(response)
                    for wire in protocol.data_to_send():
                        if wire:
                            conn.sendall(wire)
                    return protocol if response.status_code == 101 else None
            if protocol.handshake_exc is not None:
                return None
        return None


class DashboardHttpServer:
    """Bounded HTTP workers whose sockets are owned by the service lifecycle."""
    def __init__(self, port, state_source, *, max_clients=16):
        self.port, self.state_source = port, state_source
        self.max_clients = max_clients
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._workers, self._connections = set(), set()
        self._server = None

    def start(self):
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind(('127.0.0.1', self.port))
            listener.listen(8)
            listener.settimeout(.2)
        except Exception:
            listener.close()
            raise
        self._server = listener
        self.port = listener.getsockname()[1]

    def _dispatch(self, conn):
        def serve():
            try:
                _handle_http_connection(conn, self.state_source)
            finally:
                with self._lock:
                    self._connections.discard(conn)
                    self._workers.discard(threading.current_thread())
        with self._lock:
            if self._stop.is_set() or len(self._connections) >= self.max_clients:
                conn.close()
                return False
            worker = threading.Thread(target=serve, name='dashboard-http', daemon=True)
            self._connections.add(conn)
            self._workers.add(worker)
            try:
                worker.start()
            except Exception:
                self._connections.discard(conn)
                self._workers.discard(worker)
                conn.close()
                raise
        return True

    def serve_forever(self):
        while not self._stop.is_set():
            try:
                conn, _addr = self._server.accept()
            except socket.timeout:
                continue
            except OSError:
                if self._stop.is_set():
                    return
                raise
            self._dispatch(conn)

    def close(self):
        with self._lock:
            self._stop.set()
            connections, workers = list(self._connections), list(self._workers)
        if self._server is not None:
            self._server.close()
        for conn in connections:
            try:
                conn.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        deadline = time.monotonic() + 1
        for worker in workers:
            worker.join(timeout=max(0, deadline-time.monotonic()))
        return all(not worker.is_alive() for worker in workers)

    def snapshot(self):
        with self._lock:
            return dict(active_connections=len(self._connections), workers=len(self._workers),
                        stopped=self._stop.is_set(), max_clients=self.max_clients)


def _serve_http(port: int, state_source: DashboardStateSource) -> None:
    service = DashboardHttpServer(port, state_source)
    try:
        service.start()
        service.serve_forever()
    finally:
        service.close()


def _handle_http_connection(conn, state_source):
    with conn:
        conn.settimeout(.5)
        try:
            request = conn.recv(4096)
            if not request:
                return
            first_line = request.splitlines()[0].decode("utf-8", errors="ignore")
            parts = first_line.split()
            url = urlsplit(parts[1] if len(parts) >= 2 else "/")
            path = url.path
            if path == "/api/personality":
                _handle_personality_request(conn, state_source, parts[0], url.query, request)
                return
            if path == "/api/latest":
                _send_response(conn, HTTPStatus.OK, state_source.latest_payload_bytes(), "application/json; charset=utf-8")
                return
            relative = "index.html" if path in {"/", ""} else path.lstrip("/")
            file_path = (STATIC_DIR / relative).resolve()
            if STATIC_DIR.resolve() not in file_path.parents or not file_path.is_file():
                _send_response(conn, HTTPStatus.NOT_FOUND, b"Not found", "text/plain; charset=utf-8")
                return
            body = file_path.read_bytes()
            content_type = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"
            _send_response(conn, HTTPStatus.OK, body, content_type)
        except OSError:
            return


def _handle_personality_request(conn, source, method, query, request):
    headers = {}
    for line in request.split(b"\r\n")[1:]:
        name, separator, value = line.partition(b":")
        if separator:
            headers[name.lower()] = value.strip()
    changes = None
    status = HTTPStatus.OK
    try:
        if method == "POST":
            host = headers.get(b"host", b"")
            if (host.split(b":")[0] not in {b"127.0.0.1", b"localhost"}
                    or headers.get(b"origin") != b"http://" + host):
                status = HTTPStatus.FORBIDDEN
                raise ValueError("local_same_origin_required")
            fields = parse_qs(query, strict_parsing=True, max_num_fields=2)
            if not fields or set(fields) - {"quiet", "humor"} or any(len(values) != 1 for values in fields.values()):
                raise ValueError("invalid_personality_controls")
            changes = {}
            if "quiet" in fields:
                if fields["quiet"][0] not in {"true", "false"}:
                    raise ValueError("invalid_quiet_preference")
                changes["quiet"] = fields["quiet"][0] == "true"
            if "humor" in fields:
                if fields["humor"][0] not in {"off", "low", "normal"}:
                    raise ValueError("invalid_humor_preference")
                changes["humor"] = fields["humor"][0]
        elif method != "GET":
            status = HTTPStatus.METHOD_NOT_ALLOWED
            raise ValueError("unsupported_personality_method")
        result = source.personality_control(changes)
    except ValueError as error:
        if status == HTTPStatus.OK:
            status = HTTPStatus.BAD_REQUEST
        result = {"error": str(error)}
    except (OSError, RuntimeError, TimeoutError):
        status = HTTPStatus.SERVICE_UNAVAILABLE
        result = {"error": "speech_service_unavailable"}
    _send_response(conn, status, json.dumps(result).encode(), "application/json; charset=utf-8")


def _merge_voice_meter(payload: dict, meter: dict) -> dict:
    merged = dict(payload or {})
    voice = dict(merged.get("voice") or {})
    level = max(0.0, min(float(meter.get("amplitude_level") or 0.0), 1.0))
    peak = max(0.0, min(float(meter.get("amplitude_peak") or 0.0), 1.0))
    playback_active = bool(meter.get("playback_active", False))
    voice["amplitude_level"] = round(level, 4)
    voice["amplitude_peak"] = round(peak, 4)
    voice["amplitude_rms"] = meter.get("amplitude_rms")
    voice["amplitude_updated_at_ms"] = int(meter.get("updated_at_ms") or 0)
    voice["amplitude_source"] = "output_audio"
    voice["amplitude_playback_active"] = playback_active
    voice["beat_pulse"] = round(max(0.0, min(float(meter.get("beat_pulse") or 0.0), 1.0)), 4)
    voice["beat_updated_at_ms"] = int(meter.get("beat_updated_at_ms") or 0)
    if playback_active:
        voice["state"] = "active"
        voice["active"] = True
        voice["source_kind"] = str(voice.get("source_kind") or "audio_playback")
        voice["action_code"] = str(voice.get("action_code") or "VOICE_OUTPUT")
    else:
        voice["active"] = False
        if not bool(voice.get("pending", False)):
            voice["state"] = "idle"
    merged["voice"] = voice
    return merged


def _build_ws_text_frame(payload: bytes) -> bytes:
    header = bytearray()
    header.append(0x81)
    length = len(payload)
    if length < 126:
        header.append(length)
    elif length < 65536:
        header.append(126)
        header.extend(length.to_bytes(2, "big"))
    else:
        header.append(127)
        header.extend(length.to_bytes(8, "big"))
    return bytes(header) + payload


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
