import copy
import hashlib
import json
import os
import threading
import time
from collections import OrderedDict
from datetime import datetime, timezone

MAX_ENTRIES = 64
MAX_BYTES = 32 * 1024 * 1024
MAX_ENTRY_BYTES = 4 * 1024 * 1024


def _ttl():
    try:
        return max(0, min(300, int(os.environ.get("STUDIO_QUERY_CACHE_TTL", "30"))))
    except (TypeError, ValueError):
        return 30


class QueryCache:
    def __init__(self):
        self._items = OrderedDict()
        self._size = 0
        self._lock = threading.RLock()
        self._generation = {}

    def _remove(self, key):
        item = self._items.pop(key, None)
        if item:
            self._size -= item["size"]

    def invalidate_resource(self, resource_id):
        with self._lock:
            self._generation[resource_id] = self._generation.get(resource_id, 0) + 1
            for key, item in list(self._items.items()):
                if item["resource_id"] == resource_id:
                    self._remove(key)

    def generation(self, resource_id):
        with self._lock:
            return self._generation.get(resource_id, 0)

    def get(self, key, ttl):
        if ttl <= 0:
            return None
        now = time.monotonic()
        with self._lock:
            item = self._items.get(key)
            if item is None:
                return None
            if now - item["stored"] >= ttl:
                self._remove(key)
                return None
            self._items.move_to_end(key)
            return copy.deepcopy(item["value"]), item["as_of"]

    def put(self, key, resource_id, value, ttl, generation):
        if ttl <= 0:
            return None
        try:
            size = len(json.dumps(value, default=str, separators=(",", ":")).encode())
        except (TypeError, ValueError, OverflowError):
            return None
        if size > MAX_ENTRY_BYTES:
            return None
        stored = time.monotonic()
        as_of = datetime.now(timezone.utc).isoformat()
        with self._lock:
            if generation != self._generation.get(resource_id, 0):
                return None
            self._remove(key)
            self._items[key] = {"resource_id": resource_id, "value": copy.deepcopy(value),
                                "stored": stored, "as_of": as_of, "size": size}
            self._size += size
            while len(self._items) > MAX_ENTRIES or self._size > MAX_BYTES:
                oldest = next(iter(self._items))
                self._remove(oldest)
        return as_of

    def clear(self):
        with self._lock:
            self._items.clear()
            self._size = 0
            self._generation.clear()


cache = QueryCache()


def invalidate_resource(resource_id):
    cache.invalidate_resource(resource_id)


def make_key(resource_id, sql, columns, filters, charts, page, page_size,
             entity_column, generation=0, params=None):
    payload = [resource_id, generation, sql, list(columns.items()), filters, charts,
               page, page_size, entity_column, params or {}]
    raw = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()
