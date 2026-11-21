"""HTTP redirect wire behavior on socketpair, sharing one deadline."""
import http.client
import socket
import threading
from unittest.mock import patch
from asurada.cancellable_http import request_json, HttpStatusError
from asurada.task_runtime import TaskContext
from regression_support import emit_result


def scenario(status,location,max_redirects=3):
    observed=[];workers=[];sockets=[]
    def connect(connection):
        client,peer=socket.socketpair();sockets.extend((client,peer));connection.sock=client
        number=len(workers)
        def serve():
            try:
                peer.settimeout(1);data=b''
                while b'\r\n\r\n' not in data:data+=peer.recv(4096)
                head,body=data.split(b'\r\n\r\n',1)
                headers={line.split(b':',1)[0].lower():line.split(b':',1)[1].strip() for line in head.split(b'\r\n')[1:]}
                size=int(headers.get(b'content-length',b'0'))
                while len(body)<size:body+=peer.recv(size-len(body))
                observed.append((head.split(b'\r\n')[0],headers,body))
                if number==0 or location=='/loop':
                    peer.sendall(f'HTTP/1.1 {status} Redirect\r\nLocation: {location}\r\nContent-Length: 0\r\nConnection: close\r\n\r\n'.encode())
                else:peer.sendall(b'HTTP/1.1 200 OK\r\nContent-Length: 11\r\nConnection: close\r\n\r\n{"ok":true}')
            finally:peer.close()
        worker=threading.Thread(target=serve);workers.append(worker);worker.start()
    result=None;error=None
    with patch.object(http.client.HTTPConnection,'connect',connect):
        try:result=request_json('http://origin.test/start',method='POST',body={'x':1},context=TaskContext.start('redirect',1000),timeout_ms=1000,max_redirects=max_redirects,headers={'Authorization':'test'})
        except HttpStatusError as exc:error=str(exc)
        finally:
            for worker in workers:worker.join(1)
            for stream in sockets:stream.close()
    return result,error,observed


def run():
    checks={}
    for status in (307,308,301,302,303):
        result,error,rows=scenario(status,'/next')
        checks[str(status)+'_success']=result=={'ok':True} and error is None and len(rows)==2
        checks[str(status)+'_method_body']=(rows[1][0].startswith(b'POST ') and rows[1][2]==rows[0][2]) if status in (307,308) else (rows[1][0].startswith(b'GET ') and rows[1][2]==b'')
        checks[str(status)+'_remaining_budget']=int(rows[1][1][b'x-asurada-timeout-ms'])<=int(rows[0][1][b'x-asurada-timeout-ms'])
    _,error,rows=scenario(307,'http://other.test/next')
    checks['cross_origin_not_contacted']=len(rows)==1 and error=='http_cross_origin_redirect_rejected'
    _,error,rows=scenario(307,'/loop',2)
    checks['bounded_loop']=len(rows)==3 and error=='http_redirect_limit'
    return {'passed':all(checks.values()),'checks':checks,'scope':'HTTP wire via socketpair; no real DNS/TCP or external endpoint'}


if __name__=='__main__':emit_result(run())
