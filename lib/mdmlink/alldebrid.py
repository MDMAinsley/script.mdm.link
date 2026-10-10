"""AllDebrid API v4/v4.1. Authentication stays in request headers."""
import json
import time
from urllib.error import HTTPError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

from .errors import PlaybackError, Cancelled
from .files import flatten, match_files, web_url

MESSAGES = {
    'AUTH_BAD_APIKEY':'AllDebrid authorisation is invalid. Authorise again in Tools.',
    'AUTH_MISSING_APIKEY':'Authorise AllDebrid in Tools or enter an API key in settings.',
    'AUTH_BLOCKED':'AllDebrid blocked this connection. Check the account and network/IP approval.',
    'AUTH_USER_BANNED':'AllDebrid account access is unavailable.',
    'PIN_EXPIRED':'AllDebrid PIN expired. Start authorisation again.',
    'PIN_INVALID':'AllDebrid PIN is invalid. Start authorisation again.',
    'MUST_BE_PREMIUM':'An active AllDebrid subscription is required for this source.',
    'MAGNET_MUST_BE_PREMIUM':'An active AllDebrid subscription is required for torrent sources.',
    'MAGNET_TOO_MANY_ACTIVE':'AllDebrid has too many active transfers. Clear completed/unneeded transfers in your account.',
    'NO_SERVER':'AllDebrid does not allow this network/VPN connection.',
    'MAGNET_NO_SERVER':'AllDebrid does not allow this network/VPN connection.',
    'LINK_DOWN':'This source is no longer available. Try another source.',
    'LINK_HOST_UNAVAILABLE':'The source host is unavailable. Try another source.',
    'LINK_HOST_NOT_SUPPORTED':'AllDebrid does not support this source host.',
    'FREE_TRIAL_LIMIT_REACHED':'The AllDebrid trial limit has been reached.',
}


