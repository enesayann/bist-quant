"""Historical strategy parity and causal information boundaries (offline)."""
from unittest.mock import patch

import numpy as np
import pandas as pd

from backtest.signals import (Signal, confirmed_pivots, evaluate_signal,
                              prepare_indicators, signal_from_history, support_resistance)
from bot import indicators, scoring
from tests.helpers import OfflineTestCase


def historical_frame(length=240):
    x = np.arange(length)
    close = 100 + x * .1 + np.sin(x / 3)
    return pd.DataFrame({'Open': close, 'High': close + 1, 'Low': close - 1,
                         'Close': close, 'Volume': np.full(length, 1000.)},
                        index=pd.bdate_range('2022-01-03', periods=length))


def test_signal(ticker, date, price=100, atr=10):
    return Signal(ticker=ticker, signal_date=str(date)[:10], entry_reference_price=price,
                  trend_score=25, momentum_score=20, volume_score=15, volatility_score=10,
                  fundamental_score=0, news_score=0, support_resistance_adjustment=0,
                  final_score=70, technical_score=87.5, confidence=8,
                  classification='🟢 LONG', signal_type='TECHNICAL',
                  initial_stop=price - 1.5 * atr, tp1=price + 2 * atr,
                  tp2=price + 3 * atr, atr_at_entry=atr)


class SignalTests(OfflineTestCase):
    def test_future_candles_cannot_change_past_signal(self):
        frame = historical_frame(260)
        frame.iloc[239, frame.columns.get_loc('Volume')] = 100000
        frame.loc[frame.index[239], ['Open', 'High', 'Low', 'Close']] += 2
        with patch('bot.news.haber_duyarlilik_kontrol', side_effect=AssertionError('No news')), patch(
                'bot.market_data.temel_verileri_getir', side_effect=AssertionError('No current fundamentals')):
            past = evaluate_signal('ASELS.IS', frame.iloc[:240], frame.index[239])
            extended = evaluate_signal('ASELS.IS', frame, frame.index[239])
        self.assertIsNotNone(past)
        self.assertEqual(past, extended)
        self.assertEqual((past.news_score, past.fundamental_score, past.signal_type), (0, 0, 'WHALE'))

    def test_prepared_indicators_unchanged_by_future(self):
        frame = historical_frame(260)
        original = prepare_indicators(frame.iloc[:240])
        frame.iloc[240:, frame.columns.get_loc('Close')] += 100
        frame.iloc[240:, frame.columns.get_loc('High')] += 100
        frame.iloc[240:, frame.columns.get_loc('Low')] += 100
        pd.testing.assert_frame_equal(original, prepare_indicators(frame).iloc[:240])

    def test_centered_pivots_are_delayed_until_confirmation(self):
        frame = historical_frame(11)
        frame['High'] = [10, 11, 12, 13, 14, 20, 14, 13, 12, 11, 10]
        frame['Low'] = [9, 8, 7, 6, 5, 1, 5, 6, 7, 8, 9]
        self.assertEqual(tuple(map(len, confirmed_pivots(frame.iloc[:10]))), (0, 0))
        highs, lows = confirmed_pivots(frame)
        self.assertEqual((highs.iloc[0], lows.iloc[0]), (20, 1))
        self.assertEqual(highs.index[0], frame.index[10])

    def test_safe_support_matches_prefix_live_result(self):
        frame = historical_frame(100)
        for length in (10, 30, 60, 75, 100):
            prefix = frame.iloc[:length]
            self.assertEqual(support_resistance(prefix), indicators.guclu_destek_direnc_hesapla(prefix))

    def test_hhhl_safe_confirmed_equivalent_matches_live_prefix(self):
        frame = historical_frame(130)
        for length in range(13, 131):
            highs, lows = confirmed_pivots(frame.iloc[:length])
            safe = bool(len(highs) >= 2 and len(lows) >= 2
                        and highs.iloc[-1] > highs.iloc[-2] and lows.iloc[-1] > lows.iloc[-2])
            self.assertEqual(safe, indicators.higher_high_higher_low_mi(frame.iloc[:length]))

    def test_future_extremes_do_not_change_historical_support(self):
        frame = historical_frame(100)
        at = frame.index[79]
        before = support_resistance(frame.loc[:at])
        frame.loc[frame.index[80:], 'High'] = 99999
        frame.loc[frame.index[80:], 'Low'] = .01
        self.assertEqual(before, support_resistance(frame.loc[:at]))

    def test_insufficient_history_does_not_signal(self):
        self.assertIsNone(evaluate_signal('ASELS.IS', historical_frame(59), '2025-01-01'))

    def test_scores_use_original_weights_and_denominator(self):
        frame = historical_frame()
        frame.iloc[-1, frame.columns.get_loc('Volume')] = 100000
        frame.loc[frame.index[-1], ['Open', 'High', 'Low', 'Close']] += 2
        signal = evaluate_signal('ASELS.IS', frame, frame.index[-1])
        expected = scoring.toplam_skorlar(signal.trend_score, signal.momentum_score,
                                         signal.volume_score, signal.volatility_score, 0, 0,
                                         signal.support_resistance_adjustment)
        self.assertEqual((signal.final_score, signal.technical_score), expected)
        self.assertEqual(signal.confidence, min(10, int(signal.technical_score / 10) + 2))
        self.assertEqual(signal.classification, scoring.siniflandirma_etiketi(signal.confidence))

    def test_neutral_news_technical_threshold_and_whale_exception(self):
        df = prepare_indicators(historical_frame(100))
        df.loc[df.index[-3:], 'SMA_20'] = 1
        df.loc[df.index[-1], ['SMA_50', 'EMA20', 'EMA50']] = [50, 80, 70]
        with patch('backtest.signals.scoring.toplam_skorlar', return_value=(50, 69.9)):
            self.assertIsNone(signal_from_history('ASELS.IS', df))
        with patch('backtest.signals.scoring.toplam_skorlar', return_value=(50, 70)):
            signal = signal_from_history('ASELS.IS', df)
            self.assertEqual((signal.signal_type, signal.confidence), ('TECHNICAL', 7))
        df.loc[df.index[-1], 'Volume'] = 100000
        with patch('backtest.signals.scoring.toplam_skorlar', return_value=(10, 10)):
            signal = signal_from_history('ASELS.IS', df)
            self.assertEqual((signal.signal_type, signal.confidence), ('WHALE', 3))

    def test_invalid_atr_skips_signal(self):
        df = prepare_indicators(historical_frame())
        for atr in (0, -1, np.nan, np.inf):
            df.loc[df.index[-1], 'ATR'] = atr
            self.assertIsNone(signal_from_history('ASELS.IS', df))

    def test_ema_and_ichimoku_data_gates_preserved(self):
        df = prepare_indicators(historical_frame())
        original = scoring.trend_puani_hesapla
        for count, flags in ((60, (False, False)), (78, (False, True)), (200, (True, True))):
            with patch('backtest.signals.scoring.trend_puani_hesapla', wraps=original) as trend:
                signal_from_history('ASELS.IS', df.iloc[:count])
            self.assertEqual(trend.call_args.args[2:], flags)
