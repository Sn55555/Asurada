"""Fault-injected DNS, TCP and TLS cancellation without external networking."""
import errno
import threading
import time
from unittest.mock import patch
from asurada.http_connection import connect_socket, CancellableHTTPSConnection
from asurada.cancellable_http import request_json
from asurada.task_runtime import TaskContext, TaskCancelled, BoundedTaskExecutor, TaskCapacityExceeded
from regression_support import emit_result


def run():
    checks={}
    release=threading.Event();entered=threading.Event();errors=[]
    context=TaskContext.start('dns',2000)
    executor=BoundedTaskExecutor(1)
    def resolver(*args):entered.set();release.wait(2);return []
    def call():
        try:connect_socket(('unused.invalid',80),2,None,context=context)
        except Exception as exc:errors.append(exc)
    with patch('asurada.http_connection.DNS_EXECUTOR',executor),patch('asurada.http_connection.socket.getaddrinfo',side_effect=resolver):
        worker=threading.Thread(target=call);worker.start()
        try:
            assert entered.wait(1);context.cancel();worker.join(.3)
            checks['dns_cancel_returns']=not worker.is_alive() and isinstance(errors[0],TaskCancelled)
            try:executor.submit(TaskContext.start('probe',1000),lambda:True);checks['stuck_dns_retains_slot']=False
            except TaskCapacityExceeded:checks['stuck_dns_retains_slot']=True
        finally:release.set();worker.join(1)
    deadline=time.monotonic()+1
    while True:
        try:
            task=TaskContext.start('recovery',1000)
            checks['dns_slot_recovers']=task.wait(executor.submit(task,lambda:True));break
        except TaskCapacityExceeded:
            if time.monotonic()>deadline:checks['dns_slot_recovers']=False;break
            time.sleep(.005)
    class Tcp:
        closed=False
        def setblocking(self,value):pass
        def connect_ex(self,value):return errno.EINPROGRESS
        def close(self):self.closed=True
    task=TaskContext.start('tcp',1000);tcp=Tcp()
    class Selector:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def register(self,*args):pass
        def select(self,*args):task.cancel();return []
    with patch('asurada.http_connection.socket.getaddrinfo',return_value=[(2,1,6,'',('127.0.0.1',80))]),patch('asurada.http_connection.socket.socket',return_value=tcp),patch('asurada.http_connection.selectors.DefaultSelector',Selector):
        try:connect_socket(('unused.invalid',80),1,None,context=task);checks['tcp_cancel_closes_socket']=False
        except TaskCancelled:checks['tcp_cancel_closes_socket']=tcp.closed
    entered=threading.Event();stopped=threading.Event();tls_task=TaskContext.start('tls',1000)
    class TLS:
        closed=False
        def do_handshake(self):entered.set();assert stopped.wait(1);raise OSError('handshake_interrupted')
        def shutdown(self,*args):stopped.set()
        def close(self):self.closed=True
    tls=TLS()
    class Context:
        def wrap_socket(self,sock,**kwargs):
            checks['tls_certificate_hostname_preserved']=kwargs=={'server_hostname':'origin.invalid','do_handshake_on_connect':False}
            return tls
    connection=CancellableHTTPSConnection('origin.invalid');connection._context=Context()
    def cancel():
        if entered.wait(1):tls_task.cancel()
    worker=threading.Thread(target=cancel);worker.start()
    with patch('asurada.cancellable_http.connection_route',return_value=(connection,'/',{})),patch('http.client.HTTPConnection.connect',lambda self:setattr(self,'sock',object())):
        try:request_json('https://origin.invalid',method='GET',body=None,context=tls_task,timeout_ms=1000);checks['tls_handshake_cancelled']=False
        except TaskCancelled:checks['tls_handshake_cancelled']=tls.closed and stopped.is_set()
    worker.join(1)
    return {'passed':all(checks.values()),'checks':checks,'scope':'fault-injected connection phases; not live DNS/TCP/TLS acceptance'}


if __name__=='__main__':emit_result(run())
