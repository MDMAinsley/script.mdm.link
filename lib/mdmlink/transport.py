"""Bounded metadata reads. Errors deliberately omit URLs and upstream bodies."""
import json
import time
from urllib.request import Request, urlopen
from .errors import PlaybackError, Cancelled
from .files import web_url

MAX_BYTES=4*1024*1024

class Context:
    def __init__(self, stop, deadline, fetch=None):
        self.stop,self.deadline,self.fetch=stop,deadline,fetch

    def check(self):
        if self.stop.is_set(): raise Cancelled('Source search cancelled.')
        if time.monotonic()>=self.deadline: raise PlaybackError('Provider search timed out.')

    def json(self,url):
        self.check()
        if not web_url(url): raise PlaybackError('Provider address is invalid. Check Link settings.')
        if self.fetch:
            result=self.fetch(url)
        else:
            try:
                request=Request(url,headers={'User-Agent':'MDM-Link/0.1.0','Accept':'application/json'})
                timeout=max(0.1,min(10,self.deadline-time.monotonic()))
                with urlopen(request,timeout=timeout) as response:
                    raw=response.read(MAX_BYTES+1)
                if len(raw)>MAX_BYTES: raise ValueError('oversized')
                result=json.loads(raw.decode('utf-8'))
            except Exception:
                raise PlaybackError('Provider request failed. Check connection/settings or try later.') from None
        self.check()
        if not isinstance(result,dict): raise PlaybackError('Provider returned an invalid response.')
        return result
