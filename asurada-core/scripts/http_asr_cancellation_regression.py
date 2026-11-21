import http.client
import json
import socket
import threading
import time
from unittest.mock import patch
from regression_support import emit_result
from asurada.cancellable_http import request_json
from asurada.task_runtime import TaskContext, TaskCancelled


def scenario(phase):
    client,server=socket.socketpair();entered=threading.Event();finish=threading.Event();errors=[];results=[];peer_eof=[]
    context=TaskContext.start('http-asr',100 if phase=='deadline_body' else 2000)
    def connect(connection):connection.sock=client
    def peer():
        try:
            # Read complete headers; GET deliberately has no body.
            data=b''
            while b'\r\n\r\n' not in data:data+=server.recv(4096)
            if phase in {'cancel_body','deadline_body'}:
                server.sendall(b'HTTP/1.1 200 OK\r\nContent-Length: 20\r\nConnection: close\r\n\r\n{')
            elif phase=='positive':
                server.sendall(b'HTTP/1.1 200 OK\r\nContent-Length: 11\r\nConnection: close\r\n\r\n{"ok":true}')
            elif phase=='oversized':
                server.sendall(b'HTTP/1.1 200 OK\r\nContent-Length: 100\r\n\r\n'+b'x'*100)
            entered.set()
            server.settimeout(1)
            while server.recv(4096):pass
            peer_eof.append(True)
        finally:server.close();finish.set()
    def caller():
        try:results.append(request_json('http://unused.invalid/asr',method='GET',body=None,context=context,
                                       timeout_ms=1000,max_response_bytes=20 if phase=='oversized' else 1024))
        except Exception as exc:errors.append(exc)
    with patch.object(http.client.HTTPConnection,'connect',connect):
        peer_thread=threading.Thread(target=peer);worker=threading.Thread(target=caller)
        peer_thread.start();worker.start()
        try:
            assert entered.wait(1)
            if phase.startswith('cancel'):context.cancel()
            worker.join(.5);peer_thread.join(.5)
            if phase=='positive':valid=results==[{'ok':True}] and not errors
            else:valid=not results and bool(errors) and isinstance(errors[0],TaskCancelled if phase.startswith('cancel') else TimeoutError if phase.startswith('deadline') else ValueError)
            return dict(result=valid,closed=not worker.is_alive() and client.fileno()==-1 and peer_eof==[True],
                        watcher_closed=not any(t.name=='asr-http-cancel' for t in threading.enumerate()))
        finally:context.cancel();client.close();server.close();worker.join(1);peer_thread.join(1)


def run():
    checks={}
    for phase in ('cancel_headers','cancel_body','deadline_body','positive','oversized'):
        checks.update({phase+'_'+key:value for key,value in scenario(phase).items()})
    return dict(passed=all(checks.values()),checks=checks)


if __name__=='__main__':emit_result(run())
