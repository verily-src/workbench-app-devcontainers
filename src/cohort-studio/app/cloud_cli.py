import itertools
import subprocess
import threading
import time

_condition = threading.Condition()
_waiting = []
_sequence = itertools.count()
_active = False


def _priority(args):
    if args[:3] == ['wb', 'resource', 'resolve'] and '--include-password' in args:
        return 0
    if args[:3] == ['aws', 's3api', 'list-objects-v2'] and '_studio_views/' in ' '.join(args):
        return 1
    return 2


def run(args, **kwargs):
    global _active
    timeout = kwargs.get('timeout', 120)
    deadline = time.monotonic() + timeout if timeout is not None else None
    token = (_priority(args), next(_sequence))
    with _condition:
        _waiting.append(token)
        try:
            while _active or token != min(_waiting):
                remaining = None if deadline is None else deadline - time.monotonic()
                if remaining is not None and remaining <= 0:
                    raise subprocess.TimeoutExpired(args, timeout)
                _condition.wait(remaining)
            _active = True
        finally:
            _waiting.remove(token)
            _condition.notify_all()
    try:
        return subprocess.run(args, **kwargs)
    finally:
        with _condition:
            _active = False
            _condition.notify_all()
