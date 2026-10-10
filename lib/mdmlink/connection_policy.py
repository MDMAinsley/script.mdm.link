"""Device-local preferences using reported metadata, not a throughput probe."""
import math
import re
GIB=1024**3
QUALITY={'4K':2160,'2160p':2160,'1080p':1080,'720p':720,'480p':480,'SD':480,'CAM':10,'Unknown':0}

def number(value,maximum=100000):
    if type(value) not in (int,float):return None
    return float(value) if math.isfinite(value) and 0<value<=maximum else None

def setting(addon,key,default):
    try:return addon.getSetting(key) or default
    except Exception:return default

def decimal(addon,key,maximum):
    value=setting(addon,key,'0')
    if not isinstance(value,str) or not re.fullmatch(r'\d{1,5}(?:\.\d{1,3})?',value):return 0
    result=float(value);return result if 0<=result<=maximum else 0

def validate_settings(addon):
    for key in ('device_connection_mbps','device_max_size_gib'):
        value=setting(addon,key,'0')
        if not isinstance(value,str) or not re.fullmatch(r'\d{1,5}(?:\.\d{1,3})?',value) or not 0<=float(value)<=10000:
            raise ValueError('Invalid connection/file-size preferences. Use numbers from 0 to 10000, with up to three decimal places. Open addon settings to correct them.')
    for key,options,default in (('device_source_order',('Quality','Connection','Smallest'),'Quality'),('device_unknown_size',('Show','Hide'),'Show'),('device_slow_sources',('Show','Hide'),'Show'),('device_unknown_bitrate',('Show','Hide'),'Show')):
        if setting(addon,key,default) not in options:raise ValueError('Invalid source preference. Choose a listed order or Show/Hide option in addon settings.')

def size_gib(row):
    if not isinstance(row,dict):return None
    if 'size_bytes' in row:
        size=number(row['size_bytes'],100000*GIB)
        return size/GIB if size else None
    # Internal source size is GiB. Unknown strings are not guessed from filenames.
    return number(row.get('size'))

def bytes_gib(value):
    value=number(value,100000*GIB)
    return value/GIB if value else None

def coco_size(value):
    # Coco's numeric GB convention is binary GiB (verified in its convert_size).
    known=number(value)
    if known:return known
    if not isinstance(value,str):return None
    match=re.fullmatch(r'\s*(\d+(?:\.\d+)?)\s*(GiB|GB|MiB|MB|KiB|KB|B)\s*',value,re.I)
    if not match:return None
    value=float(match[1]);units={'gib':1,'gb':1,'mib':1/1024,'mb':1/1024,'kib':1/1024**2,'kb':1/1024**2,'b':1/GIB}
    return number(value*units[match[2].lower()])

def bitrate(row):
    size=size_gib(row);extra=row.get('extra');extra=extra if isinstance(extra,dict) else {}
    media=extra.get('item');media=media if isinstance(media,dict) else {}
    duration=number(media.get('duration_seconds'),86400)
    # Never divide a whole-season size by one episode's duration.
    if media.get('media_type')=='episode' and extra.get('size_scope')!='file':return None
    if not size or not duration:return None
    rate=size*GIB*8/duration/1e6
    return rate if math.isfinite(rate) else None

def assessment(addon,row):
    rate=bitrate(row);connection=decimal(addon,'device_connection_mbps',10000)
    if not connection:return 'Off',rate
    if rate is None:return 'Unknown',None
    return ('Fits estimate' if rate<=connection*.75 else 'Above budget'),rate

def allows(addon,row):
    maximum=decimal(addon,'device_max_size_gib',10000);size=size_gib(row)
    if maximum:
        if size is None and setting(addon,'device_unknown_size','Show')=='Hide':return False
        if size is not None and size>maximum:return False
    state,_=assessment(addon,row)
    if state=='Unknown' and setting(addon,'device_unknown_bitrate','Show')=='Hide':return False
    if state=='Above budget' and setting(addon,'device_slow_sources','Show')=='Hide':return False
    return True

def quality_score(row):
    value=row.get('quality');value=value if isinstance(value,str) else 'Unknown'
    match=re.fullmatch(r'(\d{3,4})p',value)
    return int(match[1]) if match else QUALITY.get(value,0)

def badge(addon,row):
    state,rate=assessment(addon,row)
    return '' if state=='Off' else ' · '+state+(' ~{:.1f} Mbps'.format(rate) if rate is not None else '')

def order(addon,rows):
    mode=setting(addon,'device_source_order','Quality')
    def key(row):
        paid=bool(row.get('debrid'));quality=quality_score(row);size=size_gib(row)
        if mode=='Smallest':return paid,size is not None,-size if size is not None else 0,quality
        if mode=='Connection' and decimal(addon,'device_connection_mbps',10000):
            state,rate=assessment(addon,row)
            return paid,{'Fits estimate':2,'Unknown':1,'Above budget':0}.get(state,1),quality,-rate if rate is not None else 0
        return paid,quality
    return sorted(rows,key=key,reverse=True)

def select(addon,rows):return order(addon,[row for row in rows if allows(addon,row)])

def note(addon,row):
    state,rate=assessment(addon,row);size=size_gib(row)
    fields=['{:.2f} GiB (reported)'.format(size) if size is not None else 'Size unknown']
    extra=row.get('extra');extra=extra if isinstance(extra,dict) else {}
    if extra.get('size_scope')=='package':fields.append('torrent/package size; selected file may be smaller')
    if state!='Off':fields.append(('~{:.1f} Mbps average · '.format(rate) if rate is not None else '')+state+' (25% connection reserve)')
    fields.append('Estimate only; bitrate peaks, host speed and buffering can differ.')
    return ' · '.join(fields)
