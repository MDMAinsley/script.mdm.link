"""Independent adapters: Archive direct files and Stremio stream responses."""
import hashlib
import os
import re
import unicodedata
from urllib.parse import quote, urlencode, urlsplit, urlunsplit
from .errors import PlaybackError
from .files import VIDEO_EXTENSIONS, match_files, web_url
from .models import info_hash, text

def normal(value):
    return re.sub(r'[^a-z0-9]+','',unicodedata.normalize('NFKD',text(value)).encode('ascii','ignore').decode().lower())

def provider_base(value):
    if not isinstance(value,str) or not web_url(value): raise PlaybackError('Stream provider address is invalid. Check Link settings.')
    parsed=urlsplit(value)
    if parsed.query or parsed.fragment: raise PlaybackError('Use the provider base or manifest URL without query parameters.')
    path=parsed.path.rstrip('/')
    if path.endswith('/manifest.json'): path=path[:-len('/manifest.json')]
    return urlunsplit((parsed.scheme,parsed.netloc,path,'',''))

class StreamProvider:
    def __init__(self,identifier,name,base,torrents_only=False):
        self.id,self.name,self.base,self.torrents_only=identifier,name,base,torrents_only

    @property
    def signature(self): return hashlib.sha256(self.base.encode()).hexdigest()

    def search(self,media,context):
        imdb=media.get('imdb_id')
        if not imdb: return []
        identifier=imdb
        kind='movie'
        if media['media_type']=='episode':
            kind='series'; identifier+=':{}:{}'.format(media['season'],media['episode'])
        url=provider_base(self.base)+'/stream/'+kind+'/'+quote(identifier,safe=':')+'.json'
        data=context.json(url)
        streams=data.get('streams')
        if not isinstance(streams,list): raise PlaybackError('Stream provider returned no valid stream list.')
        found=[]
        for row in streams[:250]:
            context.check()
            if not isinstance(row,dict): continue
            hints=row.get('behaviorHints'); hints=hints if isinstance(hints,dict) else {}
            label=text(row.get('description') or row.get('title') or row.get('name'))
            name=text(row.get('name'))
            digest=info_hash(row.get('infoHash'))
            if digest:
                found.append({'url':'magnet:?xt=urn:btih:'+digest,'access':'debrid','label':label or name,
                              'quality':name+' '+label,'size':hints.get('videoSize',0)/1024**3 if type(hints.get('videoSize')) in (int,float) else ''})
            elif not self.torrents_only and web_url(row.get('url')):
                # Browser-only URLs, archive formats and header/proxy requirements need their own resolver.
                if hints.get('proxyHeaders') or any(row.get(key) for key in ('externalUrl','nzbUrl','rarUrls','zipUrls')): continue
                found.append({'url':row['url'],'access':'free','label':label or name,'quality':name+' '+label,
                              'size':hints.get('videoSize',0)/1024**3 if type(hints.get('videoSize')) in (int,float) else ''})
        return found

class ArchiveProvider:
    id='archive'
    name='Internet Archive'
    signature='archive-v1'

    def search(self,media,context):
        episode=media['media_type']=='episode'
        title=media['tvshowtitle'] if episode else media['title']
        # Escape query syntax rather than allowing metadata to introduce search operators.
        variants=[title]+media.get('extra',{}).get('aliases',[])
        if title.lower().startswith('the '): variants.append(title[4:])
        escaped=[value.replace('\\','\\\\').replace('"','\\"') for value in variants if value]
        query='mediatype:movies AND ('+' OR '.join('title:"'+value+'"' for value in escaped)+')'
        if not episode and media.get('year'): query+=' AND year:'+str(media['year'])
        params=[('q',query),('fl[]','identifier'),('fl[]','title'),('fl[]','year'),('rows','8'),('output','json')]
        data=context.json('https://archive.org/advancedsearch.php?'+urlencode(params))
        response=data.get('response')
        docs=response.get('docs') if isinstance(response,dict) else None
        if not isinstance(docs,list): raise PlaybackError('Internet Archive returned an invalid search response.')
        found=[]; read=0
        titles={normal(value) for value in variants}
        for row in docs[:8]:
            context.check()
            if read>=3: break
            if not isinstance(row,dict) or not isinstance(row.get('identifier'),str): continue
            candidate=normal(row.get('title'))
            if (not episode and candidate not in titles) or (episode and not any(candidate.startswith(x) for x in titles if x)): continue
            if not episode and media.get('year') and str(row.get('year'))!=str(media['year']): continue
            identifier=row['identifier']
            if not re.fullmatch(r'[A-Za-z0-9_.-]+',identifier): continue
            read+=1
            try:
                meta=context.json('https://archive.org/metadata/'+quote(identifier,safe=''))
            except PlaybackError:
                # A bad/restricted item must not discard earlier valid file results.
                if found: break
                if read>=3: raise
                continue
            metadata=meta.get('metadata')
            if meta.get('is_dark') or not isinstance(metadata,dict) or metadata.get('nodownload') in (True,'true','1','1.0'): continue
            if not episode and normal(metadata.get('title')) not in titles: continue
            files=meta.get('files'); candidates=[]
            for file in files[:1000] if isinstance(files,list) else []:
                if not isinstance(file,dict) or not isinstance(file.get('name'),str) or file.get('private') in (True,'true','1'): continue
                filename=file['name']
                if os.path.splitext(filename.lower())[1] not in VIDEO_EXTENSIONS: continue
                if filename.startswith('/') or '..' in filename.split('/'): continue
                size=file.get('size')
                size=int(size) if isinstance(size,(str,int)) and str(size).isdigit() else 0
                candidates.append({'name':filename,'size':size,'url':'https://archive.org/download/'+quote(identifier,safe='')+'/'+quote(filename,safe='/')})
            matched=match_files(candidates,media)
            if episode:
                # Exact episode titles can identify old archive releases lacking SxxExx.
                # Never override an explicit different episode number in the filename.
                episode_title=normal(media['title'])
                expected={episode_title}|{show+episode_title for show in titles}
                all_videos=match_files(candidates,{'media_type':'movie'})
                for file in all_videos:
                    stem=os.path.splitext(os.path.basename(file['name']))[0]
                    if re.search(r'(?i)(s\d+[ ._-]*e\d+|\d+x\d+)',stem): continue
                    if normal(stem) in expected and file not in matched: matched.append(file)
            for file in matched:
                found.append({'url':file['url'],'label':file['name'],'quality':file['name'],'access':'free','size':file['size']/1024**3})
            if read>=3: break
        return found
