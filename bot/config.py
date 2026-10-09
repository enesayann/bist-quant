"""Original strategy constants and process configuration."""
import os
import re
import logging
import threading
import time
from datetime import datetime
from zoneinfo import ZoneInfo

log = logging.getLogger("borsa_bot")


class ConfigurationError(ValueError):
    """Required runtime configuration is missing or invalid."""


def telegram_credentials() -> tuple[str, str]:
    token = os.environ.get("TELEGRAM_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    missing = [name for name, value in (("TELEGRAM_TOKEN", token),
                                       ("TELEGRAM_CHAT_ID", chat_id)) if not value]
    if missing:
        raise ConfigurationError("Required environment variables missing: " + ", ".join(missing))
    if token == "replace_with_new_bot_token" or chat_id == "replace_with_authorized_chat_id":
        raise ConfigurationError("Replace the .env.example placeholders in your environment")
    if not re.fullmatch(r"-?\d+", chat_id):
        raise ConfigurationError("TELEGRAM_CHAT_ID must be a numeric chat ID")
    return token, chat_id


class SecretFilter(logging.Filter):
    """Redact credentials even when a library logs an HTTP URL."""

    def filter(self, record):
        message = record.getMessage()
        for name in ("TELEGRAM_TOKEN", "TELEGRAM_CHAT_ID"):
            secret = os.environ.get(name)
            if secret:
                message = message.replace(secret, "[REDACTED]")
        message = re.sub(r"(?i)(api\.telegram\.org/bot)[^/\s]+", r"\1[REDACTED]", message)
        message = re.sub(r"\b\d{6,}:[A-Za-z0-9_-]{20,}\b", "[REDACTED]", message)
        record.msg, record.args = message, ()
        return True


def configure_logging() -> None:
    handlers = [logging.FileHandler("borsa_bot.log", encoding="utf-8"), logging.StreamHandler()]
    for handler in handlers:
        handler.addFilter(SecretFilter())
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                        handlers=handlers, force=True)
    logging.getLogger("urllib3").setLevel(logging.WARNING)


def istanbul_datetime(value: str) -> datetime:
    """Legacy naive timestamps are interpreted as Istanbul local time."""
    result = datetime.fromisoformat(value)
    return result.replace(tzinfo=TR_TZ) if result.tzinfo is None else result.astimezone(TR_TZ)


_api_warning_times = {}
_api_warning_lock = threading.Lock()


def api_warning(service, error, message, *args):
    """One warning per service/error every five minutes; individual failures at DEBUG."""
    key = (service, type(error).__name__)
    now = time.monotonic()
    with _api_warning_lock:
        previous = _api_warning_times.get(key)
        show = previous is None or now - previous >= 300
        if show:
            _api_warning_times[key] = now
    if show:
        log.warning(message + " (similar failures suppressed for 5 minutes)", *args)
    else:
        log.debug(message, *args)

TR_TZ = ZoneInfo("Europe/Istanbul")


COOLDOWN_SAAT = 4


COOLDOWN_DOSYA = "son_sinyaller.json"


POZISYON_TAKIP_DOSYA = "pozisyon_takip.json"


PERFORMANS_OZET_DOSYA = "son_performans_ozeti.json"


POZISYON_OZET_DOSYA = "son_pozisyon_ozeti.json"


TELEGRAM_OFFSET_DOSYA = "telegram_offset.json"


GORULMUS_HABERLER_DOSYA = "gorulmus_haberler.json"


HABER_CACHE_DOSYA = "haber_cache.json"  # <-- YENİ EKLENEN ÖNBELLEK DOSYAMIZ


pozisyon_kilidi = threading.Lock()

# Scan workers need their own lock: the coordinator holds pozisyon_kilidi.
tarama_durum_kilidi = threading.RLock()
tarama_kilidi = threading.Lock()
haber_kilidi = threading.Lock()


UYARI_COOLDOWN_SAAT = 4


GORULMUS_HABER_SAKLAMA_GUNU = 7


MIN_GUVEN_SKORU = 7


PIYASA_ACILIS = (9, 30)


PIYASA_KAPANIS = (18, 10)


PORTFOY_BUYUKLUGU_TL = 100_000.0


MAKS_RISK_YUZDESI = 0.01


YAHOO_VERI_ARALIGI = "2y"


MIN_VERI_UZUNLUGU = 60


EMA200_ICIN_MIN_VERI = 200


ICHIMOKU_ICIN_MIN_VERI = 78


PIVOT_PENCERE = 5


DESTEK_DIRENC_LOOKBACK = 60


DESTEK_DIRENC_YUZDE = 0.02


ATR_PERIYODU = 14


TREND_MAX_PUAN = 25


MOMENTUM_MAX_PUAN = 20


HACIM_MAX_PUAN = 15


VOLATILITE_MAX_PUAN = 10


TEMEL_MAX_PUAN = 10


HABER_MAX_PUAN = 20


DESTEK_DIRENC_MAX_AYAR = 10


EMA_TAM_DIZILIM_PUAN = 10


EMA_KISMI_DIZILIM_PUAN = 5


SUPERTREND_YUKARI_PUAN = 7


ADX_GUCLU_TREND_PUAN = 5


ADX_ESIK = 25


HH_HL_YAPI_PUAN = 3


ICHIMOKU_BULUT_USTU_PUAN = 5


RSI_SAGLIKLI_BANT_PUAN = 4


RSI_YUKSELEN_YON_PUAN = 4


MACD_TAZE_KESISIM_PUAN = 5


MACD_DEVAM_BULLISH_PUAN = 2


STOCH_RSI_DONUS_PUAN = 4


BOLLINGER_ALT_BANT_DONUS_PUAN = 3


