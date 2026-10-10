"""Bounded daemon workers; partial results survive individual adapter failures."""
import queue
import threading
import time
from .errors import Cancelled
from .models import merge, source
from .transport import Context

def search(providers,media,cancel=lambda:False,update=lambda percent,message:None,fetch=None,seconds=30):
    if cancel(): raise Cancelled('Source search cancelled.')
    if not providers: return [],[]
    stop=threading.Event(); results=queue.Queue(); deadline=time.monotonic()+seconds
    def worker(provider):
        try:
            rows=provider.search(media,Context(stop,deadline,fetch))
            if not isinstance(rows,list): raise ValueError('Invalid provider rows')
            clean=[]
            for row in rows[:250]:
                parsed=source(row,provider.id,provider.name,media)
                if parsed:
                    parsed['extra']['provider_signature']=getattr(provider,'signature','')
                    clean.append(parsed)
            status='ok'
        except Exception:
            clean=[]; status='error'
        if not stop.is_set(): results.put((provider.id,clean,status))
    # The registry caps at five jobs. No unbounded executors or wait-on-shutdown.
    providers=providers[:5]
    for provider in providers: threading.Thread(target=worker,args=(provider,),daemon=True).start()
    groups=[]; statuses=[]; remaining={p.id for p in providers}
    try:
        while remaining and time.monotonic()<deadline:
            if cancel(): raise Cancelled('Source search cancelled.')
            try: identifier,rows,status=results.get(timeout=min(0.1,max(0.001,deadline-time.monotonic())))
            except queue.Empty: continue
            if identifier not in remaining: continue
            remaining.remove(identifier); groups.append(rows)
            statuses.append({'provider':identifier,'status':status,'sources':len(rows)})
            update(int(100*len(statuses)/len(providers)), '{} providers finished · {} sources'.format(len(statuses),sum(len(x) for x in groups)))
        if cancel(): raise Cancelled('Source search cancelled.')
        statuses.extend({'provider':identifier,'status':'timed_out','sources':0} for identifier in sorted(remaining))
        return merge(groups),statuses
    finally: stop.set()
