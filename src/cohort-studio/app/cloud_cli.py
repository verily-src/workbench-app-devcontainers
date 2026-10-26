import subprocess
import threading

_lock = threading.Lock()


def run(args, **kwargs):
    timeout = kwargs.get('timeout', 120)
    if not _lock.acquire(timeout=timeout):
        raise subprocess.TimeoutExpired(args, timeout)
    try:
        return subprocess.run(args, **kwargs)
    finally:
        _lock.release()
