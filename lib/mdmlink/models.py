import base64
import hashlib
import math
import re
from urllib.parse import parse_qs, urlsplit
from .errors import PlaybackError
from .files import web_url

QUALITY = {'4K':500, '2160p':500, '1080p':400, '720p':300, '480p':200, 'SD':100, 'CAM':10, 'Unknown':0}

def text(value, limit=300):
    if not isinstance(value, str): return ''
    return re.sub(r'\[(?:/?COLOR[^\]]*|/?B|/?I)\]', '', ''.join(c for c in value if ord(c)>=32), flags=re.I)[:limit]

def quality(value):
    value = text(value).lower()
    for token, label in (('2160','2160p'),('4k','4K'),('1080','1080p'),('720','720p'),('480','480p'),('cam','CAM')):
        if token in value: return label
    return 'Unknown'

def info_hash(value):
    if not isinstance(value,str): return None
    if re.fullmatch('[0-9a-fA-F]{40}',value): return value.lower()
    if re.fullmatch('[A-Za-z2-7]{32}',value):
        return base64.b32decode(value.upper()).hex()
    return None

def magnet_hash(value):
    if not isinstance(value,str) or any(ord(c)<32 for c in value): return None
    try:
        url=urlsplit(value)
        if url.scheme!='magnet': return None
        xt=parse_qs(url.query).get('xt',[])
        return next((info_hash(x[9:]) for x in xt if x.lower().startswith('urn:btih:') and info_hash(x[9:])),None)
    except ValueError: return None

def item(value):
    if not isinstance(value,dict): raise PlaybackError('Invalid title information. Open the title again.')
    kind=value.get('media_type')
    if kind not in ('movie','episode'): raise PlaybackError('Choose a movie or an individual TV episode.')
    title=text(value.get('title'))
    if not title: raise PlaybackError('Title information is missing.')
    result={'media_type':kind,'title':title}
    imdb=value.get('imdb_id')
    if isinstance(imdb,str) and re.fullmatch(r'tt[0-9]+',imdb): result['imdb_id']=imdb
    for key in ('year','tmdb_id'):
        number=value.get(key)
        if type(number) is int and number>0: result[key]=number
    if kind=='episode':
        for key,minimum in (('season',0),('episode',1)):
            number=value.get(key)
            if type(number) is not int or number<minimum: raise PlaybackError('Episode coordinates are invalid.')
            result[key]=number
        result['tvshowtitle']=text(value.get('tvshowtitle'))
        if not result['tvshowtitle']: raise PlaybackError('TV show information is missing.')
    extra=value.get('extra')
    aliases=extra.get('aliases',[]) if isinstance(extra,dict) else []
    result['extra']={'aliases':[text(x) for x in aliases[:20] if text(x)] if isinstance(aliases,list) else []}
    duration=value.get("duration_seconds")
    if type(duration) in (int,float) and math.isfinite(duration) and 0<duration<=86400:result["duration_seconds"]=duration
    return result

def source(raw, provider_id, provider_name, media):
    if not isinstance(raw,dict): return None
    url=raw.get('url')
    access=raw.get('access')
    digest=magnet_hash(url)
    if access not in ('free','debrid') or not (web_url(url) or digest and access=='debrid'): return None
    if digest: url='magnet:?xt=urn:btih:'+digest
    size=raw.get('size')
    size=size if type(size) in (int,float) and math.isfinite(size) and size>0 else ''
    identity=('torrent:'+digest if digest else 'url:'+url)+'|'+access
    return {'source_id':hashlib.sha256(identity.encode()).hexdigest(), 'label':text(raw.get('label')) or provider_name,
            'url':url, 'provider_id':'mdm_link', 'provider_name':'MDM Link / '+provider_name,
            'quality':quality(raw.get('quality') or raw.get('label')), 'host':urlsplit(url).hostname or 'Torrent',
            'size':size, 'debrid':access=='debrid',
            'extra':{'item':media, 'link_provider':provider_id, 'access':access,
                     'size_scope':raw.get('size_scope') if raw.get('size_scope') in ('file','package') else 'unknown',
                     'hash':digest or '', 'availability':'unchecked' if access=='debrid' else 'direct'}}

def merge(groups):
    found={}
    for rows in groups:
        for row in rows:
            identity=row['source_id']
            previous=found.get(identity)
            if previous is None or QUALITY.get(row['quality'],0)>QUALITY.get(previous['quality'],0): found[identity]=row
    return sorted(found.values(),key=lambda row:(row['debrid'],QUALITY.get(row['quality'],0)),reverse=True)
