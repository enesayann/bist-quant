import math

import numpy as np
import pandas as pd

from bot import indicators as ind, portfolio
from tests.helpers import OfflineTestCase


class IndicatorTests(OfflineTestCase):
    def test_rsi_rising_falling_and_warmup(self):
        rising = ind.hesapla_rsi_wilder(pd.Series(range(1, 61), dtype=float))
        falling = ind.hesapla_rsi_wilder(pd.Series(range(60, 0, -1), dtype=float))
        self.assertTrue(rising.iloc[:13].isna().all())
        self.assertEqual(rising.iloc[-1], 100)
        self.assertEqual(falling.iloc[-1], 0)

    def test_rsi_mixed_prices_original_ewm_seed(self):
        rsi = ind.hesapla_rsi_wilder(pd.Series([10., 11., 10., 12., 11., 13.]), 3)
        # Hand-calculated Wilder recursion from the original zero-delta seed.
        self.assertAlmostEqual(rsi.iloc[2], 40)
        self.assertAlmostEqual(rsi.iloc[3], 100 * 22 / 28)
        self.assertAlmostEqual(rsi.iloc[-1], 100 * 250 / 328)

    def test_atr_includes_gap(self):
        df = pd.DataFrame({"High": [101.] * 30, "Low": [99.] * 30, "Close": [100.] * 30})
        atr = ind.hesapla_atr_wilder(df)
        self.assertTrue(atr.iloc[:13].isna().all())
        self.assertEqual(atr.iloc[-1], 2)
        gap = pd.DataFrame({"High": [101., 111.], "Low": [99., 109.], "Close": [100., 110.]})
        self.assertEqual(ind.hesapla_true_range(gap).iloc[-1], 11)

    def test_macd_constant_and_ramp(self):
        macd, signal = ind.hesapla_macd(pd.Series([100.] * 60))
        self.assertEqual(macd.iloc[-1], 0)
        self.assertEqual(signal.iloc[-1], 0)
        macd, signal = ind.hesapla_macd(pd.Series(range(1, 61), dtype=float))
        self.assertAlmostEqual(macd.iloc[-1], 6.866964287009345)
        self.assertGreater(macd.iloc[-1], signal.iloc[-1])

    def test_adx_directional_and_flat(self):
        close = pd.Series(range(1, 61), dtype=float)
        directional = pd.DataFrame({"High": close + 1, "Low": close - 1, "Close": close})
        self.assertAlmostEqual(ind.hesapla_adx(directional).iloc[-1], 100)
        flat = pd.DataFrame({"High": [101.] * 60, "Low": [99.] * 60, "Close": [100.] * 60})
        self.assertTrue(ind.hesapla_adx(flat).isna().all())

    def test_bollinger_sample_standard_deviation(self):
        upper, middle, lower = ind.hesapla_bollinger(pd.Series(range(1, 21), dtype=float))
        self.assertEqual(middle.iloc[-1], 10.5)
        self.assertAlmostEqual(upper.iloc[-1], 10.5 + 2 * math.sqrt(35))
        self.assertAlmostEqual(lower.iloc[-1], 10.5 - 2 * math.sqrt(35))

    def test_supertrend_initializes_after_atr_warmup(self):
        close = pd.Series([100.] * 20 + list(np.linspace(99, 60, 30)))
        df = pd.DataFrame({"High": close + 1, "Low": close - 1, "Close": close})
        self.assertEqual(ind.hesapla_supertrend(df).iloc[-1], -1)

    def test_position_sizing(self):
        self.assertEqual(portfolio.pozisyon_buyuklugu_hesapla(100, 95), 200)
        self.assertEqual(portfolio.pozisyon_buyuklugu_hesapla(100, 100), 0)
        self.assertEqual(portfolio.pozisyon_buyuklugu_hesapla(100, 101), 0)
        with self.assertRaises(ValueError):
            portfolio.pozisyon_buyuklugu_hesapla(float("nan"), 90)

    def test_safe_number_rejects_invalid_nested_raw_values(self):
        for value in ({"raw": "bad"}, {"raw": float("inf")}, float("nan"), True, None):
            self.assertIsNone(ind.guvenli_sayi(value))
        self.assertEqual(ind.guvenli_sayi({"raw": 7}), 7)
