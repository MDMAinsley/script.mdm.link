"""Versioned API consumed by Flix and future frontends."""
from . import device_policy,connection_policy
import json
from . import API_VERSION
from .alldebrid import AllDebrid
from .errors import PlaybackError, Cancelled
from .files import web_url
from .models import item, magnet_hash
from .providers import ArchiveProvider, StreamProvider
from .torznab import TorznabProvider
from .engine import CUSTOM_PROVIDER_SLOTS, search as run_search
from .transport import FAILURE_REASONS, TORRENTIO_HOST

MODES=('Free','Debrid','Combined')
STREAM_IDS = tuple('stream_{}'.format(slot) for slot in range(1, CUSTOM_PROVIDER_SLOTS + 1))
CONFIGURED_IDS = ('torznab',) + STREAM_IDS
PROVIDER_IDS = ('archive', 'torrentio') + CONFIGURED_IDS

def mode(addon):
    setting=addon.getSetting('source_mode') or 'Combined'
    return setting if setting in MODES else 'Combined'

def migrate(addon,legacy):
    """Copy once inside Kodi; never reimport credentials after local disconnect."""
    if addon.getSetting('flix_account_imported')=='true': return
    if not addon.getSetting('alldebrid_api_key') and legacy.getSetting('alldebrid_api_key'):
        addon.setSetting('alldebrid_api_key',legacy.getSetting('alldebrid_api_key'))
        addon.setSetting('alldebrid_enabled',legacy.getSetting('alldebrid_enabled') or 'false')
    addon.setSetting('flix_account_imported','true')

def debrid_ready(addon):
    client=AllDebrid(addon)
    return client.enabled and bool(client.key)

def configured(addon):
    try:connection_policy.validate_settings(addon)
    except ValueError as error:raise PlaybackError(str(error)) from None
    if mode(addon)=='Debrid' and not debrid_ready(addon):
        raise PlaybackError('Enable and authorise AllDebrid in MDM Link, or choose Free/Combined mode.')

def registry(addon):
    providers=[]; selected=mode(addon)
    use_debrid = selected != 'Free' and debrid_ready(addon)
    if selected!='Debrid' and addon.getSetting('provider_archive')!='false': providers.append(ArchiveProvider())
    if use_debrid and addon.getSetting('provider_torrentio')!='false':
        proxy = addon.getSetting('provider_torrentio_proxy').strip()
        providers.append(StreamProvider('torrentio', 'Torrentio', f'https://{TORRENTIO_HOST}', True,
                                        metadata_proxy=proxy,
                                        metadata_ipv4=addon.getSetting('device_torrentio_ipv4') == 'true'))
    torznab_url = addon.getSetting('provider_torznab_url').strip()
    if use_debrid and torznab_url and addon.getSetting('provider_torznab_enabled') == 'true':
        providers.append(TorznabProvider(torznab_url, addon.getSetting('provider_torznab_api_key').strip()))
    for slot, identifier in enumerate(STREAM_IDS, 1):
        key = 'provider_' + identifier
        base = addon.getSetting(key+'_url').strip()
        if base and addon.getSetting(key+'_enabled') != 'false':
            providers.append(StreamProvider(identifier, 'Stream provider '+str(slot), base))
    return providers

def search(addon,media,cancel=lambda:False,update=lambda percent,message:None,fetch=None,diagnostic=None):
    configured(addon)
    media=item(media)
    providers=registry(addon)
    if not providers: raise PlaybackError('No MDM Link providers are enabled for this mode. Open Provider Settings.')
    rows,statuses=run_search(providers,media,cancel,update,fetch,seconds=device_policy.integer(addon,"device_search_timeout",30,10,120),workers=device_policy.integer(addon,"device_workers",5,1,5),request_timeout=device_policy.integer(addon,"device_request_timeout",10,10,60))
    found = len(rows)
    rows=connection_policy.select(addon,device_policy.filter_rows(addon,rows))
    selected=mode(addon); ready=debrid_ready(addon)
    rows=[row for row in rows if (not row['debrid'] and selected!='Debrid') or (row['debrid'] and selected!='Free' and ready)]
    if diagnostic is not None:
        diagnostic({'found': found, 'eligible': len(rows), 'providers': statuses})
    addon.setSetting('last_search_status',json.dumps(statuses,separators=(',',':')))
    addon.setSetting('last_search_summary',json.dumps({'mode':selected,'free':sum(not row['debrid'] for row in rows),
                     'debrid':sum(row['debrid'] for row in rows),'total':len(rows)},separators=(',',':')))
    if not rows and statuses and all(s['status']!='ok' for s in statuses):
        raise PlaybackError('All enabled Link providers failed or timed out. Check your connection/provider settings.')
    return rows

