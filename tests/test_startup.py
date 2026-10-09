import logging
import os
import threading
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import schedule

from bot import config, main, scheduler, storage
from tests.helpers import OfflineTestCase, chart_payload, position_state, response
from tests.test_news import rss


class StartupTests(OfflineTestCase):
    def test_missing_environment_fails_before_network_and_logging(self):
        with patch.dict(os.environ, {}, clear=True), patch("bot.main.configure_logging") as logging_setup, patch("builtins.print") as output:
            self.assertEqual(main.main(), 1)
        logging_setup.assert_not_called()
        message = output.call_args.args[0]
        self.assertIn("TELEGRAM_TOKEN", message)
        self.assertIn("TELEGRAM_CHAT_ID", message)

    def test_invalid_chat_id_and_placeholder_rejected(self):
        for change in ({"TELEGRAM_CHAT_ID": "bad"}, {"TELEGRAM_TOKEN": "replace_with_new_bot_token"}):
            with patch.dict(os.environ, change), self.assertRaises(config.ConfigurationError):
                config.telegram_credentials()

    def test_corrupt_state_fails_startup_without_reset_or_network(self):
        Path("pozisyon_takip.json").write_text("corrupt", encoding="utf-8")
        with patch("bot.main.configure_logging"), self.assertLogs("borsa_bot", level="ERROR"):
            self.assertEqual(main.main(), 1)
        self.assertEqual(Path("pozisyon_takip.json").read_text(encoding="utf-8"), "corrupt")

    def test_mocked_startup_news_scan_signal_jobs_and_listener(self):
        stop = threading.Event()
        calls = []

        def get(url, **kwargs):
            calls.append(url)
            if "news.google.com" in url:
                return response(text=rss("Şirket geri alım - KAP"))
            if "quoteSummary" in url:
                return response({"quoteSummary": {"result": [{"summaryDetail": {}, "defaultKeyStatistics": {}}]}})
            return response(chart_payload())

        def listener(stop_event):
            stop_event.set()

        with patch("bot.main.configure_logging"), patch("bot.main.telegram_komut_dinleyicisi_baslat", side_effect=listener), patch("bot.news.hisseler", ["ASELS.IS"]), patch("bot.scheduler.hisseler", ["ASELS.IS"]), patch("bot.main.piyasa_acik_mi", return_value=True), patch("bot.scheduler.piyasa_acik_mi", return_value=True), patch("bot.http_client.session.get", side_effect=get), patch("bot.http_client.session.post", return_value=response({"ok": True, "result": {"message_id": 1}})) as post, patch("bot.news.time.sleep"):
            self.assertEqual(main.main(stop), 0)
        self.assertTrue(stop.is_set())
        self.assertTrue(Path(config.HABER_CACHE_DOSYA).exists())
        self.assertIn("ASELS.IS", storage.son_sinyalleri_yukle())
        self.assertEqual(storage.pozisyon_takip_yukle(), {"acik": [], "kapanan": []})
        self.assertEqual(len(calls), 3)
        post.assert_called_once()

    def test_market_open_startup_runs_scans_before_listener_and_scheduler_loop(self):
        stop = threading.Event()
        events = []
        jobs = schedule.Scheduler()

        def pending():
            events.append("scheduled operation")
            stop.set()

        with patch("bot.main.configure_logging"), patch("bot.main.piyasa_acik_mi", return_value=True), patch("bot.main.toplu_haber_taramasi_yap", side_effect=lambda: events.append("news")), patch("bot.main.ana_tarama", side_effect=lambda: events.append("technical")), patch("bot.main.schedule.Scheduler", return_value=jobs), patch.object(jobs, "run_pending", side_effect=pending), patch("bot.main.threading.Thread") as listener_thread:
            listener_thread.return_value.start.side_effect = lambda: events.append("listener")
            self.assertEqual(main.main(stop), 0)

        self.assertEqual(events, ["news", "technical", "listener", "scheduled operation"])
        self.assertEqual(len(jobs.jobs), 7)
        listener_thread.assert_called_once_with(target=main.telegram_komut_dinleyicisi_baslat, args=(stop,), daemon=True)
        listener_thread.return_value.start.assert_called_once()

    def test_market_closed_startup_skips_scans_but_starts_listener_and_scheduler(self):
        stop = threading.Event()
        jobs = schedule.Scheduler()

        with patch("bot.main.configure_logging"), patch("bot.main.piyasa_acik_mi", return_value=False), patch("bot.main.toplu_haber_taramasi_yap") as news_scan, patch("bot.main.ana_tarama") as technical_scan, patch("bot.main.schedule.Scheduler", return_value=jobs), patch.object(jobs, "run_pending", side_effect=stop.set) as pending, patch("bot.main.threading.Thread") as listener_thread, self.assertLogs("borsa_bot", level="INFO") as logs:
            self.assertEqual(main.main(stop), 0)

        news_scan.assert_not_called()
        technical_scan.assert_not_called()
        listener_thread.assert_called_once_with(target=main.telegram_komut_dinleyicisi_baslat, args=(stop,), daemon=True)
        listener_thread.return_value.start.assert_called_once()
        pending.assert_called_once()
        self.assertEqual(len(jobs.jobs), 7)
        self.assertIn("Market closed; skipping initial news and technical scans. Telegram commands remain active.", "\n".join(logs.output))
        self.assertFalse(Path(config.HABER_CACHE_DOSYA).exists())
        self.assertFalse(Path(config.POZISYON_TAKIP_DOSYA).exists())

    def test_schedule_preserves_frequencies_and_istanbul_wall_times(self):
        jobs = schedule.Scheduler()
        main.configure_jobs(jobs)
        self.assertEqual(len(jobs.jobs), 7)
        self.assertEqual([(job.interval, job.unit) for job in jobs.jobs if job.at_time is None], [(15, "minutes"), (3, "hours")])
        daily = [job for job in jobs.jobs if job.at_time]
        self.assertEqual([job.at_time.strftime("%H:%M") for job in daily], ["09:15", "13:30", "17:45", "18:10", "18:15"])
        self.assertTrue(all(str(job.at_time_zone) == "Europe/Istanbul" for job in daily))

    def test_scheduled_failure_is_reported_without_killing_loop(self):
        def job():
            raise storage.StorageError("test state failure")
        with self.assertLogs("borsa_bot", level="ERROR"):
            main.run_job(job)

    def test_legacy_cooldown_date_is_timezone_safe(self):
        now = datetime.now(config.TR_TZ)
        self.assertTrue(storage.cooldown_da_mi("ASELS.IS", {"ASELS.IS": now.replace(tzinfo=None).isoformat()}))
        self.assertFalse(storage.cooldown_da_mi("ASELS.IS", {"ASELS.IS": (now-timedelta(hours=5)).isoformat()}))

    def test_failed_daily_send_does_not_mark_summary_done(self):
        state = position_state()
        poz = state["acik"].pop()
        poz.update(pnl_yuzde=5, kapanis_fiyati=105, kapanis_tarihi=datetime.now(config.TR_TZ).isoformat(), sonuc="TEST")
        state["kapanan"].append(poz)
        storage.pozisyon_takip_kaydet(state)
        with patch("bot.scheduler.basit_mesaj_gonder", return_value=False):
            scheduler.gunluk_performans_ozetini_gonder_gerekirse(state)
        self.assertFalse(Path(config.PERFORMANS_OZET_DOSYA).exists())
        with patch("bot.scheduler.hisseler", ["ASELS.IS"]), patch("bot.scheduler.gunluk_fiyat_degisimini_getir", return_value=("ASELS.IS", 100, 2)), patch("bot.scheduler.basit_mesaj_gonder", return_value=False):
            scheduler.gun_sonu_piyasa_ozeti_gonder()
        self.assertFalse(Path(config.PIYASA_OZET_DOSYA).exists())
        storage.pozisyon_takip_kaydet(position_state())
        with patch("bot.scheduler.tek_hisse_veri_getir", return_value=None), patch("bot.scheduler.basit_mesaj_gonder", return_value=False):
            scheduler.gun_sonu_pozisyon_ozeti_gonder()
        self.assertFalse(Path(config.POZISYON_OZET_DOSYA).exists())

    def test_log_filter_masks_credentials(self):
        token = os.environ["TELEGRAM_TOKEN"]
        record = logging.LogRecord("test", logging.WARNING, "", 0, "request %s", ("https://api.telegram.org/bot" + token + "/sendMessage",), None)
        config.SecretFilter().filter(record)
        self.assertNotIn(token, record.getMessage())
        self.assertIn("[REDACTED]", record.getMessage())

    def test_overlapping_scan_is_skipped(self):
        config.tarama_kilidi.acquire()
        try:
            with patch("bot.scheduler._ana_tarama") as scan:
                scheduler.ana_tarama()
            scan.assert_not_called()
        finally:
            config.tarama_kilidi.release()

    def test_repeated_api_failures_are_rate_limited(self):
        with patch("bot.config.time.monotonic", side_effect=[0, 1, 301]), patch("bot.config.log.warning") as warning, patch("bot.config.log.debug") as debug:
            for _ in range(3):
                config.api_warning("test", ValueError(), "API failure")
        self.assertEqual(warning.call_count, 2)
        self.assertEqual(debug.call_count, 1)
