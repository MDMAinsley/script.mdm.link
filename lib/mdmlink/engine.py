"""Bounded daemon workers; partial results survive individual adapter failures."""
import queue
import threading
import time
from .errors import Cancelled
from .models import merge, source
from .transport import Context

def search(providers,media,cancel=lambda:False,update=lambda percent,message:None,fetch=None,seconds=30,workers=5,request_timeout=10):
    if cancel(): raise Cancelled('Source search cancelled.')
    if not providers: return [],[]
    seconds=seconds if type(seconds) in (int,float) and 0<seconds<=120 else 30
    workers=workers if type(workers) is int and 1<=workers<=5 else 5
    stop=threading.Event(); results=queue.Queue(); jobs=queue.Queue(); deadline=time.monotonic()+seconds
    def worker(provider):
        try:
            rows=provider.search(media,Context(stop,deadline,fetch,request_timeout))
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
    for provider in providers:jobs.put(provider)
    def consume():
        while not stop.is_set() and time.monotonic()<deadline:
            try:provider=jobs.get_nowait()
            except queue.Empty:return
            worker(provider)
    for _ in range(min(workers,len(providers))):threading.Thread(target=consume,daemon=True).start()
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
