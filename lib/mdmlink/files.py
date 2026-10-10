"""Match actual videos in a torrent; never choose an arbitrary episode."""
import os
import re
from urllib.parse import urlsplit

VIDEO_EXTENSIONS = {'.mkv', '.mp4', '.avi', '.mov', '.m4v', '.ts', '.webm', '.wmv', '.mpg', '.mpeg'}


def web_url(value):
    if not isinstance(value, str) or any(ord(c)<33 or ord(c)==127 or c=='|' for c in value):
        return False
    try:
        parsed = urlsplit(value)
        parsed.port  # Validate malformed/out-of-range ports as well.
        return parsed.scheme in ('http', 'https') and bool(parsed.hostname) and not parsed.username and not parsed.password
    except ValueError:
        return False


def flatten(rows, prefix='', depth=0):
    if not isinstance(rows, list) or depth > 20:
        return []
    result = []
    for raw in rows:
        if not isinstance(raw, dict) or not isinstance(raw.get('n'), str):
            continue
        path = prefix + raw['n']
        if isinstance(raw.get('e'), list):
            result.extend(flatten(raw['e'], path + '/', depth + 1))
        elif web_url(raw.get('l')):
            result.append({'name':path, 'url':raw['l'], 'size':raw.get('s', 0)})
    return result


def match_files(rows, item):
    result = []
    episode = item.get('media_type') == 'episode'
    if episode:
        season, episode_number = int(item['season']), int(item['episode'])
        pattern = re.compile(r'(?i)(?<![a-z0-9])(?:s0*{}[ ._-]*e0*{}(?![0-9])|0*{}x[ ._-]*0*{}(?![0-9]))'.format(season,episode_number,season,episode_number))
    for file in rows:
        name = file.get('name', '')
        lower = name.lower()
        if os.path.splitext(lower)[1] not in VIDEO_EXTENSIONS or re.search(r'(?i)(?:^|[ ._/\\-])(sample|trailer)(?:[ ._/\\-]|$)', name):
            continue
        if episode and not pattern.search(name):
            continue
        result.append(file)
    return sorted(result, key=lambda f:f['size'] if type(f.get('size')) is int else 0, reverse=True)
