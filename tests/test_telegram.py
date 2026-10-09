import os
from pathlib import Path
from unittest.mock import patch

import requests

from bot import config, market_data, storage, telegram_api, telegram_bot
from tests.helpers import OfflineTestCase, chart_payload, position_state, response


class CommandTests(OfflineTestCase):
    def setUp(self):
        super().setUp()
        with patch("bot.market_data.session.get", return_value=response(chart_payload(120))):
            self.df = market_data.tek_hisse_veri_getir("ASELS.IS")
        market = patch("bot.telegram_bot.tek_hisse_veri_getir", return_value=self.df)
        self.fetch = market.start()
        self.addCleanup(market.stop)

    def test_al_opens_persistent_position(self):
        reply = telegram_bot.komut_al(["ASELS", "132,40", "500"])
        self.assertIn("Pozisyon Eklendi", reply)
        poz = storage.pozisyon_takip_yukle()["acik"][0]
        self.assertEqual((poz["hisse"], poz["giris_fiyati"], poz["adet"]), ("ASELS.IS", 132.4, 500))
        self.assertAlmostEqual(poz["stop"], 132.4 - 1.5 * self.df["ATR"].iloc[-1])
        self.assertIn("zaten açık", telegram_bot.komut_al(["ASELS", "132.40"]))

    def test_sat_closes_at_observed_price_and_pnl(self):
        storage.pozisyon_takip_kaydet(position_state())
        reply = telegram_bot.komut_sat(["ASELS"])
        self.assertIn("kapatıldı", reply)
        state = storage.pozisyon_takip_yukle()
        self.assertEqual(state["acik"], [])
        poz = state["kapanan"][0]
        price = self.df["Close"].iloc[-1]
        self.assertEqual(poz["kapanis_fiyati"], price)
        self.assertAlmostEqual(poz["pnl_yuzde"], round((price-100)/100*100, 2))

    def test_failed_sat_keeps_open_position(self):
        storage.pozisyon_takip_kaydet(position_state())
        before = Path(config.POZISYON_TAKIP_DOSYA).read_bytes()
        self.fetch.return_value = None
        self.assertIn("kapatılmadı", telegram_bot.komut_sat(["ASELS"]))
        self.assertEqual(Path(config.POZISYON_TAKIP_DOSYA).read_bytes(), before)

    def test_invalid_input_does_not_fetch_or_write(self):
        for args in ([], ["ASELS"], ["ASELS", "bad"], ["../bad", "100"], ["ASELS", "0"],
                     ["ASELS", "-1"], ["ASELS", "nan"], ["ASELS", "inf"], ["ASELS", "100", "0"],
                     ["ASELS", "100", "nan"], ["ASELS", "100", "-1"], ["ASELS", "100", "bad"]):
            with self.subTest(args=args):
                reply = telegram_bot.komut_al(args)
                self.assertTrue("Geçersiz" in reply or "Kullanım" in reply)
        self.assertIn("Geçersiz", telegram_bot.komut_sat(["../../bad"]))
        self.assertIn("Kullanım", telegram_bot.komut_sat([]))
        self.fetch.assert_not_called()
        self.assertFalse(Path(config.POZISYON_TAKIP_DOSYA).exists())

    def test_unauthorized_chat_is_ignored_at_dispatch(self):
        with patch("bot.telegram_bot.komut_al") as buy, patch("bot.telegram_bot.basit_mesaj_gonder") as send:
            telegram_bot.komut_isle({"chat": {"id": 999}, "text": "/al ASELS 100"})
        buy.assert_not_called()
        send.assert_not_called()

    def test_authorized_al_sat_and_bot_command_suffix(self):
        with patch("bot.telegram_bot.basit_mesaj_gonder", return_value=True) as send:
            telegram_bot.komut_isle({"chat": {"id": 123}, "text": "/al@some_bot ASELS 100 10"})
            self.assertEqual(len(storage.pozisyon_takip_yukle()["acik"]), 1)
            telegram_bot.komut_isle({"chat": {"id": 123}, "text": "/sat ASELS"})
        self.assertEqual(send.call_count, 2)
        self.assertEqual(len(storage.pozisyon_takip_yukle()["kapanan"]), 1)

    def test_storage_failure_does_not_reply_success(self):
        with patch("bot.storage.os.replace", side_effect=OSError("mock disk failure")), patch("bot.telegram_bot.basit_mesaj_gonder", return_value=True) as send, self.assertLogs("borsa_bot", level="ERROR"):
            telegram_bot.komut_isle({"chat": {"id": 123}, "text": "/al ASELS 100"})
        self.assertIn("Komut tamamlanamadı", send.call_args.args[0])
        self.assertFalse(Path(config.POZISYON_TAKIP_DOSYA).exists())

    def test_malformed_nontext_messages_ignored(self):
        with patch("bot.telegram_bot.basit_mesaj_gonder") as send:
            for message in ({}, {"chat": None}, {"chat": {"id": 123}, "text": None}):
                telegram_bot.komut_isle(message)
        send.assert_not_called()


class TransportTests(OfflineTestCase):
    def test_send_requires_http_and_api_success(self):
        with patch("bot.telegram_api.session.post", return_value=response({"ok": True, "result": {"message_id": 1}})):
            self.assertTrue(telegram_api.basit_mesaj_gonder("hello"))
        for payload in ({"ok": False}, {"ok": True}, {"ok": True, "result": []}, []):
            config._api_warning_times.clear()
            with patch("bot.telegram_api.session.post", return_value=response(payload)), self.assertLogs("borsa_bot", level="WARNING"):
                self.assertFalse(telegram_api.basit_mesaj_gonder("hello"))

    def test_polling_rejects_invalid_api_structures(self):
        for payload in ({"ok": False}, {"ok": True, "result": None}, {"ok": True, "result": [{}]},
                        {"ok": True, "result": [{"update_id": 1, "message": "bad"}]}):
            with patch("bot.telegram_api.requests.get", return_value=response(payload)), self.assertRaises(telegram_api.TelegramError):
                telegram_api.telegram_guncellemelerini_al(0)
        with patch("bot.telegram_api.requests.get", return_value=response(status=429)), self.assertRaises(telegram_api.TelegramError):
            telegram_api.telegram_guncellemelerini_al(0)

    def test_polling_success_timeout_policy(self):
        payload = {"ok": True, "result": [{"update_id": 4, "message": {"chat": {"id": 123}, "text": "/help"}}]}
        with patch("bot.telegram_api.requests.get", return_value=response(payload)) as get:
            self.assertEqual(telegram_api.telegram_guncellemelerini_al(3), payload["result"])
        self.assertEqual(get.call_args.kwargs["timeout"], (10, 30))

    def test_secret_is_not_logged_or_exposed_by_poll_errors(self):
        token = os.environ["TELEGRAM_TOKEN"]
        exception = requests.ConnectionError("failed https://api.telegram.org/bot" + token + "/getUpdates")
        with patch("bot.telegram_api.session.post", side_effect=exception), self.assertLogs("borsa_bot", level="WARNING") as logs:
            self.assertFalse(telegram_api.basit_mesaj_gonder("hello"))
        self.assertNotIn(token, " ".join(logs.output))
        with patch("bot.telegram_api.requests.get", side_effect=exception), self.assertRaises(telegram_api.TelegramError) as caught:
            telegram_api.telegram_guncellemelerini_al(0)
        self.assertNotIn(token, str(caught.exception))
