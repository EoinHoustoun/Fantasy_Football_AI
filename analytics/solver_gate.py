"""Let the solve a human is waiting on go first.

The draft page starts eight ceiling MILPs in a daemon thread at load, each with
a 25-second limit. CBC is CPU-bound, so on an eight-core box that is enough to
saturate it, and the foreground solve someone is actually waiting for went from
about 4 seconds to 41.

This is a priority gate rather than a lock. A plain lock would be worse than
nothing: the foreground would queue behind a background solve already holding
it, which is precisely the wait being removed.

    with solver_gate.foreground():   # never waits for background work
        ...

    with solver_gate.background():   # steps aside while foreground is active
        ...

Background work is not cancelled, only deferred. A ceiling that arrives a few
seconds later costs nothing, because the pitch already renders without it and
swaps the number in when it lands.
"""
import logging
import threading
from contextlib import contextmanager

logger = logging.getLogger(__name__)

# How long a background solve waits for a clear run before going anyway. Without
# a ceiling here a busy page could starve the warm-up forever, and the ceilings
# would never appear at all.
MAX_DEFER_SECONDS = 30.0

_STATE = threading.local()
_LOCK = threading.Lock()
_CLEAR = threading.Event()
_CLEAR.set()
_ACTIVE = [0]          # foreground solves in flight, across all threads


def reset() -> None:
    """Clear the gate. For tests, and for a process that lost a thread."""
    with _LOCK:
        _ACTIVE[0] = 0
        _CLEAR.set()


@contextmanager
def foreground():
    """Mark a solve as user-facing. Never blocks."""
    with _LOCK:
        _ACTIVE[0] += 1
        _CLEAR.clear()
    try:
        yield
    finally:
        with _LOCK:
            _ACTIVE[0] = max(0, _ACTIVE[0] - 1)
            if _ACTIVE[0] == 0:
                _CLEAR.set()


@contextmanager
def background(max_defer: float = MAX_DEFER_SECONDS):
    """Wait for the foreground to be idle, then run. Gives up waiting after
    `max_defer` so a busy page cannot starve the warm-up completely."""
    if not _CLEAR.wait(timeout=max_defer):
        logger.debug("background solve proceeding after %.0fs deferred", max_defer)
    yield
