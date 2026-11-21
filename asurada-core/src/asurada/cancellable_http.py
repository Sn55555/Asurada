"""Direct JSON HTTP transport with an owned socket and one task budget."""
from contextlib import contextmanager
import http.client
import json
import socket
import threading
import time
import base64
from urllib.parse import urlsplit, unquote, urljoin
from urllib.request import getproxies, proxy_bypass
from .task_runtime import TaskContext, TaskCancelled
from .http_connection import CancellableHTTPSConnection, connect_socket


class HttpStatusError(RuntimeError):
    pass


class HttpRedirect(HttpStatusError):
    def __init__(self,status,location):
        super().__init__('http_redirect:'+str(status))
        self.status,self.location=status,location


def connection_route(target, *, timeout, trust_env):
    """HTTP proxies, including CONNECT for TLS origins; bypass follows urllib."""
    path=(target.path or '/')+('?' + target.query if target.query else '')
    proxy=getproxies().get(target.scheme) if trust_env and not proxy_bypass(target.netloc) else None
    kind=CancellableHTTPSConnection if target.scheme=='https' else http.client.HTTPConnection
    if not proxy:
        return kind(target.hostname,target.port,timeout=timeout),path,{}
    parsed=urlsplit(proxy if '://' in proxy else 'http://'+proxy)
    if parsed.scheme!='http' or not parsed.hostname or parsed.query or parsed.fragment or parsed.path not in ('','/'):
        raise ValueError('unsupported_http_proxy_configuration')
    proxy_headers={}
    if parsed.username is not None:
        credentials=unquote(parsed.username)+':'+unquote(parsed.password or '')
        proxy_headers['Proxy-Authorization']='Basic '+base64.b64encode(credentials.encode()).decode('ascii')
    connection=kind(parsed.hostname,parsed.port or 80,timeout=timeout)
    if target.scheme=='https':
        connection.set_tunnel(target.hostname,target.port or 443,headers=proxy_headers)
        return connection,path,{}
    return connection,target.geturl(),proxy_headers


def request_json(url, *, method, body, context, timeout_ms, max_response_bytes=4*1024*1024,
                 headers=None, include_response_headers=False, propagate_budget=True,
                 connect_timeout_s=None, read_timeout_s=None, trust_env=False, max_redirects=0):
    if isinstance(max_redirects,bool) or not isinstance(max_redirects,int) or not 0<=max_redirects<=10:
        raise ValueError('invalid_redirect_limit')
    task=TaskContext(context.task_id,min(context.deadline,time.monotonic()+timeout_ms/1000),context.cancellation)
    def origin(value):
        parsed=urlsplit(value)
        return parsed.scheme,parsed.hostname,parsed.port or (443 if parsed.scheme=='https' else 80)
    request_headers=dict(headers or {})
    for hop in range(max_redirects+1):
        task.remaining()
        try:
            return _request_json_once(url,method=method,body=body,context=task,timeout_ms=timeout_ms,
                max_response_bytes=max_response_bytes,headers=request_headers,
                include_response_headers=include_response_headers,propagate_budget=propagate_budget,
                connect_timeout_s=connect_timeout_s,read_timeout_s=read_timeout_s,trust_env=trust_env)
        except HttpRedirect as redirect:
            task.remaining()
            if hop==max_redirects:raise HttpStatusError('http_redirect_limit') from redirect
            if not redirect.location:raise HttpStatusError('http_redirect_missing_location') from redirect
            destination=urlsplit(urljoin(url,redirect.location))._replace(fragment='').geturl()
            if origin(destination)!=origin(url):raise HttpStatusError('http_cross_origin_redirect_rejected') from redirect
            if redirect.status==303 and method!='HEAD' or redirect.status in (301,302) and method=='POST':
                method,body='GET',None
                request_headers={k:v for k,v in request_headers.items() if k.lower() not in {'content-type','content-length'}}
            url=destination


