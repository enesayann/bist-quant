"""News responsibilities extracted from the original bot."""
from .config import (
    GORULMUS_HABERLER_DOSYA,
    GORULMUS_HABER_SAKLAMA_GUNU,
    HABER_CACHE_DOSYA,
    KAP_OLAY_TIPLERI,
    NEGASYON_KELIMELERI,
    OLUMLU_KELIMELER,
    OLUMSUZ_KELIMELER,
    PATRON_KELIMELERI,
    TR_TZ,
    hisseler,
    log,
)
from .http_client import session
from .storage import _json_kaydet, _json_yukle
from .config import api_warning, haber_kilidi, istanbul_datetime
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from zoneinfo import ZoneInfo
import hashlib
import re
import time
import xml.etree.ElementTree as ET
import requests


def _rss_items(response):
    response.raise_for_status()
    root = ET.fromstring(response.text)
    if root.tag != "rss" or root.find("channel") is None:
        raise ValueError("Unexpected Google News RSS structure")
    return root.findall(".//item")[:5]

def gorulmus_haberleri_yukle() -> dict:
    veri = _json_yukle(GORULMUS_HABERLER_DOSYA, {})
    esik = datetime.now(TR_TZ) - timedelta(days=GORULMUS_HABER_SAKLAMA_GUNU)
    return {h: t for h, t in veri.items() if istanbul_datetime(t) > esik}


def gorulmus_haberleri_kaydet(veri: dict) -> None: _json_kaydet(GORULMUS_HABERLER_DOSYA, veri)


def haber_hash(baslik: str) -> str: return hashlib.md5(baslik.encode("utf-8")).hexdigest()


def haber_bugune_mi_ait(item) -> bool:
    pubdate_el = item.find("pubDate")
    if pubdate_el is None or not pubdate_el.text:
        log.warning("RSS item has no publication date; skipped")
        return False
    try:
        haber_zamani = parsedate_to_datetime(pubdate_el.text)
        if haber_zamani.tzinfo is None: haber_zamani = haber_zamani.replace(tzinfo=ZoneInfo("UTC"))
        return haber_zamani.astimezone(TR_TZ).date() == datetime.now(TR_TZ).date()
    except (ValueError, TypeError, OverflowError):
        log.warning("RSS item has an invalid publication date; skipped")
        return False


def _negasyonlu_mu(baslik_lower: str, konum: int, uzunluk: int) -> bool:
    sonrasi = baslik_lower[konum + uzunluk: konum + uzunluk + 20]
    for neg in NEGASYON_KELIMELERI:
        # Retain common copula forms matched by the old substring rule, while
        # avoiding unrelated words such as 'yoksulluk'. This remains heuristic.
        pattern = re.escape(neg)
        if neg == "değil":
            pattern += r"(?:dir|di|miş|im|sin|iz|siniz|ler|se|ken)?"
        elif neg == "yok":
            pattern += r"(?:tur|tu|muş|sa)?"
        if re.search(r"\b" + pattern + r"\b", sonrasi):
            return True
    return False


def kap_kaynakli_mi(baslik: str) -> bool:
    parcalar = baslik.rsplit(" - ", 1)
    if len(parcalar) == 2: return bool(re.search(r"\bkap\b", parcalar[1].lower()))
    return False


def kap_olay_tipi_puani(baslik_lower: str) -> float:
    toplam = 0.0
    for kelimeler, agirlik in KAP_OLAY_TIPLERI.values():
        for kelime in kelimeler:
            konum = baslik_lower.find(kelime)
            if konum != -1 and not _negasyonlu_mu(baslik_lower, konum, len(kelime)):
                toplam += agirlik
                break
    return toplam


def kelime_skorunu_hesapla(baslik_lower: str) -> tuple[int, int]:
    olumlu_skor, olumsuz_skor = 0, 0
    zarar_azaldi_kalibi = any(z in baslik_lower for z in ["zarar azaldı", "zararı azaldı", "kaybı azaldı", "zarar düştü"])
    if zarar_azaldi_kalibi: olumlu_skor += 1

    for kelime in OLUMLU_KELIMELER:
        konum = baslik_lower.find(kelime)
        if konum != -1:
            olumsuz_skor += 1 if _negasyonlu_mu(baslik_lower, konum, len(kelime)) else 0
            olumlu_skor += 0 if _negasyonlu_mu(baslik_lower, konum, len(kelime)) else 1

    for kelime in OLUMSUZ_KELIMELER:
        konum = baslik_lower.find(kelime)
        if konum != -1:
            if zarar_azaldi_kalibi and kelime in ("azaldı", "zarar", "kayıp", "düştü"): continue
            olumlu_skor += 1 if _negasyonlu_mu(baslik_lower, konum, len(kelime)) else 0
            olumsuz_skor += 0 if _negasyonlu_mu(baslik_lower, konum, len(kelime)) else 1
    return olumlu_skor, olumsuz_skor


def toplu_haber_taramasi_yap() -> None:
    with haber_kilidi:
        _toplu_haber_taramasi_yap()


