from unittest.mock import patch

import numpy as np
import pandas as pd

from bot import config, scoring
from tests.helpers import OfflineTestCase


def score_frame():
    n = 20
    df = pd.DataFrame({
        "High": [101.] * n, "Low": [99.] * n, "Close": [98.] * (n-1) + [100.],
        "EMA20": [95.] * n, "EMA50": [90.] * n, "EMA200": [80.] * n,
        "SuperTrend_Yon": [1] * n, "ADX": [30.] * n, "Senkou_A": [85.] * n,
        "Senkou_B": [86.] * n, "Tenkan": [90.] * n, "Kijun": [89.] * n,
        "RSI": list(np.linspace(35, 50, n)), "MACD": [-1.] * (n-1) + [1.],
        "MACD_Sinyal": [0.] * n, "StochRSI_K": [10.] * (n-1) + [30.],
        "StochRSI_D": [20.] * n, "BB_Alt": [99.] * n, "OBV": list(range(n)),
        "Volume": [100.] * (n-5) + [300.] * 5, "Vol_20": [100.] * n,
        "MFI": [50.] * n, "CMF": [0.1] * n, "VWAP_Yaklasik": [99.] * n,
        "Donchian_Ust": [101.] * n, "Hist_Vol": [40.] * n,
    })
    return df


class ScoringTests(OfflineTestCase):
    def test_all_category_caps_with_maximum_conditions(self):
        df = score_frame()
        with patch("bot.scoring.higher_high_higher_low_mi", return_value=True):
            self.assertEqual(scoring.trend_puani_hesapla(df, 100, True, True)[0], 25)
        self.assertEqual(scoring.momentum_puani_hesapla(df, 100)[0], 20)
        self.assertEqual(scoring.hacim_puani_hesapla(df)[0], 15)
        self.assertEqual(scoring.volatilite_puani_hesapla(df, 100)[0], 10)
        self.assertEqual(scoring.temel_puani_hesapla(10, .5, 2, 8, .02)[0], 10)
        news = {"pozitif": True, "kap_kaynakli": True, "patron_aliyor": True, "kap_olay_puani": 10}
        self.assertEqual(scoring.haber_puani_hesapla(news)[0], 20)
        news.update(pozitif=False, kap_kaynakli=False, patron_aliyor=False, kap_olay_puani=-8)
        self.assertEqual(scoring.haber_puani_hesapla(news)[0], 0)

    def test_final_and_technical_score_bounds_and_denominator(self):
        self.assertEqual(scoring.toplam_skorlar(25, 20, 15, 10, 10, 20, 10), (100, 100))
        self.assertEqual(scoring.toplam_skorlar(0, 0, 0, 0, 0, 0, -10), (0, 0))
        self.assertEqual(scoring.toplam_skorlar(20, 10, 5, 5, 0, 8, 0), (48, 50))
        self.assertEqual(sum((config.TREND_MAX_PUAN, config.MOMENTUM_MAX_PUAN, config.HACIM_MAX_PUAN,
                             config.VOLATILITE_MAX_PUAN, config.TEMEL_MAX_PUAN, config.HABER_MAX_PUAN)), 100)
        with self.assertRaises(ValueError):
            scoring.toplam_skorlar(float("nan"), 0, 0, 0, 0, 0, 0)

    def test_support_resistance_priority_and_adjustments(self):
        self.assertEqual(scoring.destek_direnc_ayarlamasi(100, 99, 120)[0], 10)
        self.assertEqual(scoring.destek_direnc_ayarlamasi(100, 80, 101)[0], -10)
        self.assertEqual(scoring.destek_direnc_ayarlamasi(100, 99, 101)[0], -10)
        self.assertEqual(scoring.destek_direnc_ayarlamasi(100, 80, 120)[0], 0)
        with self.assertRaises(ValueError):
            scoring.destek_direnc_ayarlamasi(0, 1, 2)

    def test_classification_boundaries(self):
        for value, expected in ((0, "RISKY"), (3, "RISKY"), (4, "WATCHLIST"), (5, "WATCHLIST"),
                                (6, "EARLY"), (7, "EARLY"), (8, "LONG"), (10, "LONG")):
            self.assertIn(expected, scoring.siniflandirma_etiketi(value))

    def test_missing_fundamentals_do_not_earn_points(self):
        self.assertEqual(scoring.temel_puani_hesapla(None, None, None, 8, None)[0], 0)
        self.assertEqual(scoring.temel_puani_hesapla(float("nan"), None, None, None, float("inf"))[0], 0)

    def test_hold_score_bounds(self):
        state = {"giris_fiyati": 100, "guncel_stop": 85, "tp2": 130}
        for negative, positive in ((True, False), (False, True), (False, False)):
            value, _ = scoring.tut_azalt_cik_skoru_hesapla(score_frame(), 100, state, negative, positive)
            self.assertGreaterEqual(value, 0)
            self.assertLessEqual(value, 100)
