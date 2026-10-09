"""Offline market-data contract, calendar, normalization and API acceptance."""
import asyncio
from datetime import datetime
import json
import threading
import time
from unittest.mock import Mock, patch

import numpy as np
import pandas as pd
import requests
from fastapi.testclient import TestClient

from api.errors import AnalysisError
from api.main import create_app
from api.market.cache import MarketCache
from api.market.models import Quote, History, Scanner
from api.market.service import MarketDataService, UNIVERSE
from api.market.session import MarketCalendar
from api.market.yahoo_provider import YahooMarketDataProvider, finite
from api.models import normalize_symbol
from intraday.session import TZ
from tests.helpers import OfflineTestCase, response

NOW = datetime(2026, 10, 10, 12, tzinfo=TZ)


def payload_fixture():
    calendar = MarketCalendar()
    weekdays = pd.bdate_range(end='2026-10-09', periods=270, tz=TZ)+pd.Timedelta(hours=10)
    days = [day for day in weekdays if calendar.calendar.session(day.date()).open][-240:]
    close = (100+np.arange(240)*.1).tolist()
    return {'chart': {'error': None, 'result': [{
        'timestamp': [int(day.timestamp()) for day in days],
        'meta': {'regularMarketPrice': close[-1]+.2, 'regularMarketTime': int(pd.Timestamp('2026-10-09 18:09', tz=TZ).timestamp()), 'currency': 'TRY', 'chartPreviousClose': 50},
        'indicators': {'quote': [{'open': [v-.2 for v in close], 'high': [v+1 for v in close], 'low': [v-1 for v in close], 'close': close, 'volume': [1000]*240}]},
    }]}}


def provider_fixture():
    provider = Mock(name='provider')
    provider.name = 'Fixture provider'
    yahoo = YahooMarketDataProvider()
    provider.fetch_snapshot.side_effect = lambda symbol, now: yahoo.normalize(payload_fixture(), symbol, pd.Timestamp(now))
    return provider


