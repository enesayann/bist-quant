"""Pure deterministic explanation rules; provider/network/scoring stay untouched."""
import copy
import json
from unittest.mock import patch

from api.explanations.service import generate_explanation
from api.explanations.rules import atr_state, hist_state
from api.models import AnalysisResponse
from fastapi.testclient import TestClient
from api.main import create_app
from api.services.analysis_service import AnalysisService
from tests.test_analysis_api import adapter_fixture
from tests.helpers import OfflineTestCase


def snapshot(**indicators):
    return {'as_of': '2026-10-10T12:00:00+03:00', 'market': {'price': 110},
            'indicators': indicators, 'risk': {},
            'data_freshness': {'last_bar': '2026-10-09', 'is_stale': False, 'market_status': 'unknown'},
            'scores': {'overall': 42, 'technical': 52.5}, 'strategy': {'state': 'no_setup'}}


class ExplanationTests(OfflineTestCase):
    def test_bullish_ema_structure(self):
        result = generate_explanation(snapshot(ema20=105, ema50=100))
        self.assertEqual(result.trend.state, 'bullish')
        self.assertIn('above EMA20', ' '.join(result.trend.points))
        self.assertEqual(result.trend.evidence[0].inputs['analysis_close'], 110)

    def test_bearish_ema_structure(self):
        result = generate_explanation(snapshot(ema20=115, ema50=120))
        self.assertEqual(result.trend.state, 'bearish')
        self.assertIn('below EMA50', ' '.join(result.trend.points))

    def test_neutral_equal_ema(self):
        self.assertEqual(generate_explanation(snapshot(ema20=110, ema50=110)).trend.state, 'neutral')

    def test_missing_ema_partial_not_invented(self):
        result = generate_explanation(snapshot(ema20=105, ema50=None))
        self.assertEqual(result.trend.state, 'unknown')
        self.assertIn('ema50', result.trend.missing_inputs)
        self.assertFalse(any('EMA50' in point for point in result.trend.points))

    def test_mixed_ema_structure(self):
        self.assertEqual(generate_explanation(snapshot(ema20=115, ema50=100)).trend.state, 'mixed')

    def test_adx_threshold_boundaries(self):
        for adx, word in [(19.9, 'weak'), (20, 'moderate'), (25, 'moderate'), (25.1, 'strong')]:
            with self.subTest(adx=adx):
                text = ' '.join(generate_explanation(snapshot(adx=adx)).trend.points)
                self.assertIn(word+' trend strength', text)

    def test_supertrend_direction_only(self):
        for value, word in [(1, 'positive'), (-1, 'negative')]:
            self.assertIn(word, ' '.join(generate_explanation(snapshot(supertrend=value)).trend.points))
        self.assertEqual(generate_explanation(snapshot(supertrend=0)).trend.evidence, [])

    def test_high_rsi_overextended(self):
        for rsi in (70, 81, 100):
            self.assertEqual(generate_explanation(snapshot(rsi=rsi)).momentum.state, 'overextended')

    def test_low_rsi_weak(self):
        result = generate_explanation(snapshot(rsi=22))
        self.assertEqual(result.momentum.state, 'weak')
        self.assertIn('low RSI region', result.momentum.points[0])

    def test_neutral_rsi(self):
        for rsi in (45, 50, 54.99):
            self.assertEqual(generate_explanation(snapshot(rsi=rsi)).momentum.state, 'neutral')

    def test_positive_and_strong_rsi(self):
        self.assertEqual(generate_explanation(snapshot(rsi=55)).momentum.state, 'positive')
        self.assertEqual(generate_explanation(snapshot(rsi=60)).momentum.state, 'strong')

    def test_macd_above_signal(self):
        result = generate_explanation(snapshot(macd=-.2, macd_signal=-.4))
        self.assertEqual(result.momentum.state, 'positive')
        self.assertIn('above its signal', ' '.join(result.momentum.points))

    def test_macd_below_signal(self):
        result = generate_explanation(snapshot(macd=.2, macd_signal=.4))
        self.assertEqual(result.momentum.state, 'weak')
        self.assertIn('below its signal', ' '.join(result.momentum.points))

    def test_conflicting_rsi_macd_is_mixed(self):
        self.assertEqual(generate_explanation(snapshot(rsi=62, macd=-1, macd_signal=0)).momentum.state, 'mixed')

    def test_positive_cmf(self):
        result = generate_explanation(snapshot(cmf=.1))
        self.assertEqual(result.volume.state, 'positive')
        self.assertEqual(result.volume.evidence[0].inputs, {'cmf': .1})

    def test_negative_cmf(self):
        self.assertEqual(generate_explanation(snapshot(cmf=-.1)).volume.state, 'negative')

    def test_near_zero_cmf_and_boundaries(self):
        for value in (-.05, 0, .05):
            self.assertEqual(generate_explanation(snapshot(cmf=value)).volume.state, 'moderate')

    def test_vwap_comparison(self):
        result = generate_explanation(snapshot(vwap=115))
        self.assertIn('below the engine daily VWAP approximation', ' '.join(result.volume.points))

    def test_obv_single_level_not_direction(self):
        result = generate_explanation(snapshot(obv=12345))
        self.assertIn('cannot be inferred', ' '.join(result.volume.points))
        self.assertNotIn('rising', ' '.join(result.volume.points))
        self.assertNotIn('falling', ' '.join(result.volume.points))

    def test_relative_volume_unavailable(self):
        result = generate_explanation(snapshot(cmf=.2))
        self.assertIn('relative_volume', result.volume.missing_inputs)
        self.assertFalse(any('relative_volume' in evidence.inputs for evidence in result.volume.evidence))

    def test_atr_percentage_bands(self):
        for value, state in [(0, 'low'), (1.99, 'low'), (2, 'moderate'), (3.99, 'moderate'), (4, 'elevated'), (5.99, 'elevated'), (6, 'high')]:
            self.assertEqual(atr_state(value), state)

    def test_atr_safely_derived_and_traced(self):
        result = generate_explanation(snapshot(atr=5.5))
        self.assertEqual(result.risk.state, 'elevated')
        evidence = result.risk.evidence[0]
        self.assertTrue(evidence.derived)
        self.assertEqual(evidence.inputs['derived.atr_pct'], 5)

    def test_api_atr_percent_takes_precedence(self):
        data = snapshot(atr=5.5)
        data['risk']['atr_pct'] = 1
        result = generate_explanation(data)
        self.assertEqual(result.risk.state, 'low')
        self.assertFalse(result.risk.evidence[0].derived)

    def test_historical_volatility_bands_and_composite(self):
        for value, expected in [(19.9, 'low'), (20, 'moderate'), (40, 'elevated'), (65, 'elevated'), (65.1, 'high')]:
            self.assertEqual(hist_state(value), expected)
        data = snapshot(historical_volatility_pct=80)
        data['risk']['atr_pct'] = 1
        self.assertEqual(generate_explanation(data).risk.state, 'high')

    def test_missing_indicators_are_partial(self):
        result = generate_explanation(snapshot())
        for item in (result.trend, result.momentum, result.volume, result.risk):
            self.assertEqual(item.state, 'unknown')
            self.assertEqual(item.evidence, [])
            self.assertEqual(item.points, [])
        self.assertIn('unavailable', result.summary.text)

    def test_stale_warning(self):
        data = snapshot(rsi=50)
        data['data_freshness']['is_stale'] = True
        self.assertIn('may not represent the current session', ' '.join(generate_explanation(data).warnings))

    def test_market_closed_context(self):
        for status in ('closed', 'holiday'):
            data = snapshot()
            data['data_freshness']['market_status'] = status
            self.assertIn('closed or on holiday', ' '.join(generate_explanation(data).warnings))

    def test_unknown_market_not_guessed(self):
        result = generate_explanation(snapshot())
        self.assertEqual(result.market_status, 'unknown')
        self.assertFalse(any('closed or on holiday' in warning for warning in result.warnings))

    def test_summary_from_actual_states(self):
        data = snapshot(ema20=105, ema50=100, rsi=62, cmf=-.1, atr=1, historical_volatility_pct=10)
        result = generate_explanation(data)
        self.assertIn('constructive', result.summary.text)
        self.assertIn('strong', result.summary.text)
        self.assertIn('negative', result.summary.text)
        self.assertIn('volatility is low', result.summary.text)

    def test_nonfinite_and_invalid_regions_excluded(self):
        result = generate_explanation(snapshot(ema20=float('inf'), rsi=float('nan'), macd=-float('inf'), cmf=2, mfi=101, historical_volatility_pct=-1))
        for item in (result.trend, result.momentum, result.volume, result.risk):
            self.assertEqual(item.evidence, [])
        json.dumps(result.model_dump(), allow_nan=False)

    def test_overflow_derived_atr_not_emitted(self):
        data = snapshot(atr=1e308)
        data['market']['price'] = 1e-308
        result = generate_explanation(data)
        self.assertEqual(result.risk.state, 'unknown')
        self.assertIn('atr_pct', result.risk.missing_inputs)
        json.dumps(result.model_dump(), allow_nan=False)

    def test_no_predictions_advice_targets_or_fake_missing_metrics(self):
        result = generate_explanation(snapshot(ema20=105, ema50=100, rsi=78, macd=2, macd_signal=1, obv=100, cmf=.1, atr=1))
        text = result.model_dump_json().lower()
        for phrase in ('will rise', 'will fall', 'buy now', 'sell now', 'price target', 'is safe', 'guaranteed return', 'fundamentals neutral', 'news neutral'):
            self.assertNotIn(phrase, text)
        self.assertFalse(any('fundamental' in evidence.inputs or 'news' in evidence.inputs for part in (result.trend, result.momentum, result.volume, result.risk) for evidence in part.evidence))

    def test_pure_repeatable_no_input_mutation_or_scoring(self):
        data = snapshot(ema20=105, ema50=100, rsi=62, cmf=.1, atr=2)
        original = copy.deepcopy(data)
        with patch('bot.scoring.toplam_skorlar', side_effect=AssertionError('No scoring')), patch('api.market.yahoo_provider.YahooMarketDataProvider.fetch_snapshot', side_effect=AssertionError('No provider')):
            first, second = generate_explanation(data), generate_explanation(data)
        self.assertEqual(first, second)
        self.assertEqual(data, original)

    def test_response_additive_and_original_values_unchanged(self):
        adapter, _ = adapter_fixture()
        response = adapter.analyze('ASELS.IS')
        legacy = response.model_dump(exclude={'explanation'})
        regenerated = AnalysisResponse.model_validate(legacy)
        self.assertIsNotNone(regenerated.explanation)
        self.assertEqual(regenerated.model_dump(exclude={'explanation'}), legacy)
        self.assertEqual(regenerated.explanation.analysis_as_of, regenerated.as_of)

    def test_endpoint_and_cached_explanation(self):
        adapter, provider = adapter_fixture()
        service = AnalysisService(adapter)
        self.addCleanup(service.close)
        client = TestClient(create_app(service), raise_server_exceptions=False)
        first = client.post('/api/v1/analyze', json={'ticker': 'ASELS'})
        second = client.post('/api/v1/analyze', json={'ticker': 'asels.is'})
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(first.json()['explanation'], second.json()['explanation'])
        self.assertEqual(provider.fetch.call_count, 1)
        self.assertTrue(second.json()['cache']['hit'])
