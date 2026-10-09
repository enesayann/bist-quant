"""API-owned TTL/LRU cache; never touches analysis or bot caches."""
from collections import OrderedDict
import threading
import time


class MarketCache:
    def __init__(self, clock=time.monotonic, limit=128):
        self.clock, self.limit = clock, limit
        self.lock = threading.Lock()
        self.items = OrderedDict()

    def get(self, key):
        with self.lock:
            now = self.clock()
            for stale in [key for key, (saved, ttl, _) in self.items.items() if now-saved >= ttl]:
                del self.items[stale]
            if key not in self.items:
                return None
            saved, _, value = self.items[key]
            self.items.move_to_end(key)
            return value.model_copy(deep=True), now-saved

    def put(self, key, value, ttl):
        with self.lock:
            self.items[key] = (self.clock(), ttl, value.model_copy(deep=True))
            self.items.move_to_end(key)
            while len(self.items) > self.limit:
                self.items.popitem(last=False)