def _toplu_haber_taramasi_yap() -> None:
    """Günde 3 kez çalışarak Google News'i yavaş ve güvenli bir şekilde tarar.
    Bulduğu haberleri 'haber_cache.json' dosyasına yazar."""

    log.info("📰 [HABER MOTORU] Toplu haber taraması başlıyor. Google engeline takılmamak için yavaş çalışacaktır (~6-7 dk)...")
    gorulmus_haberler = gorulmus_haberleri_yukle()
    haber_cache = _json_yukle(HABER_CACHE_DOSYA, {})
    bugun_str = datetime.now(TR_TZ).date().isoformat()

    # Dünden kalan eski haberleri temizle
    haber_cache = {k: v for k, v in haber_cache.items() if v.get("tarih") == bugun_str}

    failures = 0
    for hisse in hisseler:
        time.sleep(2.5)  # 🚦 VİTES DÜŞÜRME: Google Ban Koruması
        try:
            clean_name = hisse.replace(".IS", "")
            url = f"https://news.google.com/rss/search?q={clean_name}+borsa+hisse+when:1d&hl=tr&gl=TR&ceid=TR:tr"
            r = session.get(url, timeout=10)
            for item in _rss_items(r):
                if not haber_bugune_mi_ait(item): continue
                baslik_el = item.find("title")
                if baslik_el is None or not baslik_el.text:
                    log.warning("[%s] RSS item has no title; skipped", hisse)
                    continue

                baslik = baslik_el.text
                h = haber_hash(baslik)
                if h in gorulmus_haberler: continue

                gorulmus_haberler[h] = datetime.now(TR_TZ).isoformat()
                baslik_lower = baslik.lower()
                kap_kaynagi = kap_kaynakli_mi(baslik)
                kap_puani = kap_olay_tipi_puani(baslik_lower)

                patron_aliyor = False
                for pk in PATRON_KELIMELERI:
                    konum = baslik_lower.find(pk)
                    if konum != -1 and not _negasyonlu_mu(baslik_lower, konum, len(pk)):
                        patron_aliyor = True
                        break

                olumlu, olumsuz = kelime_skorunu_hesapla(baslik_lower)
                pozitif = patron_aliyor or (olumlu > olumsuz)

                if pozitif or kap_puani != 0:
                    mevcut = haber_cache.get(hisse, {})
                    if mevcut.get("patron_aliyor") and not patron_aliyor: continue

                    haber_cache[hisse] = {
                        "tarih": bugun_str, "pozitif": pozitif, "baslik": baslik,
                        "patron_aliyor": patron_aliyor, "kap_kaynakli": kap_kaynagi, "kap_olay_puani": kap_puani
                    }
                    log.info(f"📰 [{hisse}] Önemli Haber Önbelleğe Alındı: {baslik}")
                    break

        except (requests.RequestException, ET.ParseError, ValueError) as error:
            failures += 1
            api_warning("Google bulk", error, "[%s] News scan failed (existing cache retained): %s", hisse, type(error).__name__)

    _json_kaydet(HABER_CACHE_DOSYA, haber_cache)
    gorulmus_haberleri_kaydet(gorulmus_haberler)
    if failures:
        log.warning("News scan incomplete: %s/%s tickers failed; cache persisted", failures, len(hisseler))
    else:
        log.info("✅ [HABER MOTORU] Haberler toplanıp önbelleğe (cache) kaydedildi.")


def haber_duyarlilik_kontrol(hisse_adi: str) -> dict:
    """Google'a ASLA bağlanmaz. Toplu haber taramasının hazırladığı önbellekten (cache) okur.
    Böylece ana teknik analiz taraması ışık hızında ve engelsiz tamamlanır."""
    haber_cache = _json_yukle(HABER_CACHE_DOSYA, {})
    bugun_str = datetime.now(TR_TZ).date().isoformat()
    mevcut = haber_cache.get(hisse_adi, {})

    if mevcut and mevcut.get("tarih") == bugun_str:
        return {
            "pozitif": mevcut.get("pozitif", False),
            "baslik": mevcut.get("baslik", ""),
            "patron_aliyor": mevcut.get("patron_aliyor", False),
            "kap_kaynakli": mevcut.get("kap_kaynakli", False),
            "kap_olay_puani": mevcut.get("kap_olay_puani", 0.0)
        }
    return {"pozitif": False, "baslik": "", "patron_aliyor": False, "kap_kaynakli": False, "kap_olay_puani": 0.0}


def acik_pozisyon_negatif_haber_kontrol(hisse: str) -> dict:
    """Açık pozisyonlar için CANLI negatif haber kontrolü. Toplu haber taraması
    (Motor 1) sadece POZİTİF/KAP haberlerini önbelleğe aldığı için negatif haberi
    yakalamak üzere burada ayrı, canlı bir kontrol yapılır. Sadece açık pozisyon
    sayısı kadar (genelde az) çağrıldığı için Google'a ekstra yük bindirmez."""
    try:
        clean_name = hisse.replace(".IS", "")
        url = f"https://news.google.com/rss/search?q={clean_name}+borsa+hisse+when:1d&hl=tr&gl=TR&ceid=TR:tr"
        r = session.get(url, timeout=8)
        for item in _rss_items(r):
            if not haber_bugune_mi_ait(item):
                continue
            baslik_el = item.find("title")
            if baslik_el is None or not baslik_el.text:
                continue
            olumlu, olumsuz = kelime_skorunu_hesapla(baslik_el.text.lower())
            if olumsuz > olumlu:
                return {"negatif": True, "baslik": baslik_el.text, "kullanilabilir": True}
        return {"negatif": False, "baslik": "", "kullanilabilir": True}
    except (requests.RequestException, ET.ParseError, ValueError) as error:
        api_warning("Google live", error, "[%s] Negatif haber durumu bilinmiyor: %s", hisse, type(error).__name__)
        return {"negatif": False, "baslik": "", "kullanilabilir": False}