class AllDebrid:
    BASE = 'https://api.alldebrid.com/'

    def __init__(self, addon):
        self.addon = addon
        self.key = addon.getSetting('alldebrid_api_key').strip()

    @property
    def enabled(self):
        return self.addon.getSetting('alldebrid_enabled') == 'true'

    def request(self, endpoint, params=None, authenticated=True):
        if authenticated and not self.key:
            raise PlaybackError(MESSAGES['AUTH_MISSING_APIKEY'])
        headers = {'Accept':'application/json', 'User-Agent':'MDM-Link/0.1.0', 'Content-Type':'application/x-www-form-urlencoded'}
        if authenticated:
            headers['Authorization'] = 'Bearer ' + self.key
        get_endpoint = endpoint in ('v4/user', 'v4.1/pin/get')
        encoded = urlencode(params or {}, doseq=True)
        url = self.BASE + endpoint
        if get_endpoint and encoded:
            url += '?' + encoded
        req = Request(url, data=None if get_endpoint else encoded.encode('utf-8'), headers=headers,
                      method='GET' if get_endpoint else 'POST')
        try:
            with urlopen(req, timeout=15) as response:
                payload = json.loads(response.read().decode('utf-8'))
        except HTTPError as error:
            if error.code in (429, 503):
                raise PlaybackError('AllDebrid is busy or rate-limited. Wait briefly and try again.') from None
            try:
                payload = json.loads(error.read().decode('utf-8'))
            except Exception:
                raise PlaybackError('AllDebrid request failed. Check authorisation and your connection.') from None
        except Exception:
            raise PlaybackError('Could not contact AllDebrid. Check your internet connection and try again.') from None
        if not isinstance(payload, dict):
            raise PlaybackError('AllDebrid returned an invalid response. Try again.')
        if payload.get('status') != 'success':
            error = payload.get('error')
            code = error.get('code') if isinstance(error, dict) else None
            raise PlaybackError(MESSAGES.get(code, 'AllDebrid could not process this source. Check your account or try another source.'))
        data = payload.get('data')
        if not isinstance(data, dict):
            raise PlaybackError('AllDebrid returned an incomplete response. Try again.')
        return data

    def user(self):
        data = self.request('v4/user').get('user')
        if not isinstance(data, dict):
            raise PlaybackError('AllDebrid account information is unavailable.')
        return data

    @staticmethod
    def wait(progress, monitor, seconds=5):
        for _ in range(seconds * 10):
            if progress.iscanceled() or monitor.waitForAbort(0.1):
                raise Cancelled('Playback cancelled.')

    def unlock(self, url, progress, monitor):
        if not web_url(url):
            raise PlaybackError('The source URL is invalid. Search again.')
        data = self.request('v4/link/unlock', {'link':url})
        streams = data.get('streams')
        if not data.get('link') and isinstance(streams, list) and streams:
            video = [s for s in streams if isinstance(s, dict) and str(s.get('quality','')).isdigit() and s.get('id')]
            if not video or not data.get('id'):
                raise PlaybackError('AllDebrid returned no video streams.')
            best = max(video, key=lambda s:int(s['quality']))
            data = self.request('v4/link/streaming', {'id':data['id'], 'stream':best['id']})
        if data.get('delayed'):
            deadline = time.monotonic() + 60
            delayed = data['delayed']
            while time.monotonic() < deadline:
                self.wait(progress, monitor)
                data = self.request('v4/link/delayed', {'id':delayed})
                if data.get('status') == 2:
                    break
                if data.get('status') == 3:
                    raise PlaybackError('AllDebrid could not generate this link. Try another source.')
            else:
                raise PlaybackError('AllDebrid is still preparing this link. Try again later.')
        link = data.get('link')
        if not web_url(link):
            raise PlaybackError('AllDebrid returned no playable URL. Try another source.')
        return link

    def resolve(self, source, progress, monitor, choose):
        if progress.iscanceled() or monitor.abortRequested():
            raise Cancelled('Playback cancelled.')
        if not self.enabled:
            raise PlaybackError('Enable and authorise AllDebrid in your selected provider settings.')
        url = source.get('url', '')
        if not url.startswith('magnet:'):
            return self.unlock(url, progress, monitor)
        data = self.request('v4/magnet/upload', {'magnets[]':[url]})
        magnets = data.get('magnets')
        if not isinstance(magnets, list) or not magnets or not isinstance(magnets[0], dict):
            raise PlaybackError('AllDebrid did not accept this torrent.')
        magnet = magnets[0]
        if magnet.get('error'):
            error = magnet['error']
            code = error.get('code') if isinstance(error, dict) else None
            raise PlaybackError(MESSAGES.get(code, 'AllDebrid rejected this torrent. Try another source.'))
        magnet_id = magnet.get('id')
        if not magnet_id:
            raise PlaybackError('AllDebrid returned no transfer ID.')
        # Check only the selected source; never upload all search results for a cache probe.
        deadline = time.monotonic() + 60
        while True:
            if progress.iscanceled() or monitor.abortRequested():
                raise Cancelled('Playback cancelled.')
            data = self.request('v4.1/magnet/status', {'id':magnet_id})
            rows = data.get('magnets')
            if isinstance(rows, dict):
                rows = [rows]
            status = next((row for row in (rows if isinstance(rows, list) else []) if isinstance(row, dict) and str(row.get('id'))==str(magnet_id)), None)
            if not status:
                raise PlaybackError('AllDebrid transfer status is unavailable.')
            code = status.get('statusCode')
            if code == 4:
                break
            if type(code) is not int or code >= 5:
                raise PlaybackError('AllDebrid could not prepare this torrent. Try another source.')
            if time.monotonic() >= deadline:
                raise PlaybackError('AllDebrid is still downloading this source. It remains in your account; try it again when ready.')
            progress.update(50, 'AllDebrid is preparing the selected source. Cancel to return.')
            self.wait(progress, monitor)
        data = self.request('v4/magnet/files', {'id[]':[magnet_id]})
        rows = data.get('magnets')
        entry = next((row for row in (rows if isinstance(rows,list) else []) if isinstance(row,dict) and str(row.get('id'))==str(magnet_id)), None)
        candidates = match_files(flatten(entry.get('files') if entry else []), source.get('extra',{}).get('item',{}))
        if not candidates:
            raise PlaybackError('No matching video file was found for this title/episode. Try another source.')
        selected = 0 if len(candidates)==1 else choose([f['name'] for f in candidates])
        if selected < 0:
            raise Cancelled('File selection cancelled.')
        return self.unlock(candidates[selected]['url'], progress, monitor)
