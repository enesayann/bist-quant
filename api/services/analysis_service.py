"""Bounded workers, single-flight requests and a thread-safe TTL/LRU cache."""
import asyncio
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
import threading
import time

from api.adapters.daily_strategy_adapter import DailyStrategyAdapter
from api.errors import AnalysisError
from api.models import normalize_symbol


class AnalysisService:
    def __init__(self, adapter=None, ttl=60, timeout=25, max_workers=2, max_entries=128, clock=time.monotonic):
        if ttl <= 0 or timeout <= 0 or max_workers < 1 or max_entries < 1:
            raise ValueError('Cache, timeout and worker limits must be positive')
        self.adapter = adapter or DailyStrategyAdapter()
        self.ttl, self.timeout, self.max_workers, self.max_entries = ttl, timeout, max_workers, max_entries
        self.clock = clock
        self.lock = threading.Lock()
        self.cache = OrderedDict()
        self.inflight = {}
        self.executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix='analysis-api')

    def _compute(self, key):
        started = self.clock()
        try:
            result = self.adapter.analyze(key[0], ttl_seconds=self.ttl)
            with self.lock:
                if self.clock() - started <= self.timeout:
                    self.cache[key] = (self.clock(), result.model_copy(deep=True))
                    self.cache.move_to_end(key)
                    while len(self.cache) > self.max_entries:
                        self.cache.popitem(last=False)
            return result
        finally:
            with self.lock:
                self.inflight.pop(key, None)

    async def analyze(self, ticker):
        key = (normalize_symbol(ticker), 'daily_v1', 'completed_technical_neutral')
        with self.lock:
            now = self.clock()
            for expired in [item for item, (saved, _) in self.cache.items() if now - saved >= self.ttl]:
                del self.cache[expired]
            if key in self.cache:
                saved, result = self.cache[key]
                self.cache.move_to_end(key)
                result = result.model_copy(deep=True)
                result.cache.hit = True
                result.cache.age_seconds = max(0, now-saved)
                return result
            future = self.inflight.get(key)
            if future is None:
                if len(self.inflight) >= self.max_workers:
                    raise AnalysisError('analysis_busy', 'Analysis capacity is busy. Try again shortly.', 503)
                future = self.executor.submit(self._compute, key)
                self.inflight[key] = future
        try:
            # Cancelling one HTTP waiter must not cancel a shared computation.
            return (await asyncio.wait_for(asyncio.shield(asyncio.wrap_future(future)), self.timeout)).model_copy(deep=True)
        except TimeoutError as error:
            raise AnalysisError('analysis_timeout', 'Analysis exceeded the request deadline. Try again later.', 504) from error

    def close(self):
        self.executor.shutdown(wait=False, cancel_futures=True)