OBV_YUKSELEN_TREND_PUAN = 3


HACIM_PATLAMASI_PUAN = 3


HACIM_PATLAMASI_CARPANI = 1.5


SON_5_GUN_HACIM_ARTISI_PUAN = 2


MFI_SAGLIKLI_BANT_PUAN = 2


CMF_POZITIF_PUAN = 3


CMF_ESIK = 0.05


VWAP_USTUNDE_PUAN = 2


DONCHIAN_KIRILIM_PUAN = 5


DONCHIAN_YAKINLIK_YUZDE = 0.02


HISTORICAL_VOL_SAGLIKLI_PUAN = 5


HIST_VOL_MIN_YUZDE = 20.0


HIST_VOL_MAKS_YUZDE = 65.0


FK_DUSUK_PUAN = 3


FK_ESIK = 15


PEG_UYGUN_PUAN = 2


PEG_ESIK = 1


PB_UYGUN_PUAN = 2


PB_ESIK = 3


FORWARD_PE_IYILESME_PUAN = 2


TEMETTU_VAR_PUAN = 1


HABER_POZITIF_NET_PUAN = 8


KAP_KAYNAKLI_EK_PUAN = 5


PATRON_OLAY_PUAN = 7


BALINA_HACIM_CARPANI = 3


OLUMLU_KELIMELER = ["ihale", "anlaşma", "rekor", "kar", "ortaklık", "kazandı", "satın", "büyüme", "temettü", "onay", "sözleşme"]


OLUMSUZ_KELIMELER = ["iptal", "düştü", "zarar", "azaldı", "ceza", "ertele", "durdur", "red", "soruşturma", "kayıp"]


PATRON_KELIMELERI = ["geri alım", "pay alım", "pay alım satım", "şirket payları", "hisse alımı"]


NEGASYON_KELIMELERI = ["değil", "değildi", "edilmedi", "olmadı", "kalmadı", "gerçekleşmedi", "yok"]


KAP_OLAY_TIPLERI = {
    "geri_alim": (["geri alım", "pay alım", "hisse alımı"], 10.0),
    "ortak_satisi": (["ortak satışı", "pay satışı", "hisse satışı"], -8.0),
    "bedelli": (["bedelli sermaye", "bedelli artırım"], -4.0),
    "bedelsiz": (["bedelsiz sermaye", "bedelsiz artırım"], 2.0),
    "temettu_dagitim": (["temettü dağıtım", "kar payı dağıtım"], 6.0),
}


hisseler_metni = """
AEFES.IS AGHOL.IS AHGAZ.IS AKBNK.IS AKCNS.IS AKFGY.IS AKSA.IS AKSEN.IS ALARK.IS ALFAS.IS
ANSGR.IS ARCLK.IS ASELS.IS ASTOR.IS ASUZU.IS AYDEM.IS BERA.IS BIMAS.IS BIOEN.IS BOBET.IS
BRSAN.IS BRYAT.IS BSOKE.IS BTCIM.IS CCOLA.IS CIMSA.IS CWENE.IS DOAS.IS DOHOL.IS ECILC.IS
EGEEN.IS EKGYO.IS ENJSA.IS ENKAI.IS EREGL.IS EUPWR.IS EUREN.IS FROTO.IS GARAN.IS GENIL.IS
GESAN.IS GLYHO.IS GUBRF.IS GWIND.IS HALKB.IS HEKTS.IS ISCTR.IS ISGYO.IS ISMEN.IS IZENR.IS
KARSN.IS KCAER.IS KCHOL.IS KLSER.IS KMPUR.IS KONTR.IS KONYA.IS KRDMD.IS MAVI.IS MGROS.IS
MIATK.IS ODAS.IS OTKAR.IS OYAKC.IS PETKM.IS PGSUS.IS PNLSN.IS QUAGR.IS SAHOL.IS SASA.IS
SDTTR.IS SISE.IS SKBNK.IS SMRTG.IS SOKM.IS TABGD.IS TAVHL.IS TCELL.IS THYAO.IS TKFEN.IS
TOASO.IS TSKB.IS TSPOR.IS TTKOM.IS TTRAK.IS TUKAS.IS TUPRS.IS ULKER.IS VAKBN.IS VESBE.IS
VESTL.IS YKBNK.IS YYLGD.IS ZOREN.IS ISFIN.IS ECZYT.IS GSDHO.IS SAYAS.IS YEOTK.IS ALBRK.IS
VAKKO.IS YUNSA.IS KORDS.IS GOODY.IS BRISA.IS JANTS.IS AYGAZ.IS TATGD.IS PETUN.IS PINSU.IS
PNSUT.IS KNFRT.IS ALKA.IS ALKIM.IS KLKIM.IS CMENT.IS NTHOL.IS TRGYO.IS HLGYO.IS VKGYO.IS
ZRGYO.IS PSGYO.IS KZBGY.IS GZNMI.IS HUNER.IS MAGEN.IS ESEN.IS NATEN.IS SUWEN.IS DGNMO.IS
YATAS.IS KRVGD.IS ULUUN.IS FMIZP.IS PARSN.IS GENTS.IS KARTN.IS PRKAB.IS BANVT.IS CRFSA.IS
BIZIM.IS PRKME.IS NUGYO.IS RYGYO.IS RYSAS.IS LOGO.IS ARDYZ.IS MOBTL.IS MZHLD.IS POLHO.IS
IHLAS.IS IHEVA.IS IHYAY.IS
"""


hisseler = [h.strip() for h in hisseler_metni.split()]


PIYASA_OZET_DOSYA = "son_piyasa_ozeti.json"


PNL_RAPOR_SIKLIGI_SAAT = 3
