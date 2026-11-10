"""Search a user-configured Torznab feed for hash-based debrid candidates."""
import hashlib
import ipaddress
import re
from urllib.parse import urlencode, urlsplit, urlunsplit

from .connection_policy import bytes_gib
from .files import web_url
from .models import info_hash, magnet_hash, text
from .transport import ProviderRequestError


TORZNAB_ATTR = '{http://torznab.com/schemas/2015/feed}attr'


def endpoint(value):
    if not web_url(value):
        raise ProviderRequestError('torznab_configuration')
    parts = urlsplit(value)
    if parts.query or parts.fragment:
        raise ProviderRequestError('torznab_configuration')
    if parts.scheme == 'http' and parts.hostname != 'localhost':
        try:
            address = ipaddress.ip_address(parts.hostname)
        except ValueError:
            raise ProviderRequestError('torznab_configuration') from None
        if not address.is_loopback and (not address.is_private or address.is_link_local or address.is_unspecified):
            raise ProviderRequestError('torznab_configuration')
    path = parts.path.rstrip('/')
    if not path.endswith('/api'):
        path += '/api'
    return urlunsplit((parts.scheme, parts.netloc, path, '', ''))


class TorznabProvider:
    id = 'torznab'
    name = 'Torznab'

    def __init__(self, base, api_key):
        self.base = base
        self.api_key = api_key

    @property
    def signature(self):
        return hashlib.sha256((self.base + '\0' + self.api_key).encode()).hexdigest()

    def search(self, media, context):
        url = endpoint(self.base)
        if len(self.api_key) > 256 or any(ord(char) < 33 or ord(char) > 126 for char in self.api_key):
            raise ProviderRequestError('torznab_configuration')
        params = {'limit': 100, 'extended': 1}
        if self.api_key:
            params['apikey'] = self.api_key
        if media['media_type'] == 'episode':
            params.update(t='tvsearch', cat=5000, q=media['tvshowtitle'], season=media['season'], ep=media['episode'])
        else:
            params.update(t='movie', cat=2000, q=media['title'])
            if media.get('year'):
                params['year'] = media['year']
        root = context.xml(url + '?' + urlencode(params))
        if root.tag == 'error' or root.find('error') is not None:
            raise ProviderRequestError('torznab_error')
        channel = root.find('channel')
        if root.tag != 'rss' or channel is None:
            raise ProviderRequestError('invalid_response')
        rows = []
        for item in channel.findall('item')[:100]:
            context.check()
            attributes = {node.get('name', '').lower(): node.get('value', '') for node in item.findall(TORZNAB_ATTR)}
            reported_imdb = attributes.get('imdb', attributes.get('imdbid', '')).removeprefix('tt').lstrip('0')
            if media.get('imdb_id') and re.fullmatch(r'[0-9]+', reported_imdb) and reported_imdb != media['imdb_id'][2:].lstrip('0'):
                continue
            enclosure = item.find('enclosure')
            digest = (info_hash(attributes.get('infohash')) or magnet_hash(attributes.get('magneturl'))
                      or magnet_hash(item.findtext('link'))
                      or (magnet_hash(enclosure.get('url')) if enclosure is not None else None))
            label = text(item.findtext('title'))
            if not digest or not label:
                continue
            raw_size = item.findtext('size') or attributes.get('size') or (
                enclosure.get('length', '') if enclosure is not None else '')
            size = bytes_gib(int(raw_size)) if re.fullmatch(r'[0-9]{1,15}', raw_size.strip()) else None
            rows.append({'url': 'magnet:?xt=urn:btih:' + digest, 'access': 'debrid',
                         'label': label, 'size': size or '', 'size_scope': 'package'})
        return rows
