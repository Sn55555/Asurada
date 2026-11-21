"""Bounded DNS work and cancellable TCP/TLS connection establishment."""
import errno
import http.client
import selectors
import socket
import time
from .task_runtime import BoundedTaskExecutor, TaskContext


DNS_EXECUTOR = BoundedTaskExecutor(2)


def connect_socket(address, timeout, source_address, *, context):
    task=TaskContext(context.task_id,min(context.deadline,time.monotonic()+timeout),context.cancellation)
    host,port=address
    addresses=task.wait(DNS_EXECUTOR.submit(task,lambda:socket.getaddrinfo(host,port,0,socket.SOCK_STREAM)))
    error=None
    for family,kind,protocol,_,destination in addresses:
        task.remaining()
        connection=socket.socket(family,kind,protocol)
        try:
            connection.setblocking(False)
            if source_address is not None:connection.bind(source_address)
            status=connection.connect_ex(destination)
            if status not in (0,errno.EISCONN):
                if status not in (errno.EINPROGRESS,errno.EWOULDBLOCK,errno.EALREADY,errno.EINTR):
                    raise OSError(status,'tcp_connect_failed')
                with selectors.DefaultSelector() as selector:
                    selector.register(connection,selectors.EVENT_WRITE)
                    while not selector.select(min(.02,task.remaining())):
                        pass
                task.remaining()
                status=connection.getsockopt(socket.SOL_SOCKET,socket.SO_ERROR)
                if status:raise OSError(status,'tcp_connect_failed')
            connection.settimeout(task.remaining())
            return connection
        except OSError as exc:
            error=exc
            connection.close()
        except BaseException:
            connection.close()
            raise
    task.remaining()
    raise error or OSError('dns_returned_no_addresses')


class CancellableHTTPSConnection(http.client.HTTPSConnection):
    def connect(self):
        http.client.HTTPConnection.connect(self)
        hostname=self._tunnel_host or self.host
        # Publish the TLS socket before the blocking handshake so the owner's
        # cancellation watcher can shutdown it while certificate checks run.
        self.sock=self._context.wrap_socket(self.sock,server_hostname=hostname,do_handshake_on_connect=False)
        self.sock.do_handshake()
