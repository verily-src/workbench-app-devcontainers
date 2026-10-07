import time

from cache import ttl_cache


def test_hits_within_ttl():
    calls = []

    @ttl_cache(ttl=60)
    def fn(x):
        calls.append(x)
        return x * 2

    assert fn(2) == 4
    assert fn(2) == 4
    assert calls == [2]


def test_expires_after_ttl():
    calls = []

    @ttl_cache(ttl=0.05)
    def fn(x):
        calls.append(x)
        return x

    fn(1)
    time.sleep(0.08)
    fn(1)
    assert calls == [1, 1]


def test_invalidate_clears():
    calls = []

    @ttl_cache(ttl=60)
    def fn(x):
        calls.append(x)
        return x

    fn(1)
    fn.invalidate()
    fn(1)
    assert calls == [1, 1]


def test_maxsize_evicts_oldest():
    calls = []

    @ttl_cache(ttl=60, maxsize=2)
    def fn(x):
        calls.append(x)
        return x

    fn(1), fn(2), fn(3)   # evicts 1
    fn(3), fn(2)          # still cached
    fn(1)                 # recomputed
    assert calls == [1, 2, 3, 1]