def resolve(addon,source,progress,monitor,choose,policy_addon=None):
    if progress.iscanceled() or monitor.abortRequested(): raise Cancelled('Playback cancelled.')
    if not isinstance(source,dict) or source.get('provider_id')!='mdm_link': raise PlaybackError('Invalid MDM Link source. Search again.')
    policies=[addon]+([policy_addon] if policy_addon is not None else [])
    for target in policies:
        try:connection_policy.validate_settings(target)
        except ValueError as error:raise PlaybackError(str(error)) from None
    if any(not device_policy.allows(target,source) or not connection_policy.allows(target,source) for target in policies):raise PlaybackError('This source is excluded by current quality, file-size or connection preferences. Search again or change Device settings.')
    extra=source.get('extra'); extra=extra if isinstance(extra,dict) else {}
    identifier=extra.get('link_provider')
    provider=next((p for p in registry(addon) if p.id==identifier),None)
    if provider is None: raise PlaybackError('This Link provider is disabled or its mode changed. Search again.')
    if identifier in CONFIGURED_IDS and extra.get('provider_signature')!=provider.signature:
        raise PlaybackError('This provider configuration changed. Search again.')
    selected=mode(addon); access=extra.get('access')
    if identifier == 'torznab' and (access != 'debrid' or not magnet_hash(source.get('url'))):
        raise PlaybackError('Invalid Torznab source. Search again.')
    if access=='free':
        if selected=='Debrid' or source.get('debrid') or not web_url(source.get('url')): raise PlaybackError('This free source is unavailable in the current mode. Search again.')
        return source['url']
    if access=='debrid':
        if selected=='Free' or not debrid_ready(addon): raise PlaybackError('Enable and authorise AllDebrid in MDM Link or choose a free source.')
        if not source.get('debrid') or not (magnet_hash(source.get('url')) or web_url(source.get('url'))): raise PlaybackError('Invalid debrid source. Search again.')
        return AllDebrid(addon,policy_addons=policies[1:]).resolve(source,progress,monitor,choose)
    raise PlaybackError('Unsupported MDM Link source type. Search again.')

def status(addon):
    try:
        values=json.loads(addon.getSetting('last_search_status') or '[]')
        cleaned = []
        for row in values:
            if (not isinstance(row, dict) or row.get('provider') not in PROVIDER_IDS
                    or row.get('status') not in ('ok','error','timed_out') or type(row.get('sources')) is not int):
                continue
            entry = {key: row[key] for key in ('provider','status','sources')}
            reason = row.get('reason')
            if isinstance(reason, str) and reason in FAILURE_REASONS:
                entry['reason'] = reason
            code = row.get('http_status')
            if reason == 'http_error' and type(code) is int and 100 <= code <= 599:
                entry['http_status'] = code
            if row['provider'] == 'torrentio' and row.get('route') in ('proxy', 'cloudflare_ipv4'):
                entry['route'] = row['route']
            cleaned.append(entry)
        values = cleaned
    except Exception: values=[]
    try:
        summary=json.loads(addon.getSetting('last_search_summary') or '{}')
        if not isinstance(summary,dict) or summary.get('mode') not in MODES or any(type(summary.get(k)) is not int or summary[k]<0 for k in ('free','debrid','total')):
            summary={}
        else: summary={key:summary[key] for key in ('mode','free','debrid','total')}
    except Exception:summary={}
    return {'api_version':API_VERSION,'mode':mode(addon),'alldebrid_enabled':AllDebrid(addon).enabled,
            'alldebrid_configured':bool(AllDebrid(addon).key),'providers':[p.id for p in registry(addon)],'last_search':values,'last_search_summary':summary}
