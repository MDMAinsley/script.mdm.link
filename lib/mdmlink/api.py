"""Versioned API consumed by Flix and future frontends."""
from . import device_policy
import json
from . import API_VERSION
from .alldebrid import AllDebrid
from .errors import PlaybackError, Cancelled
from .files import web_url
from .models import item, magnet_hash
from .providers import ArchiveProvider, StreamProvider
from .engine import search as run_search

MODES=('Free','Debrid','Combined')

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
    if mode(addon)=='Debrid' and not debrid_ready(addon):
        raise PlaybackError('Enable and authorise AllDebrid in MDM Link, or choose Free/Combined mode.')

def registry(addon):
    providers=[]; selected=mode(addon)
    if selected!='Debrid' and addon.getSetting('provider_archive')!='false': providers.append(ArchiveProvider())
    if selected!='Free' and debrid_ready(addon) and addon.getSetting('provider_torrentio')!='false':
        providers.append(StreamProvider('torrentio','Torrentio','https://torrentio.strem.fun',True))
    for slot in range(1,4):
        key='provider_stream_'+str(slot)
        base=addon.getSetting(key+'_url').strip()
        if base and addon.getSetting(key+'_enabled')!='false':
            providers.append(StreamProvider('stream_'+str(slot),'Stream provider '+str(slot),base))
    return providers

def search(addon,media,cancel=lambda:False,update=lambda percent,message:None,fetch=None):
    configured(addon)
    media=item(media)
    providers=registry(addon)
    if not providers: raise PlaybackError('No MDM Link providers are enabled for this mode. Open Provider Settings.')
    rows,statuses=run_search(providers,media,cancel,update,fetch,seconds=device_policy.integer(addon,"device_search_timeout",30,10,120),workers=device_policy.integer(addon,"device_workers",5,1,5),request_timeout=device_policy.integer(addon,"device_request_timeout",10,10,60))
    rows=device_policy.filter_rows(addon,rows)
    selected=mode(addon); ready=debrid_ready(addon)
    rows=[row for row in rows if (not row['debrid'] and selected!='Debrid') or (row['debrid'] and selected!='Free' and ready)]
    addon.setSetting('last_search_status',json.dumps(statuses,separators=(',',':')))
    addon.setSetting('last_search_summary',json.dumps({'mode':selected,'free':sum(not row['debrid'] for row in rows),
                     'debrid':sum(row['debrid'] for row in rows),'total':len(rows)},separators=(',',':')))
    if not rows and statuses and all(s['status']!='ok' for s in statuses):
        raise PlaybackError('All enabled Link providers failed or timed out. Check your connection/provider settings.')
    return rows

def resolve(addon,source,progress,monitor,choose):
    if progress.iscanceled() or monitor.abortRequested(): raise Cancelled('Playback cancelled.')
    if not isinstance(source,dict) or source.get('provider_id')!='mdm_link': raise PlaybackError('Invalid MDM Link source. Search again.')
    if not device_policy.allows(addon,source):raise PlaybackError('This source exceeds your current quality limit or has hidden unknown quality. Search again or change Device settings.')
    extra=source.get('extra'); extra=extra if isinstance(extra,dict) else {}
    identifier=extra.get('link_provider')
    provider=next((p for p in registry(addon) if p.id==identifier),None)
    if provider is None: raise PlaybackError('This Link provider is disabled or its mode changed. Search again.')
    if identifier.startswith('stream_') and extra.get('provider_signature')!=provider.signature:
        raise PlaybackError('This stream provider configuration changed. Search again.')
    selected=mode(addon); access=extra.get('access')
    if access=='free':
        if selected=='Debrid' or source.get('debrid') or not web_url(source.get('url')): raise PlaybackError('This free source is unavailable in the current mode. Search again.')
        return source['url']
    if access=='debrid':
        if selected=='Free' or not debrid_ready(addon): raise PlaybackError('Enable and authorise AllDebrid in MDM Link or choose a free source.')
        if not source.get('debrid') or not (magnet_hash(source.get('url')) or web_url(source.get('url'))): raise PlaybackError('Invalid debrid source. Search again.')
        return AllDebrid(addon).resolve(source,progress,monitor,choose)
    raise PlaybackError('Unsupported MDM Link source type. Search again.')

def status(addon):
    try:
        values=json.loads(addon.getSetting('last_search_status') or '[]')
        values=[{'provider':s['provider'],'status':s['status'],'sources':s['sources']} for s in values
                if isinstance(s,dict) and s.get('provider') in ('archive','torrentio','stream_1','stream_2','stream_3')
                and s.get('status') in ('ok','error','timed_out') and type(s.get('sources')) is int]
    except Exception: values=[]
    try:
        summary=json.loads(addon.getSetting('last_search_summary') or '{}')
        if not isinstance(summary,dict) or summary.get('mode') not in MODES or any(type(summary.get(k)) is not int or summary[k]<0 for k in ('free','debrid','total')):
            summary={}
        else: summary={key:summary[key] for key in ('mode','free','debrid','total')}
    except Exception:summary={}
    return {'api_version':API_VERSION,'mode':mode(addon),'alldebrid_enabled':AllDebrid(addon).enabled,
            'alldebrid_configured':bool(AllDebrid(addon).key),'providers':[p.id for p in registry(addon)],'last_search':values,'last_search_summary':summary}
