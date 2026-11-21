"""One bounded latest-state sender per dashboard connection."""
from asurada.limits import DASHBOARD_PAYLOAD_MAX
import socket
import threading
import select
import time
import codecs
from websockets.protocol import OPEN, CLOSED
from websockets.frames import OP_TEXT, OP_BINARY, OP_CONT


class ProtocolStateClient:
    """Single-owner Sans-I/O protocol pump with one pending dashboard payload."""
    MAX_PAYLOAD = DASHBOARD_PAYLOAD_MAX

    def __init__(self, connection, protocol, *, on_close=lambda client: None, timeout_s=.5):
        self.connection, self.protocol = connection, protocol
        connection.setblocking(False)
        self.on_close, self.timeout_s = on_close, timeout_s
        self._condition = threading.Condition()
        self._pending = None
        self._closed = self._closing = False
        self.sent = self.coalesced = 0
        self.error = None
        self._thread = threading.Thread(target=self._run, name='dashboard-protocol', daemon=True)

    def start(self):
        self._thread.start()

    def offer(self, payload):
        if not isinstance(payload, bytes) or len(payload) > self.MAX_PAYLOAD:
            raise ValueError('dashboard_payload_exceeds_limit')
        with self._condition:
            if self._closed or self._closing:
                return False
            self.coalesced += int(self._pending is not None)
            self._pending = payload
            return True

    def _run(self):
        pending_wire = bytearray()
        write_deadline = close_deadline = None
        eof_after_write = False
        data_in_flight = False
        text_decoder = None
        try:
            while self.protocol.state is not CLOSED:
                now = time.monotonic()
                with self._condition:
                    if self._closing and close_deadline is None:
                        if self.protocol.state is OPEN:
                            self.protocol.send_close(1001, 'dashboard shutdown')
                        close_deadline = now + self.timeout_s
                    if not pending_wire and not self._closing and self.protocol.state is OPEN and self._pending is not None:
                        payload, self._pending = self._pending, None
                        self.protocol.send_text(payload)
                        data_in_flight = True
                for data in self.protocol.data_to_send():
                    if data:
                        pending_wire.extend(data)
                    else:
                        eof_after_write = True
                if len(pending_wire) > self.MAX_PAYLOAD + 65536:
                    raise OSError('dashboard_wire_buffer_limit')
                if pending_wire and write_deadline is None:
                    write_deadline = now + self.timeout_s
                if (write_deadline is not None and now >= write_deadline) or (close_deadline is not None and now >= close_deadline):
                    raise TimeoutError('dashboard_connection_deadline')
                if eof_after_write and not pending_wire:
                    break
                readable, writable, _ = select.select([self.connection], [self.connection] if pending_wire else [], [], .02)
                if writable:
                    try:
                        count = self.connection.send(pending_wire)
                    except BlockingIOError:
                        count = 0
                    del pending_wire[:count]
                    if not pending_wire:
                        write_deadline = None
                        if data_in_flight:
                            self.sent += 1
                            data_in_flight = False
                if readable:
                    try:
                        data = self.connection.recv(8192)
                    except BlockingIOError:
                        continue
                    if not data:
                        self.protocol.receive_eof()
                        break
                    self.protocol.receive_data(data)
                    # This is a state subscription, not a client command channel.
                    # Consume library events; the protocol handles control responses.
                    for event in self.protocol.events_received():
                        if event.opcode is OP_TEXT:
                            text_decoder = codecs.getincrementaldecoder('utf-8')()
                        elif event.opcode is OP_BINARY:
                            text_decoder = None
                        if event.opcode in (OP_TEXT, OP_CONT) and text_decoder is not None:
                            try:
                                text_decoder.decode(event.data, final=event.fin)
                            except UnicodeDecodeError:
                                self.protocol.fail(1007, 'invalid UTF-8')
                                self.error = 'invalid_text_utf8'
                                break
                            if event.fin:
                                text_decoder = None
        except (OSError, ValueError) as error:
            self.error = f'{type(error).__name__}: {error}'
        finally:
            with self._condition:
                self._closed = True
                self._pending = None
            try:
                self.connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            self.connection.close()
            self.on_close(self)

    def close(self):
        with self._condition:
            self._closing = True
            self._pending = None
        if self._thread.ident is None:
            self.connection.close()
            self._closed = True
        elif threading.current_thread() is not self._thread:
            self._thread.join(timeout=self.timeout_s + .2)
        return not self._thread.is_alive()

    def snapshot(self):
        with self._condition:
            return dict(sent=self.sent, coalesced=self.coalesced, queued=int(self._pending is not None),
                        closed=self._closed, worker_alive=self._thread.is_alive(), error=self.error)


class LatestStateClient:
    def __init__(self, connection, *, on_close=lambda client: None, timeout_s=.5):
        self.connection = connection
        self.connection.settimeout(timeout_s)
        self.on_close = on_close
        self._condition = threading.Condition()
        self._pending = None
        self._closed = False
        self.sent = self.coalesced = 0
        self.error = None
        self._thread = threading.Thread(target=self._run, name='dashboard-client-send', daemon=True)

    def start(self):
        self._thread.start()

    def offer(self, frame):
        with self._condition:
            if self._closed:
                return False
            if self._pending is not None:
                self.coalesced += 1
            self._pending = frame  # immutable bytes, shared without a copy
            self._condition.notify()
            return True

    def _run(self):
        try:
            while True:
                with self._condition:
                    while self._pending is None and not self._closed:
                        self._condition.wait()
                    if self._closed:
                        return
                    frame, self._pending = self._pending, None
                self.connection.sendall(frame)
                self.sent += 1
        except OSError as exc:
            self.error = f'{type(exc).__name__}: {exc}'
        finally:
            self._disconnect()
            self.on_close(self)

    def _disconnect(self):
        with self._condition:
            self._closed = True
            self._pending = None
            self._condition.notify_all()
        try:
            self.connection.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.connection.close()

    def close(self):
        self._disconnect()
        if self._thread.ident is not None and threading.current_thread() is not self._thread:
            self._thread.join(timeout=1)
        return not self._thread.is_alive()

    def snapshot(self):
        with self._condition:
            return dict(sent=self.sent, coalesced=self.coalesced, queued=int(self._pending is not None),
                        closed=self._closed, worker_alive=self._thread.is_alive(), error=self.error)