class MarketApiTests(OfflineTestCase):
    def service(self, provider=None, **kwargs):
        service = MarketDataService(provider or provider_fixture(), now=lambda: NOW, **kwargs)
        self.addCleanup(service.close)
        return service

    def client(self, provider=None, **kwargs):
        market = self.service(provider, **kwargs)
        analysis = Mock()
        app = create_app(service=analysis, market_service=market)
        return TestClient(app, raise_server_exceptions=False), market, analysis

    def normalized(self, payload=None, now=NOW):
        return YahooMarketDataProvider().normalize(payload or payload_fixture(), 'ASELS.IS', pd.Timestamp(now))

    def test_ticker_normalization(self):
        for value in ('asels', 'ASELS.IS', ' asels.is '):
            self.assertEqual(normalize_symbol(value), 'ASELS.IS')

    def test_invalid_ticker_rejected_without_provider(self):
        client, service, _ = self.client()
        for symbol in ('123', 'ASELS.US', 'AS ELS', 'ÄSELS', 'A'*13):
            self.assertEqual(client.get('/api/v1/market/quote/'+symbol).status_code, 422)
        service.provider.fetch_snapshot.assert_not_called()

    def test_quote_schema_and_daily_baseline_not_range_reference(self):
        client, _, analysis = self.client()
        result = client.get('/api/v1/market/quote/asels')
        self.assertEqual(result.status_code, 200, result.text)
        quote = Quote.model_validate(result.json())
        self.assertEqual(quote.previous_close, 123.8)
        self.assertNotEqual(quote.previous_close, 50)
        self.assertAlmostEqual(quote.change, .3)
        self.assertEqual(quote.currency, 'TRY')
        self.assertEqual(quote.price_basis, 'provider_quote')
        self.assertEqual(quote.freshness_status, 'market_closed')
        json.dumps(result.json(), allow_nan=False)
        analysis.analyze.assert_not_called()

    def test_history_schema_and_no_invented_points(self):
        client, _, _ = self.client()
        result = client.get('/api/v1/market/history/ASELS?range=1mo')
        self.assertEqual(result.status_code, 200, result.text)
        history = History.model_validate(result.json())
        self.assertTrue(history.completed_only)
        self.assertTrue(all(point.date >= '2026-09-10' for point in history.points))
        self.assertEqual(history.points[-1].date, '2026-10-09')
        self.assertTrue(all(pd.Timestamp(point.timestamp) <= NOW for point in history.points))

    def test_only_supported_history_combinations(self):
        client, service, _ = self.client()
        for query in ('interval=1h', 'range=2y', 'interval=1m&range=1mo'):
            self.assertEqual(client.get('/api/v1/market/history/ASELS?'+query).status_code, 422)
        service.provider.fetch_snapshot.assert_not_called()

    def test_scanner_partial_failure_keeps_all_tickers(self):
        provider = provider_fixture()
        original = provider.fetch_snapshot.side_effect
        provider.fetch_snapshot.side_effect = lambda symbol, now: (_ for _ in ()).throw(AnalysisError('provider_unavailable', 'Unavailable', 502)) if symbol == 'FROTO.IS' else original(symbol, now)
        client, _, analysis = self.client(provider)
        response = client.get('/api/v1/market/scanner')
        result = Scanner.model_validate(response.json())
        self.assertEqual([row.ticker for row in result.rows], list(UNIVERSE))
        self.assertTrue(result.partial_failure)
        broken = next(row for row in result.rows if row.ticker == 'FROTO')
        self.assertIsNone(broken.price)
        self.assertEqual(broken.error.code, 'provider_unavailable')
        self.assertTrue(any(row.price is not None for row in result.rows))
        analysis.analyze.assert_not_called()

    def test_scanner_no_strategy_calls(self):
        client, _, _ = self.client()
        with patch('backtest.signals.prepare_indicators', side_effect=AssertionError('No analysis allowed')):
            result = client.get('/api/v1/market/scanner')
        self.assertEqual(result.status_code, 200)
        self.assertFalse(result.json()['strategy_analysis'])

    def test_stale_detection(self):
        payload = payload_fixture()
        payload['chart']['result'][0]['meta']['regularMarketTime'] = int(pd.Timestamp('2026-10-08 18:09', tz=TZ).timestamp())
        self.assertEqual(self.normalized(payload).quote.freshness_status, 'stale')

    def test_delayed_never_live_or_guaranteed_fresh(self):
        now = datetime(2026, 10, 9, 12, tzinfo=TZ)
        payload = payload_fixture()
        payload['chart']['result'][0]['meta']['regularMarketTime'] = int(pd.Timestamp('2026-10-09 11:55', tz=TZ).timestamp())
        result = self.normalized(payload, now)
        self.assertEqual(result.quote.freshness_status, 'delayed')
        self.assertEqual(result.quote.provider_delay_status, 'unknown')
        self.assertNotIn('2026-10-09', [point.date for point in result.points])
        self.assertEqual(result.quality.incomplete_rows, 1)

    def test_market_closed_weekend_and_holiday(self):
        calendar = MarketCalendar()
        self.assertEqual(calendar.info(NOW).status, 'closed')
        self.assertEqual(calendar.info(datetime(2026, 10, 29, 12, tzinfo=TZ)).status, 'holiday')

    def test_open_auction_and_half_day(self):
        calendar = MarketCalendar()
        for hour, minute, expected in ((9, 39, 'closed'), (9, 40, 'pre_market_or_auction'), (10, 0, 'open'), (18, 0, 'pre_market_or_auction'), (18, 10, 'closed')):
            self.assertEqual(calendar.info(datetime(2026, 10, 9, hour, minute, tzinfo=TZ)).status, expected)
        self.assertEqual(calendar.info(datetime(2026, 10, 28, 12, 35, tzinfo=TZ)).status, 'pre_market_or_auction')
        self.assertTrue(calendar.info(datetime(2026, 10, 28, 12, tzinfo=TZ)).half_day)
        self.assertEqual(calendar.info(datetime(2026, 10, 28, 12, 40, tzinfo=TZ)).status, 'closed')

    def test_unknown_calendar_year(self):
        self.assertEqual(MarketCalendar().info(datetime(2027, 1, 5, 12, tzinfo=TZ)).status, 'unknown')

    def test_provider_timeout(self):
        session = Mock()
        session.__enter__ = Mock(return_value=session)
        session.__exit__ = Mock(return_value=False)
        session.get.side_effect = requests.Timeout('private error')
        provider = YahooMarketDataProvider(session_factory=lambda: session)
        client, _, _ = self.client(provider)
        result = client.get('/api/v1/market/quote/ASELS')
        self.assertEqual(result.status_code, 504)
        self.assertNotIn('private', result.text)

    def test_provider_transport_failure(self):
        provider = provider_fixture()
        provider.fetch_snapshot.side_effect = AnalysisError('provider_unavailable', 'Unavailable', 502)
        client, _, _ = self.client(provider)
        self.assertEqual(client.get('/api/v1/market/quote/ASELS').status_code, 502)

    def test_nonfinite_metadata_sanitized(self):
        payload = payload_fixture()
        meta = payload['chart']['result'][0]['meta']
        meta.update(regularMarketPrice=np.nan, regularMarketVolume=np.inf, regularMarketDayHigh=-np.inf)
        result = self.normalized(payload)
        self.assertEqual(result.quote.price_basis, 'last_completed_close')
        self.assertTrue(np.isfinite(result.quote.price))
        json.dumps(result.model_dump(), allow_nan=False)

    def test_nonfinite_candle_history_not_fabricated(self):
        payload = payload_fixture()
        payload['chart']['result'][0]['indicators']['quote'][0]['volume'][10] = np.inf
        result = self.normalized(payload)
        self.assertEqual(result.points, [])
        self.assertIsNotNone(result.history_error)
        self.assertIsNotNone(result.quote.price)
        json.dumps(result.model_dump(), allow_nan=False)

    def test_missing_latest_close_history_stale_quote_independent(self):
        payload = payload_fixture()
        payload['chart']['result'][0]['indicators']['quote'][0]['close'][-1] = None
        result = self.normalized(payload)
        self.assertEqual(result.points[-1].date, '2026-10-08')
        self.assertEqual(result.quality.removed_rows, 1)
        self.assertEqual(result.quote.freshness_status, 'market_closed')
        self.assertEqual(MarketCalendar().freshness(result.points[-1].timestamp, pd.Timestamp(NOW), completed_close=True), 'stale')

    def test_future_rows_removed_before_price_validation(self):
        payload = payload_fixture()
        result = payload['chart']['result'][0]
        result['timestamp'].append(int(pd.Timestamp('2026-10-12 10:00', tz=TZ).timestamp()))
        for values in result['indicators']['quote'][0].values():
            values.append(np.inf)
        data = self.normalized(payload)
        self.assertEqual(data.quality.future_rows, 1)
        self.assertEqual(len(data.points), 240)
        self.assertTrue(all(pd.Timestamp(point.timestamp) <= NOW for point in data.points))

    def test_future_quote_timestamp_never_returned(self):
        payload = payload_fixture()
        payload['chart']['result'][0]['meta']['regularMarketTime'] = int(pd.Timestamp('2026-10-12 12:00', tz=TZ).timestamp())
        result = self.normalized(payload)
        self.assertIsNone(result.quote.quote_time)
        self.assertEqual(result.quote.price_basis, 'last_completed_close')

    def test_missing_quote_timestamp_unknown_not_current(self):
        payload = payload_fixture()
        del payload['chart']['result'][0]['meta']['regularMarketTime']
        self.assertEqual(self.normalized(payload).quote.freshness_status, 'unknown')

    def test_missing_previous_close_not_replaced_with_chart_reference(self):
        payload = payload_fixture()
        payload['chart']['result'][0]['indicators']['quote'][0]['close'][-2] = None
        result = self.normalized(payload)
        self.assertIsNone(result.quote.previous_close)
        self.assertIsNone(result.quote.change_pct)

    def test_cache_hit_expiry_and_quote_history_reuse(self):
        clock = [10.]
        client, service, _ = self.client(clock=lambda: clock[0])
        self.assertFalse(client.get('/api/v1/market/quote/ASELS').json()['cache']['hit'])
        self.assertTrue(client.get('/api/v1/market/quote/ASELS.IS').json()['cache']['hit'])
        client.get('/api/v1/market/history/ASELS?range=1y')
        self.assertEqual(service.provider.fetch_snapshot.call_count, 1)
        clock[0] = 56
        self.assertFalse(client.get('/api/v1/market/quote/ASELS').json()['cache']['hit'])
        self.assertEqual(service.provider.fetch_snapshot.call_count, 2)
        clock[0] = 100
        self.assertTrue(client.get('/api/v1/market/history/ASELS?range=1y').json()['cache']['hit'])

    def test_scanner_cache_and_single_flight(self):
        service = self.service()
        async def twice():
            return await asyncio.gather(service.scanner(), service.scanner())
        results = asyncio.run(twice())
        self.assertEqual(service.provider.fetch_snapshot.call_count, 10)
        self.assertEqual(len(results[0].rows), 10)
        self.assertTrue(asyncio.run(service.scanner()).cache.hit)
        self.assertEqual(service.provider.fetch_snapshot.call_count, 10)

    def test_cache_returns_independent_copies_and_bounded_size(self):
        cache = MarketCache(limit=1)
        quote = self.normalized().quote
        cache.put('a', quote, 45)
        value, _ = cache.get('a')
        value.price = 0
        self.assertNotEqual(cache.get('a')[0].price, 0)
        cache.put('b', quote, 45)
        self.assertIsNone(cache.get('a'))

    def test_no_more_than_two_provider_downloads(self):
        provider = provider_fixture()
        original = provider.fetch_snapshot.side_effect
        running, maximum = [0], [0]
        lock = threading.Lock()
        def slow(symbol, now):
            with lock:
                running[0] += 1
                maximum[0] = max(maximum[0], running[0])
            try:
                time.sleep(.02)
                return original(symbol, now)
            finally:
                with lock:
                    running[0] -= 1
        provider.fetch_snapshot.side_effect = slow
        asyncio.run(self.service(provider).scanner())
        self.assertLessEqual(maximum[0], 2)

    def test_model_rejects_nonfinite_numeric_json(self):
        from pydantic import ValidationError
        with self.assertRaises(ValidationError):
            Quote(ticker='ASELS', symbol='ASELS.IS', price=np.inf, provider='fixture', fetched_at=NOW.isoformat(), price_basis='provider_quote')

    def test_empty_provider_data(self):
        payload = payload_fixture()
        result = payload['chart']['result'][0]
        result['timestamp'] = []
        with self.assertRaises(AnalysisError):
            self.normalized(payload)

    def test_provider_headers_and_timeout(self):
        session = Mock()
        session.__enter__ = Mock(return_value=session)
        session.__exit__ = Mock(return_value=False)
        session.get.return_value = response(payload_fixture())
        YahooMarketDataProvider(session_factory=lambda: session).fetch_snapshot('ASELS.IS', NOW)
        self.assertEqual(session.get.call_args.kwargs['timeout'], (3, 8))
        self.assertFalse(session.get.call_args.kwargs['allow_redirects'])
        self.assertIn('range=1y', session.get.call_args.args[0])
