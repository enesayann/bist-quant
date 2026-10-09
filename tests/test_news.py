from datetime import datetime, timedelta
from email.utils import format_datetime
from pathlib import Path
from unittest.mock import patch
import xml.etree.ElementTree as ET

from bot import config, news, storage
from tests.helpers import OfflineTestCase, response


def rss(title="Şirket ihale kazandı - KAP", when=None):
    when = when or datetime.now(config.TR_TZ)
    return f"<rss><channel><item><title>{title}</title><pubDate>{format_datetime(when)}</pubDate></item></channel></rss>"


class NewsTests(OfflineTestCase):
    def test_positive_headline(self):
        positive, negative = news.kelime_skorunu_hesapla("şirket ihale kazandı")
        self.assertGreater(positive, negative)

    def test_negative_headline(self):
        positive, negative = news.kelime_skorunu_hesapla("şirkete ceza ve soruşturma")
        self.assertGreater(negative, positive)

    def test_negated_positive_phrase(self):
        positive, negative = news.kelime_skorunu_hesapla("ihale gerçekleşmedi")
        self.assertEqual((positive, negative), (0, 1))
        self.assertEqual(news.kap_olay_tipi_puani("geri alım yapılmadı değil"), 0)
        for title in ("ihale onay değildir", "ihale yoktur", "ihale yoktu"):
            positive, negative = news.kelime_skorunu_hesapla(title)
            self.assertGreater(negative, positive)
        self.assertFalse(news._negasyonlu_mu("ihale yoksulluk haberi", 0, 5))

    def test_reduced_loss_variants(self):
        for title in ("zarar azaldı", "zararı azaldı", "kaybı azaldı", "zarar düştü"):
            with self.subTest(title=title):
                positive, negative = news.kelime_skorunu_hesapla(title)
                self.assertGreater(positive, negative)
                self.assertEqual(negative, 0)

    def test_kap_source_detection(self):
        self.assertTrue(news.kap_kaynakli_mi("Şirket geri alım - KAP"))
        self.assertFalse(news.kap_kaynakli_mi("KAP haberi - Gazete"))
        self.assertEqual(news.kap_olay_tipi_puani("geri alım ve pay alım"), 10)

    def test_rss_date_uses_istanbul_day(self):
        now = datetime.now(config.TR_TZ)
        today = ET.fromstring(rss(when=now)).find(".//item")
        yesterday = ET.fromstring(rss(when=now-timedelta(days=1))).find(".//item")
        self.assertTrue(news.haber_bugune_mi_ait(today))
        self.assertFalse(news.haber_bugune_mi_ait(yesterday))
        with self.assertLogs("borsa_bot", level="WARNING"):
            self.assertFalse(news.haber_bugune_mi_ait(ET.fromstring("<item><pubDate>bad</pubDate></item>")))

    def test_seen_news_retention_and_legacy_naive_dates(self):
        now = datetime.now(config.TR_TZ)
        storage._json_kaydet(config.GORULMUS_HABERLER_DOSYA,
                            {"new": now.isoformat(), "old": (now-timedelta(days=8)).isoformat(),
                             "legacy": now.replace(tzinfo=None).isoformat()})
        self.assertEqual(set(news.gorulmus_haberleri_yukle()), {"new", "legacy"})

    def test_bulk_scan_deduplicates_and_cached_reader_never_uses_network(self):
        with patch("bot.news.hisseler", ["ASELS.IS"]), patch("bot.news.time.sleep"), patch("bot.news.session.get", return_value=response(text=rss())) as get:
            news.toplu_haber_taramasi_yap()
            first = Path(config.HABER_CACHE_DOSYA).read_text(encoding="utf-8")
            news.toplu_haber_taramasi_yap()
            self.assertEqual(Path(config.HABER_CACHE_DOSYA).read_text(encoding="utf-8"), first)
            self.assertEqual(get.call_count, 2)
        result = news.haber_duyarlilik_kontrol("ASELS.IS")
        self.assertTrue(result["pozitif"])
        self.assertTrue(result["kap_kaynakli"])
        self.assertEqual(len(news.gorulmus_haberleri_yukle()), 1)

    def test_yesterday_cache_expires(self):
        storage._json_kaydet(config.HABER_CACHE_DOSYA, {"ASELS.IS": {
            "tarih": (datetime.now(config.TR_TZ)-timedelta(days=1)).date().isoformat(), "pozitif": True,
            "baslik": "old", "patron_aliyor": False, "kap_kaynakli": False, "kap_olay_puani": 0}})
        self.assertFalse(news.haber_duyarlilik_kontrol("ASELS.IS")["pozitif"])

    def test_failed_live_news_is_unknown_not_no_news(self):
        for fake in (response(text="malformed"), response(text="<html/>"), response(status=429)):
            config._api_warning_times.clear()
            with patch("bot.news.session.get", return_value=fake), self.assertLogs("borsa_bot", level="WARNING"):
                self.assertFalse(news.acik_pozisyon_negatif_haber_kontrol("ASELS.IS")["kullanilabilir"])

    def test_negative_live_news(self):
        with patch("bot.news.session.get", return_value=response(text=rss("Şirkete ceza - KAP"))):
            result = news.acik_pozisyon_negatif_haber_kontrol("ASELS.IS")
        self.assertTrue(result["negatif"])
        self.assertTrue(result["kullanilabilir"])
