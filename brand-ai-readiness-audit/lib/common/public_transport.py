"""Pin each socket to a validated public address, preserving TLS hostname checks.

Requests must not resolve a validated hostname again when it connects: otherwise
DNS rebinding can turn a public audit into a request to an internal service.
No production switch permits private targets. Loopback fixture tests inject their
own resolver into this module, never a URL-controlled exemption.
"""
import ipaddress
import socket

from requests.adapters import HTTPAdapter
from urllib3.connection import HTTPConnection, HTTPSConnection
from urllib3.connectionpool import HTTPConnectionPool, HTTPSConnectionPool
from urllib3.exceptions import NewConnectionError
from urllib3.util.connection import create_connection


def public_address(host, port):
    addresses = {result[4][0] for result in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)}
    if not addresses:
        raise OSError("No addresses resolved")
    for address in addresses:
        ip = ipaddress.ip_address(address)
        effective = getattr(ip, "ipv4_mapped", None) or ip
        if not effective.is_global or effective.is_multicast or "%" in address:
            raise OSError("Non-public destination excluded by safety policy")
    return sorted(addresses)[0]


class _PinnedSocket:
    def _new_conn(self):
        try:
            address = public_address(self._dns_host, self.port)
            return create_connection((address, self.port), self.timeout,
                                     source_address=self.source_address, socket_options=self.socket_options)
        except (OSError, ValueError) as error:
            raise NewConnectionError(self, str(error)) from error


class PublicHTTPConnection(_PinnedSocket, HTTPConnection):
    pass


class PublicHTTPSConnection(_PinnedSocket, HTTPSConnection):
    pass


class _HTTPPool(HTTPConnectionPool):
    ConnectionCls = PublicHTTPConnection


class _HTTPSPool(HTTPSConnectionPool):
    ConnectionCls = PublicHTTPSConnection


class PublicOnlyAdapter(HTTPAdapter):
    def init_poolmanager(self, *args, **kwargs):
        super().init_poolmanager(*args, **kwargs)
        self.poolmanager.pool_classes_by_scheme = {"http": _HTTPPool, "https": _HTTPSPool}
