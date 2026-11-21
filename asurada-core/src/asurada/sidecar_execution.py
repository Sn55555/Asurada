"""Bound HTTP connections and ASR work independently, including abandoned calls."""
from concurrent.futures import TimeoutError as FutureTimeout
from http.server import ThreadingHTTPServer
import select
import socket
import socketserver
import threading
from .task_runtime import BoundedTaskExecutor, TaskCancelled

ASR_EXECUTOR = BoundedTaskExecutor(2)


class BoundedSidecarTCPServer(socketserver.ThreadingTCPServer):
    """A stuck provider retains its connection slot until its handler exits."""
    daemon_threads = True
    block_on_close = False
    allow_reuse_address = True
    request_queue_size = 8

    def __init__(self, *args, **kwargs):
        self.slots = threading.BoundedSemaphore(8)
        super().__init__(*args, **kwargs)

    def process_request(self, request, address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        request.settimeout(2.)
        try:
            super().process_request(request, address)
        except BaseException:
            self.slots.release()
            raise

    def process_request_thread(self, request, address):
        try:
            super().process_request_thread(request, address)
        finally:
            self.slots.release()


def watch_stream(context, connection, stopping, finished):
    """Cancel on peer EOF, service shutdown or total deadline, even in provider I/O."""
    while not finished.wait(.02):
        try:
            context.remaining()
            if stopping.is_set():
                raise TaskCancelled('sidecar_stopping')
            readable, _, _ = select.select([connection], [], [], 0)
            if readable:
                try:
                    data = connection.recv(1, socket.MSG_PEEK | socket.MSG_DONTWAIT)
                except (BlockingIOError, socket.timeout):
                    continue
                if data == b'':
                    raise TaskCancelled('asr_client_disconnected')
        except (TaskCancelled, TimeoutError, OSError):
            context.cancel()
            try:
                connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            return


class BoundedSidecarHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    block_on_close = False
    request_queue_size = 16

    def __init__(self, *args, **kwargs):
        self.slots = threading.BoundedSemaphore(16)
        super().__init__(*args, **kwargs)

    def process_request(self, request, address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        request.settimeout(2.)
        try:super().process_request(request,address)
        except BaseException:self.slots.release();raise

    def process_request_thread(self, request, address):
        try:super().process_request_thread(request,address)
        finally:self.slots.release()


def await_asr(context, future, connection, stopping):
    try:
        while True:
            context.remaining()
            if stopping.is_set():
                context.cancel()
                raise TaskCancelled('sidecar_stopping')
            readable,_,_=select.select([connection],[],[],0)
            if readable and connection.recv(1,socket.MSG_PEEK)==b'':
                context.cancel()
                raise TaskCancelled('asr_client_disconnected')
            try:
                result=future.result(timeout=min(.02,context.remaining()))
            except FutureTimeout:
                if future.done():raise
                continue
            context.remaining()
            return result
    except BaseException:
        context.cancel()
        raise
