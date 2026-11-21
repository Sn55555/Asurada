"""Actual TLS/CONNECT over socketpair; no TCP listener or external provider."""
import http.client
import shutil
import socket
import ssl
import subprocess
import tempfile
import threading
from pathlib import Path
from unittest.mock import patch
from asurada.cancellable_http import request_json
from asurada.task_runtime import TaskContext, TaskCancelled
from regression_support import emit_result


def scenario(cert,key,mode):
    client,peer=socket.socketpair()
    peer.settimeout(2)
    context=TaskContext.start(mode,1500)
    observations=[];peer_errors=[]
    server_context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_context.load_cert_chain(cert,key)
    trusted=ssl.create_default_context(cafile=str(cert)) if mode!='untrusted' else ssl.create_default_context()
    proxy=mode in {'proxy_success','tunnel_cancel'}
    def read_headers(stream):
        data=b''
        while not data.endswith(b'\r\n\r\n'):
            block=stream.recv(1)
            if not block:raise EOFError('peer_closed')
            data+=block
            if len(data)>65536:raise ValueError('test_header_limit')
        return data
    def serve():
        stream=peer
        try:
            if proxy:
                observations.append(read_headers(stream))
                if mode=='tunnel_cancel':
                    context.cancel()
                    observations.append(stream.recv(1));return
                stream.sendall(b'HTTP/1.0 200 Connection established\r\n\r\n')
            if mode=='handshake_cancel':
                assert stream.recv(4096)
                context.cancel()
                observations.append(stream.recv(1));return
            stream=server_context.wrap_socket(stream,server_side=True)
            observations.append(read_headers(stream))
            stream.sendall(b'HTTP/1.1 200 OK\r\nContent-Length: 11\r\nConnection: close\r\n\r\n{"ok":true}')
        except Exception as exc:peer_errors.append(type(exc).__name__)
        finally:stream.close()
    def connect(connection):
        connection.sock=client
        if connection._tunnel_host:connection._tunnel()
    worker=threading.Thread(target=serve)
    result=None;error=None
    with patch.object(http.client.HTTPConnection,'connect',connect),patch('ssl._create_default_https_context',return_value=trusted),patch('asurada.cancellable_http.getproxies',return_value={'https':'http://user:pass@proxy.test:8080'}),patch('asurada.cancellable_http.proxy_bypass',return_value=False):
        worker.start()
        try:
            host='wrong.test' if mode=='wrong_hostname' else 'origin.test'
            result=request_json('https://'+host+'/v1',method='GET',body=None,context=context,timeout_ms=1500,trust_env=proxy)
        except Exception as exc:error=exc
        finally:
            context.cancel();worker.join(2);client.close();peer.close()
    checks={'peer_terminated':not worker.is_alive()}
    if mode in {'success','proxy_success'}:
        checks['valid_response']=result=={'ok':True} and error is None and not peer_errors
        checks['origin_request']=observations[-1].startswith(b'GET /v1 HTTP/1.1\r\n') and b'Proxy-Authorization' not in observations[-1]
        if proxy:checks['connect_wire']=observations[0].startswith((b'CONNECT origin.test:443 HTTP/1.0\r\n',b'CONNECT origin.test:443 HTTP/1.1\r\n')) and b'Proxy-Authorization: Basic dXNlcjpwYXNz' in observations[0]
    elif mode in {'untrusted','wrong_hostname'}:
        checks['certificate_rejected']=isinstance(error,ssl.SSLCertVerificationError) and result is None
    else:
        checks['cancelled_and_closed']=isinstance(error,TaskCancelled) and observations[-1:]==[b'']
    return checks


def run():
    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp);cert=root/'cert.pem';key=root/'key.pem';config=root/'openssl.cnf'
        config.write_text('[req]\ndistinguished_name=dn\nx509_extensions=ext\nprompt=no\n[dn]\nCN=origin.test\n[ext]\nsubjectAltName=DNS:origin.test\nbasicConstraints=critical,CA:TRUE\n')
        subprocess.run([shutil.which('openssl') or 'openssl','req','-x509','-newkey','rsa:2048','-nodes','-days','1','-config',str(config),'-keyout',str(key),'-out',str(cert)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=True,timeout=15)
        checks={}
        for mode in ('success','proxy_success','untrusted','wrong_hostname','handshake_cancel','tunnel_cancel'):
            checks.update({mode+'_'+k:v for k,v in scenario(cert,key,mode).items()})
        return {'passed':all(checks.values()),'checks':checks,'scope':'real TLS and CONNECT on local socketpair with ephemeral certificate; TCP connect/DNS and live provider excluded'}


if __name__=='__main__':emit_result(run())
