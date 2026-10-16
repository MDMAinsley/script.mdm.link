"""Thread-local bounds shared by Flix and the selected debrid resolver."""
from contextlib import contextmanager
from contextvars import ContextVar
import time
from .errors import AutoplayBudgetExpired

_deadline = ContextVar("mdm_autoplay_deadline", default=None)


def active():
    return _deadline.get() is not None


def remaining():
    deadline = _deadline.get()
    return None if deadline is None else max(0, deadline - time.monotonic())


def check():
    if remaining() == 0:
        raise AutoplayBudgetExpired("Autoplay reached its 75-second resolution budget after source search. Use Source Select or try again later.")


def exclude_choice_time(seconds):
    deadline = _deadline.get()
    if deadline is not None and seconds > 0:
        _deadline.set(deadline + seconds)


@contextmanager
def bounded(seconds=75):
    previous = _deadline.get()
    deadline = time.monotonic() + seconds
    token = _deadline.set(min(previous, deadline) if previous is not None else deadline)
    try:
        yield
    finally:
        _deadline.reset(token)