@contextmanager
def _open_response(url, *, method, body, context, timeout_ms, max_response_bytes,
                 headers, include_response_headers, propagate_budget,
                 connect_timeout_s, read_timeout_s, trust_env):
    target=urlsplit(url)
    if target.scheme not in {'http','https'} or not target.hostname or target.username or target.password or target.fragment:
        raise ValueError('unsupported_direct_http_url')
    task=TaskContext(context.task_id,min(context.deadline,time.monotonic()+timeout_ms/1000),context.cancellation)
    connection,path,proxy_headers=connection_route(target,trust_env=trust_env,
        timeout=min(task.remaining(),connect_timeout_s) if connect_timeout_s is not None else task.remaining())
    connection._create_connection=lambda address,timeout,source_address: connect_socket(
        address,timeout,source_address,context=task)
    stop=threading.Event()
    owned_socket=None
    response=None
    def shutdown():
        current=owned_socket if owned_socket is not None else connection.sock
        if current is not None:
            try:current.shutdown(socket.SHUT_RDWR)
            except OSError:pass
    def watch():
        while not stop.wait(.02):
            try:task.remaining()
            except (TaskCancelled,TimeoutError):
                # Connect/TLS can replace .sock while cancellation races it.
                # Keep shutting down the current owner until final cleanup.
                shutdown()
    watcher=threading.Thread(target=watch,name='asr-http-cancel',daemon=True)
    watcher.start()
    try:
        connection.connect()
        # Keep the socket even when HTTPConnection clears .sock for Connection: close.
        owned_socket=connection.sock
        task.remaining()
        connection.sock.settimeout(min(task.remaining(),read_timeout_s) if read_timeout_s is not None else task.remaining())
        data=None if body is None else json.dumps(body,ensure_ascii=False,allow_nan=False).encode()
        request_headers={'Content-Type':'application/json',**(headers or {}),**proxy_headers}
        if propagate_budget:
            request_headers['X-Asurada-Timeout-Ms']=str(max(1,int(task.remaining()*1000)))
        connection.request(method,path,body=data,headers=request_headers)
        task.remaining()
        response=connection.getresponse()
        task.remaining()
        yield task, response
    except Exception:
        task.remaining()
        raise
    finally:
        stop.set()
        shutdown()
        watcher.join()
        if response is not None:response.close()
        connection.close()


def _request_json_once(url, **options):
    with _open_response(url, **options) as (task, response):
        max_response_bytes = options['max_response_bytes']
        include_response_headers = options['include_response_headers']
        payload=response.read(max_response_bytes+1)
        task.remaining()
        if len(payload)>max_response_bytes:raise ValueError('http_response_too_large')
        if response.status in (301,302,303,307,308):
            raise HttpRedirect(response.status,response.getheader('Location'))
        if not 200<=response.status<300:
            raise HttpStatusError(f'voice_sidecar_http_error:{response.status}:{payload.decode("utf-8",errors="replace")}')
        result=json.loads(payload)
        task.remaining()
        return (result,{key.lower():value for key,value in response.getheaders()}) if include_response_headers else result


def iter_http_lines(url, *, body, headers, context, connect_timeout_s=None, read_timeout_s=None,
                    max_line_bytes=1024*1024, max_response_bytes=32*1024*1024,
                    propagate_budget=False, trust_env=True):
    """Bounded HTTP lines with cancellation owning the full iterator lifetime.

    Streaming redirects are rejected before emitting any application data.
    """
    with _open_response(url, method='POST', body=body, headers=headers, context=context,
            timeout_ms=max(1,int(context.remaining()*1000)), max_response_bytes=max_response_bytes,
            include_response_headers=False, propagate_budget=propagate_budget, trust_env=trust_env,
            connect_timeout_s=connect_timeout_s, read_timeout_s=read_timeout_s) as (task, response):
        if not 200 <= response.status < 300:
            raise HttpStatusError('stream_http_status:' + str(response.status))
        total = 0
        while True:
            task.remaining()
            line = response.readline(max_line_bytes+1)
            task.remaining()
            if not line:
                return
            total += len(line)
            if len(line) > max_line_bytes or total > max_response_bytes:
                raise ValueError('http_stream_size_limit')
            yield line.rstrip(b'\r\n')
