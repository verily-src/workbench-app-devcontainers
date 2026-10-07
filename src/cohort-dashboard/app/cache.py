"""Tiny thread-safe TTL cache shared by the data engines.

Lives in imported modules (not main.py) on purpose: panel serve re-runs
main.py per browser session, but imported modules load once per process,
so these caches are shared across sessions and survive page reloads.
"""

import functools
import threading
import time


def ttl_cache(ttl: float, maxsize: int = 32):
    """Memoize by positional/keyword args with a time-to-live.

    Cached values are returned by reference — callers must not mutate
    them (relevant for DataFrames). The wrapper gains `.invalidate()`
    which clears every entry, for use after writes (seeding, DDL).
    """
    def decorator(fn):
        store: dict = {}
        lock = threading.Lock()

        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            key = (args, tuple(sorted(kwargs.items())))
            now = time.monotonic()
            with lock:
                hit = store.get(key)
                if hit is not None and hit[1] > now:
                    return hit[0]
            value = fn(*args, **kwargs)
            with lock:
                store[key] = (value, now + ttl)
                while len(store) > maxsize:
                    oldest = min(store, key=lambda k: store[k][1])
                    del store[oldest]
            return value

        def invalidate():
            with lock:
                store.clear()

        wrapper.invalidate = invalidate
        return wrapper
    return decorator
