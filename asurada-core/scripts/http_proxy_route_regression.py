"""Proxy route construction without network access or user proxy settings."""
from unittest.mock import patch
from urllib.parse import urlsplit
from asurada.cancellable_http import connection_route
from regression_support import emit_result


def run():
    checks={}
    settings={'http':'http://user:pass@proxy.invalid:8080','https':'http://user:pass@proxy.invalid:8080'}
    with patch('asurada.cancellable_http.getproxies',return_value=settings), patch('asurada.cancellable_http.proxy_bypass',return_value=False):
        connection,path,headers=connection_route(urlsplit('http://origin.invalid/v1?q=1'),timeout=1,trust_env=True)
        checks['http_absolute_form']=connection.host=='proxy.invalid' and connection.port==8080 and path=='http://origin.invalid/v1?q=1'
        checks['http_proxy_auth']=headers=={'Proxy-Authorization':'Basic dXNlcjpwYXNz'}
        connection,path,headers=connection_route(urlsplit('https://origin.invalid:8443/v1'),timeout=.5,trust_env=True)
        checks['https_tunnel']=connection.host=='proxy.invalid' and connection._tunnel_host=='origin.invalid' and connection._tunnel_port==8443 and path=='/v1'
        checks['credentials_only_in_tunnel']=headers=={} and connection._tunnel_headers=={'Proxy-Authorization':'Basic dXNlcjpwYXNz'}
        checks['budget_preserved']=connection.timeout==.5
        connection,path,headers=connection_route(urlsplit('https://origin.invalid/v1'),timeout=1,trust_env=False)
        checks['explicit_direct']=connection.host=='origin.invalid' and headers=={} and path=='/v1'
    with patch('asurada.cancellable_http.getproxies',return_value=settings), patch('asurada.cancellable_http.proxy_bypass',return_value=True) as bypass:
        connection,_,_=connection_route(urlsplit('https://origin.invalid:8443/v1'),timeout=1,trust_env=True)
        checks['bypass_host_and_port']=connection.host=='origin.invalid' and bypass.call_args.args==('origin.invalid:8443',)
    with patch('asurada.cancellable_http.getproxies',return_value={'https':'socks5://proxy.invalid:1080'}), patch('asurada.cancellable_http.proxy_bypass',return_value=False):
        try:connection_route(urlsplit('https://origin.invalid'),timeout=1,trust_env=True);checks['unsupported_proxy_rejected']=False
        except ValueError:checks['unsupported_proxy_rejected']=True
    return {'passed':all(checks.values()),'checks':checks,'scope':'route construction only; no real CONNECT, TLS or proxy server'}


if __name__=='__main__':emit_result(run())
