from unittest.mock import patch

from bot import config, market_data
from tests.helpers import OfflineTestCase, chart_payload, response


class MarketTests(OfflineTestCase):
    def test_yahoo_success(self):
        with patch("bot.market_data.session.get", return_value=response(chart_payload(60))):
            df = market_data.tek_hisse_veri_getir("ASELS.IS")
        self.assertEqual(len(df), 60)
        self.assertTrue({"EMA20", "EMA50", "RSI", "ATR", "ADX", "MACD", "OBV", "Vol_20"}.issubset(df.columns))

    def test_empty_missing_null_and_mismatched_arrays(self):
        invalid = [{}, {"chart": {"result": []}}, {"chart": {"result": None}}, {"chart": []}]
        for change in (lambda quote: quote.update(close=None), lambda quote: quote.update(close=[]),
                       lambda quote: quote.update(close=[None]*60), lambda quote: quote.update(close=[float("nan")]*60)):
            payload = chart_payload(60)
            change(payload["chart"]["result"][0]["indicators"]["quote"][0])
            invalid.append(payload)
        for payload in invalid:
            config._api_warning_times.clear()
            with self.subTest(payload_type=type(payload).__name__), patch("bot.market_data.session.get", return_value=response(payload)), self.assertLogs("borsa_bot", level="WARNING"):
                self.assertIsNone(market_data.tek_hisse_veri_getir("ASELS.IS"))

    def test_some_null_rows_are_dropped_like_original(self):
        payload = chart_payload(60)
        payload["chart"]["result"][0]["indicators"]["quote"][0]["close"][0] = None
        _, df = market_data.chart_frame(payload)
        self.assertEqual(len(df), 59)

    def test_zero_close_cannot_divide_daily_change_by_zero(self):
        payload = chart_payload(5)
        payload["chart"]["result"][0]["indicators"]["quote"][0]["close"][-2] = 0
        with patch("bot.market_data.session.get", return_value=response(payload)), patch("bot.market_data.time.sleep"), self.assertLogs("borsa_bot", level="WARNING"):
            self.assertIsNone(market_data.gunluk_fiyat_degisimini_getir("ASELS.IS"))

    def test_fundamentals_missing_pe_does_not_fabricate_comparison(self):
        payload = {"quoteSummary": {"result": [{"summaryDetail": {"forwardPE": {"raw": 8}}, "defaultKeyStatistics": {}}]}}
        with patch("bot.market_data.session.get", return_value=response(payload)):
            self.assertEqual(market_data.temel_verileri_getir("ASELS.IS"), (None, None, None, 8, None))

    def test_fundamental_failure_is_visible_with_neutral_missing_values(self):
        with patch("bot.market_data.session.get", return_value=response({"quoteSummary": {"result": []}})), self.assertLogs("borsa_bot", level="WARNING"):
            self.assertEqual(market_data.temel_verileri_getir("ASELS.IS"), (None,)*5)
