"""Bounded provider snapshots, shared quote/history data and partial scanner."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import threading
import time
import pandas as pd

from api.errors import AnalysisError
from api.models import normalize_symbol
from intraday.session import TZ
from .cache import MarketCache
from .models import CacheInfo, History, PublicError, Quote, Scanner
from .provider import MarketDataProvider
from .session import MarketCalendar
from .yahoo_provider import YahooMarketDataProvider

UNIVERSE = ('ASELS', 'THYAO', 'TUPRS', 'BIMAS', 'EREGL', 'KCHOL', 'GARAN', 'SISE', 'FROTO', 'TCELL')
QUOTE_TTL, SCANNER_TTL, HISTORY_TTL = 45, 60, 300


class MarketDataService:
    def __init__(self, provider: MarketDataProvider | None = None, *, now=None, clock=time.monotonic, timeout=24):
        self.provider = provider or YahooMarketDataProvider()
        self.calendar = MarketCalendar()
        self.now = now or (lambda: datetime.now(TZ))
        self.timeout = timeout
        self.cache = MarketCache(clock)
        self.executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix='market-data')
        self.lock = threading.Lock()
        self.jobs = {}
        self.scanner_future = None

    def _download(self, key):
        try:
            result = self.provider.fetch_snapshot(key[1], self.now())
            # Provider-neutral finite contract validates external implementations too.
            from .models import ProviderSnapshot
            result = ProviderSnapshot.model_validate(result.model_dump())
            if result.quote.symbol != key[1]:
                raise AnalysisError('invalid_market_data', 'Provider returned a different ticker.', 502)
            now = pd.Timestamp(self.now()).tz_convert(TZ)
            stamps = [point.timestamp for point in result.points] + [value for value in (result.quote.quote_time, result.quote.last_bar_time, result.quote.fetched_at) if value]
            if any(pd.Timestamp(value).tz_convert(TZ) > now for value in stamps):
                raise AnalysisError('invalid_market_data', 'Provider returned future timestamps.', 502)
            self.cache.put(key, result, QUOTE_TTL)
            return result
        finally:
            with self.lock:
                self.jobs.pop(key, None)

    async def _snapshot(self, ticker):
        symbol = normalize_symbol(ticker)
        key = ('source', symbol, '1d', '1y')
        cached = self.cache.get(key)
        if cached:
            return cached[0], True, cached[1]
        # At most two submitted downloads. Scanner waiters do not enqueue work.
        deadline = asyncio.get_running_loop().time()+self.timeout
        while True:
            cached = self.cache.get(key)
            if cached:
                return cached[0], True, cached[1]
            with self.lock:
                future = self.jobs.get(key)
                if future is None and len(self.jobs) < 2:
                    future = self.executor.submit(self._download, key)
                    self.jobs[key] = future
            if future is not None:
                break
            if asyncio.get_running_loop().time() >= deadline:
                raise AnalysisError('market_busy', 'Market provider capacity is busy.', 503)
            await asyncio.sleep(.1)
        remaining = deadline-asyncio.get_running_loop().time()
        try:
            snapshot = await asyncio.wait_for(asyncio.shield(asyncio.wrap_future(future)), max(.01, remaining))
            return snapshot, False, 0
        except TimeoutError as error:
            raise AnalysisError('market_timeout', 'Market-data request deadline exceeded.', 504) from error
        except AnalysisError:
            raise
        except Exception as error:
            raise AnalysisError('market_unavailable', 'Market-data provider returned unusable data.', 502) from error

    async def quote(self, ticker):
        result, hit, age = await self._snapshot(ticker)
        quote = result.quote.model_copy(deep=True)
        now = pd.Timestamp(self.now()).tz_convert(TZ)
        quote.market_status = self.calendar.info(now).status
        quote.freshness_status = self.calendar.freshness(quote.quote_time if quote.price_basis == 'provider_quote' else quote.last_bar_time,
                                                       now, completed_close=quote.price_basis == 'last_completed_close',
                                                       guarantee=quote.provider_delay_status == 'real_time_guaranteed')
        quote.cache = CacheInfo(hit=hit, ttl_seconds=QUOTE_TTL, age_seconds=age)
        return quote

    async def history(self, ticker, interval='1d', range='3mo'):
        symbol = normalize_symbol(ticker)
        if interval != '1d' or range not in ('1mo', '3mo', '6mo', '1y'):
            raise AnalysisError('unsupported_history', 'Supported history: interval=1d; range=1mo,3mo,6mo,1y. Hourly history awaits intraday-contract integration.', 422)
        key = ('history', symbol, interval, range)
        cached = self.cache.get(key)
        now = pd.Timestamp(self.now()).tz_convert(TZ)
        if cached:
            result, age = cached
            result.cache = CacheInfo(hit=True, ttl_seconds=HISTORY_TTL, age_seconds=age)
            result.market_status = self.calendar.info(now).status
            result.freshness_status = self.calendar.freshness(result.last_bar_time, now, completed_close=True)
            return result
        snapshot, _, _ = await self._snapshot(symbol)
        if snapshot.history_error or not snapshot.points:
            raise AnalysisError('no_history', snapshot.history_error.message if snapshot.history_error else 'No completed price history.', 422)
        cutoff = now-pd.DateOffset(months={'1mo': 1, '3mo': 3, '6mo': 6, '1y': 12}[range])
        points = [point for point in snapshot.points if point.date >= cutoff.date().isoformat()]
        if not points:
            raise AnalysisError('no_history', 'No completed candles in the requested range.', 422)
        result = History(ticker=symbol.removesuffix('.IS'), symbol=symbol, range=range, provider=self.provider.name,
                         fetched_at=snapshot.quote.fetched_at, points=points, quality=snapshot.quality,
                         last_bar_time=points[-1].timestamp, market_status=self.calendar.info(now).status,
                         freshness_status=self.calendar.freshness(points[-1].timestamp, now, completed_close=True),
                         cache=CacheInfo(ttl_seconds=HISTORY_TTL))
        self.cache.put(key, result, HISTORY_TTL)
        return result

    async def _scanner(self):
        rows = {}
        async def one(ticker):
            try:
                rows[ticker] = await self.quote(ticker)
            except AnalysisError as error:
                rows[ticker] = Quote(ticker=ticker, symbol=ticker+'.IS', provider=self.provider.name,
                                     fetched_at=self.now().isoformat(), price_basis='unavailable',
                                     market_status=self.calendar.info(self.now()).status,
                                     error=PublicError(code=error.code, message=error.message))
            except Exception:
                rows[ticker] = Quote(ticker=ticker, symbol=ticker+'.IS', provider=self.provider.name,
                                     fetched_at=self.now().isoformat(), price_basis='unavailable',
                                     error=PublicError(code='provider_unavailable', message='Market data unavailable for this ticker.'))
        tasks = [asyncio.create_task(one(ticker)) for ticker in UNIVERSE]
        done, pending = await asyncio.wait(tasks, timeout=self.timeout)
        for task in pending:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        for ticker in UNIVERSE:
            if ticker not in rows:
                rows[ticker] = Quote(ticker=ticker, symbol=ticker+'.IS', provider=self.provider.name,
                                     fetched_at=self.now().isoformat(), price_basis='unavailable',
                                     error=PublicError(code='market_timeout', message='Scanner deadline exceeded for this ticker.'))
        result = Scanner(fetched_at=self.now().isoformat(), session=self.calendar.info(self.now()), provider=self.provider.name,
                         rows=[rows[ticker] for ticker in UNIVERSE], partial_failure=any(row.error for row in rows.values()),
                         cache=CacheInfo(ttl_seconds=SCANNER_TTL))
        self.cache.put(('scanner',), result, SCANNER_TTL)
        return result

    async def scanner(self):
        cached = self.cache.get(('scanner',))
        if cached:
            result, age = cached
            result.cache = CacheInfo(hit=True, ttl_seconds=SCANNER_TTL, age_seconds=age)
            now = pd.Timestamp(self.now()).tz_convert(TZ)
            result.session = self.calendar.info(now)
            for quote in result.rows:
                quote.market_status = result.session.status
                quote.freshness_status = self.calendar.freshness(quote.quote_time if quote.price_basis == 'provider_quote' else quote.last_bar_time, now,
                                                               completed_close=quote.price_basis == 'last_completed_close', guarantee=quote.provider_delay_status == 'real_time_guaranteed')
            return result
        # Event-loop single-flight is app-owned; all routes run in the same loop.
        if self.scanner_future is None or self.scanner_future.done():
            self.scanner_future = asyncio.create_task(self._scanner())
        return (await asyncio.shield(self.scanner_future)).model_copy(deep=True)

    def close(self):
        self.executor.shutdown(wait=False, cancel_futures=True)
