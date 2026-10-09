"""Offline API acceptance tests. No request can escape to Yahoo or Telegram."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import json
import threading
import time
from unittest.mock import Mock, patch

import numpy as np
import pandas as pd
from fastapi.testclient import TestClient
from pydantic import ValidationError
import requests

from api.adapters.daily_strategy_adapter import BoundedSession, DailyStrategyAdapter
from api.errors import AnalysisError
from api.main import create_app
from api.models import AnalyzeRequest, AnalysisResponse, Indicators, normalize_symbol
from api.services.analysis_service import AnalysisService
from backtest.signals import prepare_indicators, signal_from_history
from bot.config import TR_TZ
from tests.helpers import OfflineTestCase


def frame_fixture(length=240):
    x = np.arange(length)
    close = 100 + x * .12 + np.sin(x / 3)
    return pd.DataFrame({'Open': close-.2, 'High': close+1, 'Low': close-1,
                         'Close': close, 'Volume': np.full(length, 1000.)},
                        index=pd.bdate_range(end='2026-10-09', periods=length))


def adapter_fixture(frame=None):
    provider = Mock()
    provider.fetch.return_value = frame_fixture() if frame is None else frame
    return DailyStrategyAdapter(provider, now=lambda: datetime(2026, 10, 10, 12, tzinfo=TR_TZ)), provider


class AnalysisApiTests(OfflineTestCase):
    def client_for(self, frame=None, **settings):
        adapter, provider = adapter_fixture(frame)
        service = AnalysisService(adapter, **settings)
        self.addCleanup(service.close)
        return TestClient(create_app(service), raise_server_exceptions=False), provider, service

    def test_normalizes_common_forms(self):
        for ticker in ('ASELS', 'ASELS.IS', 'asels', 'asels.is', '  asels.is  '):
            with self.subTest(ticker=ticker):
                self.assertEqual(AnalyzeRequest(ticker=ticker).ticker, 'ASELS.IS')

    def test_invalid_tickers(self):
        for ticker in ('', '123', '../ASELS', 'ASELS.US', 'AS ELS', 'ASELS?x=1', 'ÄSELS', 'A'*13, None, 42, True):
            with self.subTest(ticker=ticker), self.assertRaises((ValidationError, ValueError)):
                AnalyzeRequest(ticker=ticker)

    def test_health_is_read_only(self):
        client, provider, _ = self.client_for()
        self.assertEqual(client.get('/api/v1/health').json()['status'], 'ok')
        provider.fetch.assert_not_called()

    def test_v2_not_implemented(self):
        client, provider, _ = self.client_for()
        states = {row['name']: row['status'] for row in client.get('/api/v1/strategies/status').json()['strategies']}
        self.assertEqual(states['Intraday Strategy v2'], 'not_implemented')
        self.assertEqual(states['Intraday Data Contract'], 'ready')
        provider.fetch.assert_not_called()

    def test_response_schema_and_provenance(self):
        client, provider, _ = self.client_for()
        response = client.post('/api/v1/analyze', json={'ticker': 'asels'})
        self.assertEqual(response.status_code, 200, response.text)
        result = AnalysisResponse.model_validate(response.json())
        self.assertEqual(result.symbol, 'ASELS.IS')
        self.assertIsNone(result.scores.news)
        self.assertIsNone(result.scores.fundamental)
        self.assertEqual(result.market.price, frame_fixture().Close.iloc[-1])
        self.assertEqual(result.market.previous_close, frame_fixture().Close.iloc[-2])
        self.assertEqual(result.scores.category_maxima['trend'], 25)
        self.assertEqual(result.data_freshness.last_bar, '2026-10-09')
        self.assertFalse(result.data_freshness.is_stale)
        self.assertEqual(result.data_freshness.market_status, 'unknown')
        self.assertEqual(len(result.price_series), 240)
        json.dumps(response.json(), allow_nan=False)
        provider.fetch.assert_called_once_with('ASELS.IS', '2024-10-09', '2026-10-09')

    def test_existing_signal_decision_is_reused(self):
        adapter, _ = adapter_fixture()
        response = adapter.analyze('ASELS.IS')
        signal = signal_from_history('ASELS.IS', prepare_indicators(frame_fixture()))
        self.assertEqual(response.strategy.signal, signal.signal_type if signal else None)
        self.assertEqual(response.strategy.state, 'setup' if signal else 'no_setup')

    def test_optional_indicator_nonfinite_becomes_null(self):
        value = Indicators(rsi=float('nan'), adx=float('inf'), cmf=-float('inf'), atr=1.2)
        self.assertIsNone(value.rsi)
        self.assertIsNone(value.adx)
        self.assertIsNone(value.cmf)
        self.assertEqual(value.atr, 1.2)
        self.assertNotIn('NaN', value.model_dump_json())

    def test_derived_nonfinite_indicator_in_response(self):
        client, _, _ = self.client_for()
        enriched = prepare_indicators(frame_fixture())
        enriched.loc[enriched.index[-1], 'MFI'] = np.inf
        with patch('api.adapters.daily_strategy_adapter.prepare_indicators', return_value=enriched):
            response = client.post('/api/v1/analyze', json={'ticker': 'ASELS'})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIsNone(response.json()['indicators']['mfi'])

    def test_missing_ohlcv_row_removed_and_reported(self):
        frame = frame_fixture()
        frame.loc[frame.index[20], 'Close'] = np.nan
        client, _, _ = self.client_for(frame)
        response = client.post('/api/v1/analyze', json={'ticker': 'ASELS'})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['data_quality']['rows_removed'], 1)
        self.assertEqual(response.json()['data_quality']['usable_rows'], 239)
        self.assertIn('missing Close', ' '.join(response.json()['data_quality']['warnings']))

    def test_infinite_ohlcv_rejected(self):
        for value in (np.inf, -np.inf):
            frame = frame_fixture()
            frame.loc[frame.index[20], 'Volume'] = value
            client, _, _ = self.client_for(frame)
            response = client.post('/api/v1/analyze', json={'ticker': 'ASELS'})
            self.assertEqual(response.status_code, 502)
            self.assertEqual(response.json()['error']['code'], 'invalid_data')

    def test_negative_and_inconsistent_candles_rejected(self):
        for column, value in [('Volume', -1), ('Low', 500), ('Open', -1)]:
            frame = frame_fixture()
            frame.loc[frame.index[10], column] = value
            client, _, _ = self.client_for(frame)
            self.assertEqual(client.post('/api/v1/analyze', json={'ticker': 'ASELS'}).status_code, 502)

    def test_empty_provider(self):
        client, _, _ = self.client_for(pd.DataFrame())
        response = client.post('/api/v1/analyze', json={'ticker': 'ASELS'})
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()['error']['code'], 'no_data')

    def test_provider_failure_is_sanitized(self):
        client, provider, _ = self.client_for()
        provider.fetch.side_effect = requests.HTTPError('private provider traceback secret')
        response = client.post('/api/v1/analyze', json={'ticker': 'ASELS'})
        self.assertEqual(response.status_code, 502)
        self.assertNotIn('secret', response.text)
        self.assertNotIn('traceback', response.text)

    def test_provider_timeout(self):
        client, provider, _ = self.client_for()
        provider.fetch.side_effect = requests.Timeout('private error')
        self.assertEqual(client.post('/api/v1/analyze', json={'ticker': 'ASELS'}).status_code, 504)

    def test_unexpected_exception_sanitized(self):
        client, provider, _ = self.client_for()
        provider.fetch.side_effect = RuntimeError('private secret')
        response = client.post('/api/v1/analyze', json={'ticker': 'ASELS'})
        self.assertEqual(response.status_code, 500)
        self.assertNotIn('secret', response.text)

    def test_request_errors_do_not_call_provider(self):
        client, provider, _ = self.client_for()
        for payload in ({}, {'ticker': 'AS ELS'}, {'ticker': 10}, {'ticker': 'ASELS', 'execute': True}):
            self.assertEqual(client.post('/api/v1/analyze', json=payload).status_code, 422)
        provider.fetch.assert_not_called()

    def test_cors_local_origins_only(self):
        client, _, _ = self.client_for()
        for origin in ('http://127.0.0.1:5173', 'http://localhost:5173'):
            response = client.options('/api/v1/analyze', headers={'Origin': origin, 'Access-Control-Request-Method': 'POST', 'Access-Control-Request-Headers': 'content-type'})
            self.assertEqual(response.headers['access-control-allow-origin'], origin)
        response = client.get('/api/v1/health', headers={'Origin': 'https://untrusted.example'})
        self.assertNotIn('access-control-allow-origin', response.headers)

    def test_cache_normalization_and_expiry(self):
        clock = [10.0]
        client, provider, service = self.client_for(clock=lambda: clock[0], ttl=60)
        first = client.post('/api/v1/analyze', json={'ticker': 'asels'}).json()
        clock[0] = 20
        second = client.post('/api/v1/analyze', json={'ticker': 'ASELS.IS'}).json()
        self.assertFalse(first['cache']['hit'])
        self.assertTrue(second['cache']['hit'])
        self.assertEqual(second['cache']['age_seconds'], 10)
        self.assertEqual(provider.fetch.call_count, 1)
        second['market']['price'] = 0
        self.assertGreater(asyncio.run(service.analyze('ASELS')).market.price, 0)
        clock[0] = 71
        self.assertFalse(client.post('/api/v1/analyze', json={'ticker': 'ASELS'}).json()['cache']['hit'])
        self.assertEqual(provider.fetch.call_count, 2)

    def test_cache_bound_and_no_failed_result_cache(self):
        client, provider, service = self.client_for(max_entries=1)
        client.post('/api/v1/analyze', json={'ticker': 'ASELS'})
        client.post('/api/v1/analyze', json={'ticker': 'GARAN'})
        self.assertEqual(len(service.cache), 1)
        provider.fetch.side_effect = requests.HTTPError('failure')
        for _ in range(2):
            self.assertEqual(client.post('/api/v1/analyze', json={'ticker': 'THYAO'}).status_code, 502)
        self.assertEqual(provider.fetch.call_count, 4)

    def test_concurrent_identical_requests_single_download(self):
        adapter, provider = adapter_fixture()
        original = adapter.analyze
        def slow(*args, **kwargs):
            time.sleep(.05)
            return original(*args, **kwargs)
        adapter.analyze = slow
        service = AnalysisService(adapter)
        self.addCleanup(service.close)
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: asyncio.run(service.analyze('ASELS')), range(4)))
        self.assertEqual(provider.fetch.call_count, 1)
        self.assertTrue(all(result.symbol == 'ASELS.IS' for result in results))

    def test_deadline_and_worker_capacity(self):
        release = threading.Event()
        started = threading.Event()
        adapter = Mock()
        def wait(*args, **kwargs):
            started.set()
            release.wait(2)
            raise AnalysisError('no_data', 'No data', 422)
        adapter.analyze.side_effect = wait
        service = AnalysisService(adapter, timeout=.02, max_workers=1)
        self.addCleanup(service.close)
        try:
            with self.assertRaises(AnalysisError) as error:
                asyncio.run(service.analyze('ASELS'))
            self.assertEqual(error.exception.code, 'analysis_timeout')
            self.assertTrue(started.is_set())
            with self.assertRaises(AnalysisError) as error:
                asyncio.run(service.analyze('GARAN'))
            self.assertEqual(error.exception.code, 'analysis_busy')
        finally:
            release.set()

    def test_insufficient_data(self):
        client, _, _ = self.client_for(frame_fixture(30))
        self.assertEqual(client.post('/api/v1/analyze', json={'ticker': 'ASELS'}).json()['error']['code'], 'insufficient_data')

    def test_stale_data_exposed(self):
        client, _, _ = self.client_for(frame_fixture().iloc[:-2])
        result = client.post('/api/v1/analyze', json={'ticker': 'ASELS'}).json()
        self.assertTrue(result['data_freshness']['is_stale'])

    def test_future_candles_rejected(self):
        frame = frame_fixture()
        frame.index = frame.index + pd.Timedelta(days=10)
        client, _, _ = self.client_for(frame)
        self.assertEqual(client.post('/api/v1/analyze', json={'ticker': 'ASELS'}).status_code, 502)

    def test_transport_bounded_without_shared_bot_session(self):
        transport = BoundedSession()
        self.addCleanup(transport.close)
        with patch.object(transport.session, 'get') as get:
            transport.get('https://query1.finance.yahoo.com/example', timeout=30)
            self.assertEqual(get.call_args.kwargs['timeout'], (3, 12))
            self.assertFalse(get.call_args.kwargs['allow_redirects'])
        self.assertEqual(normalize_symbol('garAn'), 'GARAN.IS')
