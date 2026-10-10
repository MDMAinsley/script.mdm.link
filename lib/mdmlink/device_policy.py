"""Device-local limits; reported quality only, never decoder capability proof."""
import re

CAPS={'Unlimited':None,'720p':720,'1080p':1080,'4K':2160}
def setting(addon,key,default):
    try:return addon.getSetting(key) or default
    except Exception:return default
def integer(addon,key,default,minimum,maximum):
    value=setting(addon,key,str(default))
    if not isinstance(value,str) or not re.fullmatch('[0-9]{1,3}',value):return default
    value=int(value);return value if minimum<=value<=maximum else default
def limit(addon):
    value=setting(addon,'device_quality_max','Unlimited');return value if value in CAPS else 'Unlimited'
def height(row):
    if not isinstance(row,dict):return None
    parts=[row.get(key,'') for key in ('quality','label','name')]
    text=' '.join(value for value in parts if isinstance(value,str)).lower();found=[]
    for match in re.finditer(r'(?<![0-9])([0-9]{3,4})[pi](?![a-z0-9])',text):found.append(int(match[1]))
    for match in re.finditer(r'(?<![0-9])[0-9]{3,5}\s*[x×]\s*([0-9]{3,5})(?![0-9])',text):found.append(int(match[1]))
    for token,number in ((r'\b8k\b',4320),(r'\b(?:4k|uhd)\b',2160),(r'\bfhd\b',1080),(r'\b(?:sd|cam)\b',480)):
        if re.search(token,text):found.append(number)
    return max(found) if found else None
def allows(addon,row):
    maximum=CAPS[limit(addon)];reported=height(row)
    if reported is None:return setting(addon,'device_unknown_quality','Show')!='Hide'
    return maximum is None or reported<=maximum
def filter_rows(addon,rows):return [row for row in rows if allows(addon,row)]
def artwork_mode(addon):return setting(addon,'device_artwork','Standard')=='Light'
