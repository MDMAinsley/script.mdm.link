"""Bounded metadata reads. Errors deliberately omit URLs and upstream bodies."""
from http.client import HTTPException, HTTPSConnection
import json
import re
import socket
import ssl
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from .errors import PlaybackError, Cancelled
from .files import web_url

MAX_BYTES=4*1024*1024
FAILURE_REASONS = frozenset({
    'http_error', 'dns_error', 'tls_certificate', 'tls_error', 'request_timeout',
    'connection_error', 'connection_interrupted', 'invalid_json', 'invalid_response',
    'response_too_large', 'invalid_stream_list', 'search_budget', 'proxy_configuration',
})


class ProviderRequestError(PlaybackError):
    def __init__(self, reason, http_status=None, retryable=False):
        super().__init__('Provider search failed ({}). Check Diagnostics.'.format(
            'HTTP {}'.format(http_status) if http_status else reason))
        self.reason = reason
        self.http_status = http_status
        self.retryable = retryable


def connection_error(error):
    cause = error.reason if isinstance(error, URLError) else error
    if isinstance(cause, socket.gaierror):
        return ProviderRequestError('dns_error', retryable=cause.errno == socket.EAI_AGAIN)
    if isinstance(cause, ssl.SSLCertVerificationError):
        return ProviderRequestError('tls_certificate')
    if isinstance(cause, ssl.SSLError):
        return ProviderRequestError('tls_error')
    if isinstance(cause, TimeoutError):
        return ProviderRequestError('request_timeout', retryable=True)
    if isinstance(cause, (HTTPException, ConnectionResetError, ConnectionAbortedError)):
        return ProviderRequestError('connection_interrupted', retryable=True)
    return ProviderRequestError('connection_error')


def proxy_address(value):
    # This setting accepts a trusted HTTP CONNECT proxy without credentials.
    try:
        if not isinstance(value, str) or len(value) > 256 or any(ord(ch) <= 32 for ch in value):
            raise ValueError()
        target = urlsplit(value)
        host, port = target.hostname, target.port
        if (target.scheme != 'http' or target.username is not None or target.password is not None
                or not host or not re.fullmatch(r'[A-Za-z0-9.:-]+', host)
                or not port or target.path not in ('', '/') or target.query or target.fragment):
            raise ValueError()
        return host, port
    except ValueError:
        raise ProviderRequestError('proxy_configuration') from None


def proxy_response(request, address, timeout):
    origin = urlsplit(request.full_url)
    if origin.scheme != 'https' or not origin.hostname or origin.username is not None:
        raise ProviderRequestError('proxy_configuration')
    connection = HTTPSConnection(*address, timeout=timeout, context=ssl.create_default_context())
    try:
        connection.set_tunnel(origin.hostname, origin.port or 443)
        path = origin.path or '/'
        if origin.query:
            path += '?' + origin.query
        headers = {'Host': origin.netloc, 'Accept': 'application/json', 'User-Agent': 'MDM-Link/0.1.0'}
        connection.request('GET', path, headers=headers)
        with connection.getresponse() as response:
            if not 200 <= response.status < 300:
                raise ProviderRequestError('http_error', response.status)
            return response.read(MAX_BYTES + 1)
    finally:
        connection.close()


class Context:
    def __init__(self, stop, deadline, fetch=None, request_timeout=10):
        self.stop,self.deadline,self.fetch=stop,deadline,fetch
        self.used_proxy = False
        self.request_timeout=request_timeout if type(request_timeout) is int and 10<=request_timeout<=60 else 10

    def check(self):
        if self.stop.is_set(): raise Cancelled('Source search cancelled.')
        if time.monotonic() >= self.deadline:
            raise ProviderRequestError('search_budget')

    def _read_json(self, request, proxy=None, reserve=0):
        self.check()
        timeout = max(0.1, min(self.request_timeout, self.deadline - time.monotonic() - reserve))
        try:
            if proxy:
                raw = proxy_response(request, proxy, timeout)
            else:
                with urlopen(request, timeout=timeout) as response:
                    raw = response.read(MAX_BYTES + 1)
        except HTTPError as error:
            retryable = error.code in (500, 502, 503, 504) and not (
                error.headers and error.headers.get('Retry-After'))
            error.close()
            raise ProviderRequestError('http_error', error.code, retryable) from None
        except (OSError, HTTPException) as error:
            raise connection_error(error) from None
        if len(raw) > MAX_BYTES:
            raise ProviderRequestError('response_too_large')
        try:
            return json.loads(raw.decode('utf-8'))
        except (ValueError, RecursionError):
            raise ProviderRequestError('invalid_json') from None

    def json(self, url, *, retry=False, proxy=''):
        self.check()
        if not web_url(url):
            raise PlaybackError('Provider address is invalid. Check Link settings.')
        if self.fetch:
            result = self.fetch(url)
        else:
            request = Request(url, headers={'User-Agent':'MDM-Link/0.1.0','Accept':'application/json'})
            reserve = min(4, max(0, (self.deadline - time.monotonic()) / 2)) if proxy else 0
            try:
                result = self._read_json(request, reserve=reserve)
            except ProviderRequestError as error:
                remaining = self.deadline - time.monotonic()
                proxy_eligible = error.retryable or error.reason in ('dns_error', 'connection_error')
                if proxy and proxy_eligible and remaining >= 0.5:
                    self.check()
                    address = proxy_address(proxy)
                    self.used_proxy = True
                    result = self._read_json(request, proxy=address)
                elif retry and error.retryable and remaining >= 2:
                    self.stop.wait(0.25)
                    result = self._read_json(request)
                else:
                    raise
        self.check()
        if not isinstance(result, dict):
            raise ProviderRequestError('invalid_response')
        return result
