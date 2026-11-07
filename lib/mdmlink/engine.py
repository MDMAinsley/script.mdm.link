"""Coordinate independently bounded provider jobs and retain completed results."""
from collections import deque
from dataclasses import dataclass
import math
import queue
import threading
import time

from .errors import Cancelled
from .models import merge, source
from .transport import Context, ProviderRequestError

CUSTOM_PROVIDER_SLOTS = 6
MAX_PROVIDERS = 2 + CUSTOM_PROVIDER_SLOTS


@dataclass
class Running:
    stop: threading.Event
    deadline: float


def search(providers, media, cancel=lambda: False, update=lambda percent, message: None,
           fetch=None, seconds=30, workers=5, request_timeout=10):
    if cancel():
        raise Cancelled('Source search cancelled.')
    if not providers:
        return [], []
    seconds = seconds if type(seconds) in (int, float) and 0 < seconds <= 120 else 30
    workers = workers if type(workers) is int and 1 <= workers <= 5 else 5
    pending = deque({p.id: p for p in providers[:MAX_PROVIDERS]}.values())
    total = len(pending)
    deadline = time.monotonic() + seconds
    running = {}
    finished = queue.Queue()
    groups = []
    statuses = []

    def record(identifier, rows, status, detail):
        groups.append(rows)
        statuses.append(dict(provider=identifier, status=status, sources=len(rows), **detail))
        update(int(100 * len(statuses) / total),
               '{} providers finished · {} sources'.format(len(statuses), sum(map(len, groups))))

    def run(provider, job):
        context = Context(job.stop, job.deadline, fetch, request_timeout)
        detail = {}
        clean = []
        status = 'ok'
        try:
            rows = provider.search(media, context)
            if not isinstance(rows, list):
                raise ValueError('Invalid provider rows')
            for row in rows[:250]:
                parsed = source(row, provider.id, provider.name, media)
                if parsed:
                    parsed['extra']['provider_signature'] = getattr(provider, 'signature', '')
                    clean.append(parsed)
        except ProviderRequestError as error:
            clean = []
            status = 'timed_out' if error.reason == 'search_budget' else 'error'
            detail['reason'] = error.reason
            if error.http_status is not None:
                detail['http_status'] = error.http_status
        except Exception:
            clean = []
            status = 'error'
        if context.used_proxy:
            detail['route'] = 'proxy'
        elif context.used_ipv4:
            detail['route'] = 'cloudflare_ipv4'
        if not job.stop.is_set():
            finished.put((provider.id, clean, status, detail, time.monotonic()))

    def receive(event):
        identifier, rows, status, detail, completed_at = event
        job = running.pop(identifier, None)
        if job is None:
            return
        job.stop.set()
        if completed_at > job.deadline:
            record(identifier, [], 'timed_out', {'reason': 'search_budget'})
        else:
            record(identifier, rows, status, detail)

    try:
        while pending or running:
            if cancel():
                raise Cancelled('Source search cancelled.')
            while True:
                try:
                    event = finished.get_nowait()
                except queue.Empty:
                    break
                receive(event)

            now = time.monotonic()
            for identifier, job in list(running.items()):
                if now >= job.deadline:
                    job.stop.set()
                    del running[identifier]
                    record(identifier, [], 'timed_out', {'reason': 'search_budget'})

            if now >= deadline:
                break

            # Reserve time for queued providers. An uncooperative adapter can
            # outlive its slot, but can never block the next queued provider.
            # Each provider starts at most once, so even stale threads are capped.
            waves = max(1, math.ceil((len(pending) + len(running)) / workers))
            slot_deadline = now + (deadline - now) / waves
            while pending and len(running) < workers:
                provider = pending.popleft()
                job = Running(threading.Event(), slot_deadline)
                running[provider.id] = job
                threading.Thread(target=run, args=(provider, job), daemon=True).start()

            if running:
                until = min(job.deadline for job in running.values())
                try:
                    event = finished.get(timeout=max(0, min(0.1, until - time.monotonic())))
                except queue.Empty:
                    continue
                receive(event)
        if cancel():
            raise Cancelled('Source search cancelled.')
        for provider in pending:
            record(provider.id, [], 'timed_out', {'reason': 'search_budget'})
        return merge(groups), statuses
    finally:
        for job in running.values():
            job.stop.set()
