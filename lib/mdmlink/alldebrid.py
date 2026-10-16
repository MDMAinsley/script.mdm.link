"""AllDebrid API v4/v4.1. Authentication stays in request headers."""
from . import device_policy,connection_policy
import json
from contextlib import contextmanager
import time
from urllib.error import HTTPError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

from .errors import PlaybackError, Cancelled, SourceFailure, SourcePreparing, SourceNotReady, AutoplayBudgetExpired
from . import autoplay_context
from .models import quality
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

    def __init__(self, addon, policy_addons=()):
        self.addon = addon
        self.policies=(addon,)+tuple(policy_addons)
        self.key = addon.getSetting('alldebrid_api_key').strip()
        self.deadline = None

    @contextmanager
    def resolution_budget(self):
        previous = self.deadline
        if previous is None:
            autoplay_context.check()
            remaining = autoplay_context.remaining()
            self.deadline = time.monotonic() + (min(45, remaining) if remaining is not None else 45)
        try:
            yield
        finally:
            self.deadline = previous

    def remaining(self):
        return None if self.deadline is None else max(0, self.deadline - time.monotonic())

    def timeout_error(self):
        autoplay_context.check()
        return (SourceNotReady if autoplay_context.active() else SourcePreparing)(self.timeout_message())

    @staticmethod
    def timeout_message():
        return ('AllDebrid did not finish preparing the selected source within the 45-second resolution budget. '
                'It may still be downloading or generating a link. Try another ready source or retry later; '
                'any created transfer remains in your account.')

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
        remaining = self.remaining()
        if remaining is not None and remaining <= 0:
            raise self.timeout_error()
        timeout = device_policy.integer(self.addon,"device_request_timeout",15,10,60)
        if remaining is not None:
            timeout = min(timeout, remaining)
        try:
            with urlopen(req, timeout=timeout) as response:
                payload = json.loads(response.read().decode('utf-8'))
        except HTTPError as error:
            if error.code in (429, 503):
                raise PlaybackError('AllDebrid is busy or rate-limited. Wait briefly and try again.') from None
            try:
                payload = json.loads(error.read().decode('utf-8'))
            except Exception:
                raise PlaybackError('AllDebrid request failed. Check authorisation and your connection.') from None
        except Exception:
            if self.remaining() == 0:
                raise self.timeout_error() from None
            raise PlaybackError('Could not contact AllDebrid. Check your internet connection and try again.') from None
        if self.remaining() == 0:
            raise self.timeout_error()
        if not isinstance(payload, dict):
            raise PlaybackError('AllDebrid returned an invalid response. Try again.')
        if payload.get('status') != 'success':
            error = payload.get('error')
            code = error.get('code') if isinstance(error, dict) else None
            failure = SourceFailure if code in ('LINK_DOWN','LINK_HOST_UNAVAILABLE','LINK_HOST_NOT_SUPPORTED','MAGNET_INVALID_ID','MAGNET_INVALID_URI','MAGNET_INVALID') else PlaybackError
            raise failure(MESSAGES.get(code, 'AllDebrid could not process this source. Check your account or try another source.'))
        data = payload.get('data')
        if not isinstance(data, dict):
            raise PlaybackError('AllDebrid returned an incomplete response. Try again.')
        return data

    def user(self):
        data = self.request('v4/user').get('user')
        if not isinstance(data, dict):
            raise PlaybackError('AllDebrid account information is unavailable.')
        return data

    def wait(self, progress, monitor, seconds=5):
        remaining = self.remaining()
        if remaining is not None and remaining < seconds:
            raise self.timeout_error()
        for _ in range(seconds * 10):
            if progress.iscanceled() or monitor.waitForAbort(0.1):
                raise Cancelled('Playback cancelled.')

    def eligible(self,row):
        for addon in self.policies:
            try:connection_policy.validate_settings(addon)
            except ValueError as error:raise PlaybackError(str(error)) from None
        return all(device_policy.allows(addon,row) and connection_policy.allows(addon,row) for addon in self.policies)

    @staticmethod
    def file_candidate(file, source):
        row = dict(file)
        extra = dict(source.get('extra') or {})
        extra['size_scope'] = 'file'
        reported = quality(file.get('name'))
        if reported == 'Unknown':
            height = device_policy.height(source)
            reported = str(height) + 'p' if height else 'Unknown'
            extra['quality_origin'] = 'source_report' if height else 'unknown'
        else:
            extra['quality_origin'] = 'file_name'
        row.update(size_bytes=file.get('size'), quality=reported, debrid=True, extra=extra)
        # The file row deliberately has its own name, not the release label.
        # Explicit file quality takes precedence; fallback is reported metadata,
        # not a claim to have measured/decoded the file.
        return row

    def exclusions(self, row):
        reasons = set()
        for addon in self.policies:
            try:
                connection_policy.validate_settings(addon)
            except ValueError as error:
                raise PlaybackError(str(error)) from None
            height = device_policy.height(row)
            if not device_policy.allows(addon, row):
                reasons.add('unknown quality hidden' if height is None else 'maximum reported quality')
            size = connection_policy.size_gib(row)
            maximum = connection_policy.decimal(addon, 'device_max_size_gib', 10000)
            if maximum:
                if size is None and connection_policy.setting(addon, 'device_unknown_size', 'Show') == 'Hide':
                    reasons.add('unknown file size hidden')
                elif size is not None and size > maximum:
                    reasons.add('maximum file size')
            state, _ = connection_policy.assessment(addon, row)
            if state == 'Above budget' and connection_policy.setting(addon, 'device_slow_sources', 'Show') == 'Hide':
                reasons.add('connection bitrate budget')
            if state == 'Unknown' and connection_policy.setting(addon, 'device_unknown_bitrate', 'Show') == 'Hide':
                reasons.add('unknown bitrate hidden')
        return reasons

    @staticmethod
    def reported(data,source=None):
        row=dict(source or {});extra=dict(row.get('extra') or {});row['extra']=extra
        if 'filesize' in data:
            row['size_bytes']=data['filesize'];extra['size_scope']='file'
        if isinstance(data.get('filename'),str):row['name']=data['filename']
        return row

    def unlock(self, url, progress, monitor, source=None):
        with self.resolution_budget():
            return self._unlock(url, progress, monitor, source)

    def _unlock(self, url, progress, monitor, source=None):
        if progress.iscanceled() or monitor.abortRequested():
            raise Cancelled('Playback cancelled.')
        progress.update(85, 'AllDebrid: generating the selected video link (45s total preparation budget).')
        if not web_url(url):
            raise SourceFailure('The source URL is invalid. Search again.')
        data = self.request('v4/link/unlock', {'link':url})
        streams = data.get('streams')
        if not data.get('link') and isinstance(streams, list) and streams:
            video = [s for s in streams if isinstance(s, dict) and str(s.get('quality','')).isdigit() and s.get('id')]
            if not video or not data.get('id'):
                raise SourceFailure('AllDebrid returned no video streams.')
            candidates=[]
            for stream in video:
                row=self.reported(stream,source);row['quality']=str(stream['quality'])+'p';row['debrid']=True
                if self.eligible(row):candidates.append((stream,row))
            if not candidates:raise SourceFailure('No debrid stream remains under current source preferences.')
            ordered=connection_policy.order(self.policies[-1],[row for stream,row in candidates])
            best=next(stream for stream,row in candidates if row is ordered[0])
            source=ordered[0]
            data = self.request('v4/link/streaming', {'id':data['id'], 'stream':best['id']})
        source=self.reported(data,source)
        if not self.eligible(source):raise SourceFailure('Resolved file is excluded by current quality, file-size or connection preferences.')
        if data.get('delayed'):
            deadline = self.deadline
            delayed = data['delayed']
            checks = 0
            while time.monotonic() < deadline:
                if autoplay_context.active() and checks >= 3:
                    raise SourceNotReady('The selected AllDebrid link is still being generated after short readiness checks.')
                self.wait(progress, monitor, 2 if autoplay_context.active() else 5)
                checks += 1
                data = self.request('v4/link/delayed', {'id':delayed})
                source=self.reported(data,source)
                if not self.eligible(source):raise SourceFailure('Resolved file is excluded by current source preferences.')
                if data.get('status') == 2:
                    break
                if data.get('status') == 3:
                    raise SourceFailure('AllDebrid could not generate this link. Try another source.')
            else:
                raise PlaybackError('AllDebrid is still preparing this link. Try again later.')
        link = data.get('link')
        if not web_url(link):
            raise SourceFailure('AllDebrid returned no playable URL. Try another source.')
        return link

    def resolve(self, source, progress, monitor, choose):
        with self.resolution_budget():
            return self._resolve(source, progress, monitor, choose)

    def _resolve(self, source, progress, monitor, choose):
        if progress.iscanceled() or monitor.abortRequested():
            raise Cancelled('Playback cancelled.')
        if not self.enabled:
            raise PlaybackError('Enable and authorise AllDebrid in your selected provider settings.')
        if not self.eligible(source):raise PlaybackError('This source is excluded by current source preferences. Search again.')
        url = source.get('url', '')
        if not url.startswith('magnet:'):
            return self.unlock(url, progress, monitor,source)
        progress.update(10, 'AllDebrid: checking the selected release; availability is not yet verified.')
        data = self.request('v4/magnet/upload', {'magnets[]':[url]})
        magnets = data.get('magnets')
        if not isinstance(magnets, list) or not magnets or not isinstance(magnets[0], dict):
            raise SourceFailure('AllDebrid did not accept this torrent.')
        magnet = magnets[0]
        if magnet.get('error'):
            error = magnet['error']
            code = error.get('code') if isinstance(error, dict) else None
            raise (SourceFailure if code in ('MAGNET_INVALID','MAGNET_INVALID_URI','MAGNET_INVALID_ID') else PlaybackError)(MESSAGES.get(code, 'AllDebrid rejected this torrent. Try another source.'))
        magnet_id = magnet.get('id')
        if not magnet_id:
            raise PlaybackError('AllDebrid returned no transfer ID.')
        # Check only the selected source; never upload all search results for a cache probe.
        deadline = self.deadline
        checks = 0
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
                raise SourceFailure('AllDebrid could not prepare this torrent. Try another source.')
            if autoplay_context.active() and checks >= 3:
                raise SourceNotReady('The selected AllDebrid release is still not ready after short readiness checks; any submitted transfer remains in your account.')
            if time.monotonic() >= deadline:
                raise self.timeout_error()
            progress.update(50, 'AllDebrid: selected release is still downloading/preparing ({}s left). Cancel to return.'.format(max(0, int(self.remaining()))))
            self.wait(progress, monitor, 2 if autoplay_context.active() else 5)
            checks += 1
        data = self.request('v4/magnet/files', {'id[]':[magnet_id]})
        rows = data.get('magnets')
        entry = next((row for row in (rows if isinstance(rows,list) else []) if isinstance(row,dict) and str(row.get('id'))==str(magnet_id)), None)
        progress.update(75, 'AllDebrid: matching video files and checking your source preferences.')
        if entry is None or entry.get('error'):
            raise SourceFailure('AllDebrid could not return the selected release file list. Retry it or try another source.')
        files = flatten(entry.get('files'))
        videos = match_files(files, {})
        if not videos:
            raise SourceFailure('No supported video files were returned for this release (samples/trailers excluded). Try another source.')
        media = source.get('extra',{}).get('item',{})
        matches = match_files(videos, media)
        if not matches:
            expected = 'S{:02d}E{:02d}'.format(int(media['season']), int(media['episode'])) if media.get('media_type') == 'episode' else 'this title'
            raise SourceFailure('No matching video file for {} was found in this release. No different episode was selected; try another source.'.format(expected))
        candidates = [self.file_candidate(file, source) for file in matches]
        allowed = []; reasons = set()
        for file in candidates:
            excluded = self.exclusions(file)
            if excluded:
                reasons.update(excluded)
            else:
                allowed.append(file)
        candidates = connection_policy.order(self.policies[-1], allowed)
        if not candidates:
            raise SourceFailure('Matching video files were found, but all were excluded by: {}. Check preferences in Flix and your selected provider, or try another source.'.format(', '.join(sorted(reasons))))
        if len(candidates) == 1:
            selected = 0
        else:
            choosing = time.monotonic()
            try:
                selected = choose([f['name'] for f in candidates])
            finally:
                # A user's time in the file chooser is not network preparation.
                elapsed = max(0, time.monotonic() - choosing)
                self.deadline += elapsed
                autoplay_context.exclude_choice_time(elapsed)
        if selected < 0:
            raise Cancelled('File selection cancelled.')
        if type(selected) is not int or selected>=len(candidates):raise PlaybackError('Invalid file selection.')
        return self.unlock(candidates[selected]['url'], progress, monitor,candidates[selected])
