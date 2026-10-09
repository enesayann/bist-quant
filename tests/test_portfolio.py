import threading
import time
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from bot import portfolio
from tests.helpers import OfflineTestCase, candle, position_state
from tests.test_scoring import score_frame


class PortfolioTests(OfflineTestCase):
    def setUp(self):
        super().setUp()
        send = patch("bot.portfolio.basit_mesaj_gonder", return_value=True)
        send.start()
        self.addCleanup(send.stop)
        alerts = patch("bot.portfolio._acik_pozisyon_ek_kontroller")
        alerts.start()
        self.addCleanup(alerts.stop)
        self.state = position_state()

    def test_open_position_fields_and_no_duplicates(self):
        poz = self.state["acik"][0]
        self.assertEqual((poz["giris_fiyati"], poz["guncel_stop"], poz["adet"]), (100, 85, 10))
        self.assertFalse(poz["tp1_vuruldu"])
        with self.assertRaises(ValueError):
            portfolio.pozisyon_ac("ASELS.IS", 100, 85, 120, 130, 10, "TEST", self.state)

    def test_tp1_moves_stop_to_break_even_without_partial_sale(self):
        portfolio.pozisyon_kontrol_et("ASELS.IS", candle(high=121), self.state)
        poz = self.state["acik"][0]
        self.assertTrue(poz["tp1_vuruldu"])
        self.assertEqual(poz["guncel_stop"], 100)
        self.assertEqual(poz["adet"], 10)
        self.assertEqual(self.state["kapanan"], [])

    def test_tp2_exit_and_pnl(self):
        portfolio.pozisyon_kontrol_et("ASELS.IS", candle(high=131), self.state)
        poz = self.state["kapanan"][0]
        self.assertEqual((poz["sonuc"], poz["kapanis_fiyati"], poz["pnl_yuzde"]), ("WIN TP2", 130, 30))
        self.assertEqual(self.state["acik"], [])
        self.assertIn("+300 TL", portfolio.kar_zarar_tl_metni(poz, 130))

    def test_initial_stop(self):
        portfolio.pozisyon_kontrol_et("ASELS.IS", candle(high=100, low=80, close=90), self.state)
        poz = self.state["kapanan"][0]
        self.assertEqual((poz["sonuc"], poz["kapanis_fiyati"], poz["pnl_yuzde"]), ("LOSS", 85, -15))

    def test_same_candle_stop_and_target_preserves_stop_first_assumption(self):
        portfolio.pozisyon_kontrol_et("ASELS.IS", candle(high=140, low=80, close=105), self.state)
        self.assertEqual(self.state["kapanan"][0]["sonuc"], "LOSS")

    def test_trailing_stop_only_moves_up(self):
        portfolio.pozisyon_kontrol_et("ASELS.IS", candle(high=111, low=109, close=110, atr=3), self.state)
        self.assertEqual(self.state["acik"][0]["guncel_stop"], 105.5)
        portfolio.pozisyon_kontrol_et("ASELS.IS", candle(high=110, low=107, close=108, atr=10), self.state)
        self.assertEqual(self.state["acik"][0]["guncel_stop"], 105.5)

    def test_tp1_followed_by_trailing_stop_uses_actual_stop_for_pnl(self):
        portfolio.pozisyon_kontrol_et("ASELS.IS", candle(high=121), self.state)
        portfolio.pozisyon_kontrol_et("ASELS.IS", candle(high=127, low=124, close=125, atr=5), self.state)
        portfolio.pozisyon_kontrol_et("ASELS.IS", candle(high=123, low=117, close=120, atr=5), self.state)
        poz = self.state["kapanan"][0]
        self.assertEqual(poz["kapanis_fiyati"], 117.5)
        self.assertEqual(poz["pnl_yuzde"], 17.5)
        self.assertIn("WIN TP1", poz["sonuc"])

    def test_break_even_is_not_a_profitable_win(self):
        portfolio.pozisyon_kontrol_et("ASELS.IS", candle(high=121), self.state)
        portfolio.pozisyon_kontrol_et("ASELS.IS", candle(high=106, low=99, close=104), self.state)
        poz = self.state["kapanan"][0]
        self.assertEqual((poz["sonuc"], poz["pnl_yuzde"]), ("BREAK EVEN", 0))
        self.assertEqual(portfolio.performans_istatistikleri_hesapla([poz])["win_rate_yuzde"], 0)

    def test_profitable_trailing_stop_before_tp1_is_not_loss(self):
        portfolio.pozisyon_kontrol_et("ASELS.IS", candle(high=111, low=109, close=110, atr=3), self.state)
        portfolio.pozisyon_kontrol_et("ASELS.IS", candle(high=110, low=105, close=108, atr=3), self.state)
        self.assertEqual(self.state["kapanan"][0]["sonuc"], "WIN TRAILING STOP")

    def test_trailing_update_precedes_same_daily_candle_low(self):
        portfolio.pozisyon_kontrol_et("ASELS.IS", candle(high=112, low=100, close=110, atr=3), self.state)
        self.assertEqual(self.state["kapanan"][0]["kapanis_fiyati"], 105.5)

    def test_daily_candle_can_contain_low_before_manual_entry(self):
        # Existing implementation uses the whole latest candle without entry-time filtering.
        portfolio.pozisyon_kontrol_et("ASELS.IS", candle(high=110, low=80, close=100), self.state)
        self.assertEqual(self.state["kapanan"][0]["sonuc"], "LOSS")

    def test_statistics_zero_profit_factor_and_initial_drawdown(self):
        result = portfolio.performans_istatistikleri_hesapla([{"pnl_yuzde": -5}, {"pnl_yuzde": -2}])
        self.assertEqual(result["profit_factor"], 0)
        self.assertEqual(result["maksimum_drawdown_yuzde"], -7)
        result = portfolio.performans_istatistikleri_hesapla([{"pnl_yuzde": 10}, {"pnl_yuzde": -5}])
        self.assertEqual(result["profit_factor"], 2)
        self.assertEqual(result["expectancy_yuzde"], 2.5)

    def test_workers_cannot_lose_each_others_position_changes(self):
        portfolio.pozisyon_ac("THYAO.IS", 100, 85, 120, 130, 10, "TEST", self.state)
        gate = threading.Barrier(2)
        original = portfolio._pozisyon_kontrol_et
        running, maximum = 0, 0

        def transition(*args):
            nonlocal running, maximum
            running += 1
            maximum = max(maximum, running)
            time.sleep(.02)
            original(*args)
            running -= 1

        def worker(symbol):
            gate.wait(timeout=5)
            portfolio.pozisyon_kontrol_et(symbol, candle(high=131), self.state)

        with patch("bot.portfolio._pozisyon_kontrol_et", side_effect=transition), ThreadPoolExecutor(max_workers=2) as executor:
            list(executor.map(worker, ["ASELS.IS", "THYAO.IS"]))
        self.assertEqual(maximum, 1)
        self.assertEqual(self.state["acik"], [])
        self.assertEqual({p["hisse"] for p in self.state["kapanan"]}, {"ASELS.IS", "THYAO.IS"})


class AlertTests(OfflineTestCase):
    def test_failed_send_does_not_start_alert_cooldown(self):
        poz = position_state()["acik"][0]
        with patch("bot.portfolio.acik_pozisyon_negatif_haber_kontrol", return_value={"negatif": True, "baslik": "ceza", "kullanilabilir": True}), patch("bot.portfolio.basit_mesaj_gonder", return_value=False) as send:
            portfolio._acik_pozisyon_ek_kontroller("ASELS.IS", score_frame(), poz, 100)
        self.assertGreater(send.call_count, 0)
        self.assertEqual(poz["son_uyarilar"], {})
