import functools
import threading
import time

def ttl_cache(ttl: float, maxsize: int = 32):

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
