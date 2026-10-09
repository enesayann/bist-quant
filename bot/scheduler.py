"""Scheduler responsibilities extracted from the original bot."""
from .analysis import analiz_et
from .config import (
    ADX_ESIK,
    HABER_CACHE_DOSYA,
    PERFORMANS_OZET_DOSYA,
    PIYASA_ACILIS,
    PIYASA_KAPANIS,
    PIYASA_OZET_DOSYA,
    PNL_RAPOR_SIKLIGI_SAAT,
    POZISYON_OZET_DOSYA,
    TR_TZ,
    hisseler,
    log,
    pozisyon_kilidi,
)
from .config import tarama_kilidi
from .market_data import gunluk_fiyat_degisimini_getir, tek_hisse_veri_getir
from .news import acik_pozisyon_negatif_haber_kontrol
from .portfolio import kar_zarar_tl_metni, performans_istatistikleri_hesapla
from .storage import (
    _json_kaydet,
    _json_yukle,
    pozisyon_takip_kaydet,
    pozisyon_takip_yukle,
    son_sinyalleri_kaydet,
    son_sinyalleri_yukle,
)
from .telegram_api import basit_mesaj_gonder
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import pandas as pd

def piyasa_acik_mi() -> bool:
    simdi = datetime.now(TR_TZ)
    if simdi.weekday() >= 5: return False
    acilis = simdi.replace(hour=PIYASA_ACILIS[0], minute=PIYASA_ACILIS[1], second=0, microsecond=0)
    kapanis = simdi.replace(hour=PIYASA_KAPANIS[0], minute=PIYASA_KAPANIS[1], second=0, microsecond=0)
    return acilis <= simdi <= kapanis


def gunluk_performans_ozetini_gonder_gerekirse(pozisyon_takip: dict) -> None:
    bugun = datetime.now(TR_TZ).date().isoformat()
    son = _json_yukle(PERFORMANS_OZET_DOSYA, {"tarih": ""})
    if son.get("tarih") == bugun: return
    ist = performans_istatistikleri_hesapla(pozisyon_takip["kapanan"])
    if not ist: return
    mesaj = f"📊 **GÜNLÜK PERFORMANS ÖZETİ** ({bugun})\n\nToplam İşlem: {ist['toplam_islem']}\n🎯 Win Rate: %{ist['win_rate_yuzde']}\n📈 Ortalama Kazanç: %{ist['ortalama_kazanc_yuzde']}\n📉 Ortalama Kayıp: %{ist['ortalama_kayip_yuzde']}\n💹 Profit Factor: {ist['profit_factor']}\n🔻 Maksimum Drawdown: %{ist['maksimum_drawdown_yuzde']}\n🧮 Expectancy: %{ist['expectancy_yuzde']}"
    if basit_mesaj_gonder(mesaj):
        _json_kaydet(PERFORMANS_OZET_DOSYA, {"tarih": bugun})


def periyodik_kar_zarar_raporu_gonder() -> None:
    """Piyasa açıkken her PNL_RAPOR_SIKLIGI_SAAT saatte bir tüm açık pozisyonların
    kâr/zarar durumunu özetleyip Telegram'a gönderir."""
    if not piyasa_acik_mi():
        return
    with pozisyon_kilidi:
        pozisyon_takip = pozisyon_takip_yukle()
    acik = pozisyon_takip["acik"]
    if not acik:
        return

    satirlar = [f"⏱️ **{PNL_RAPOR_SIKLIGI_SAAT} Saatlik Kâr/Zarar Özeti**"]
    toplam_tl = 0.0
    for poz in acik:
        df = tek_hisse_veri_getir(poz["hisse"])
        if df is None:
            satirlar.append(f"\n{poz['hisse'].replace('.IS','')} — veri alınamadı")
            continue
        fiyat = float(df["Close"].iloc[-1])
        pnl = (fiyat - poz["giris_fiyati"]) / poz["giris_fiyati"] * 100
        adet = poz.get("adet")
        if adet:
            toplam_tl += (fiyat - poz["giris_fiyati"]) * adet
        satirlar.append(f"\n**{poz['hisse'].replace('.IS','')}**: %{pnl:+.2f}{kar_zarar_tl_metni(poz, fiyat)}")

    if any(poz.get("adet") for poz in acik):
        satirlar.append(f"\n\n💰 **Toplam: {toplam_tl:+,.0f} TL**")

    basit_mesaj_gonder("\n".join(satirlar))


def gun_sonu_piyasa_ozeti_gonder() -> None:
    """Piyasa kapanışında tüm hisseleri tarar; en çok yükselen/düşenleri ve
    günün önemli haberlerini (haber_cache.json'dan) Telegram'a gönderir.
    Ana sinyal taramasından bağımsız çalışır (cooldown'a takılmaz), bu yüzden
    o gün sinyal göndermemiş hisseler de özete dahil olur."""
    bugun = datetime.now(TR_TZ).date().isoformat()
    son = _json_yukle(PIYASA_OZET_DOSYA, {"tarih": ""})
    if son.get("tarih") == bugun:
        return

    log.info("📊 [GÜN SONU ÖZETİ] Piyasa geneli taranıyor...")
    with ThreadPoolExecutor(max_workers=5) as executor:
        sonuclar = list(executor.map(gunluk_fiyat_degisimini_getir, hisseler))
    gecerliler = [s for s in sonuclar if s is not None]

    if not gecerliler:
        log.warning("[GÜN SONU ÖZETİ] Hiçbir hisse için veri alınamadı, özet gönderilmiyor.")
        return

    siralanmis = sorted(gecerliler, key=lambda x: x[2], reverse=True)
    en_cok_yukselenler, en_cok_dusenler = siralanmis[:5], siralanmis[-5:][::-1]

    satirlar = [f"📊 **GÜN SONU PİYASA ÖZETİ** ({bugun})\n", "🟢 **En Çok Yükselenler**"]
    satirlar += [f"{h.replace('.IS','')}: {f:.2f} TL (%{d:+.2f})" for h, f, d in en_cok_yukselenler]
    satirlar.append("\n🔴 **En Çok Düşenler**")
    satirlar += [f"{h.replace('.IS','')}: {f:.2f} TL (%{d:+.2f})" for h, f, d in en_cok_dusenler]

    haber_cache = _json_yukle(HABER_CACHE_DOSYA, {})
    onemli_haberler = [
        (h, v) for h, v in haber_cache.items()
        if v.get("tarih") == bugun and (v.get("pozitif") or v.get("kap_olay_puani", 0) != 0)
    ]
    satirlar.append("\n📰 **Günün Önemli Haberleri**")
    if onemli_haberler:
        onemli_haberler.sort(key=lambda x: (x[1].get("patron_aliyor", False), x[1].get("kap_kaynakli", False)), reverse=True)
        for h, v in onemli_haberler[:5]:
            etiket = "👔" if v.get("patron_aliyor") else "📢" if v.get("kap_kaynakli") else "📰"
            satirlar.append(f"{etiket} {h.replace('.IS','')}: {v.get('baslik','')}")
    else:
        satirlar.append("Yok")

    if basit_mesaj_gonder("\n".join(satirlar)):
        _json_kaydet(PIYASA_OZET_DOSYA, {"tarih": bugun})
        log.info("✅ [GÜN SONU ÖZETİ] Gönderildi.")


def gun_sonu_pozisyon_ozeti_gonder() -> None:
    """Açık pozisyonlar için gün sonu özet (kâr/zarar, trend, negatif haber durumu)."""
    bugun = datetime.now(TR_TZ).date().isoformat()
    son = _json_yukle(POZISYON_OZET_DOSYA, {"tarih": ""})
    if son.get("tarih") == bugun:
        return
    with pozisyon_kilidi:
        pozisyon_takip = pozisyon_takip_yukle()
    acik = pozisyon_takip["acik"]
    if not acik:
        return

    satirlar = ["📊 **Gün Sonu Pozisyon Özeti**"]
    for poz in acik:
        df = tek_hisse_veri_getir(poz["hisse"])
        if df is None:
            satirlar.append(f"\n{poz['hisse']} — veri alınamadı")
            continue
        fiyat = float(df["Close"].iloc[-1])
        pnl = (fiyat - poz["giris_fiyati"]) / poz["giris_fiyati"] * 100
        trend_metni = ("Trend Güçlü" if df["EMA20"].iloc[-1] > df["EMA50"].iloc[-1] and pd.notna(df["ADX"].iloc[-1]) and df["ADX"].iloc[-1] > ADX_ESIK
                       else "Momentum zayıf" if df["EMA20"].iloc[-1] < df["EMA50"].iloc[-1] else "Nötr")
        haber = acik_pozisyon_negatif_haber_kontrol(poz["hisse"])
        satirlar.append(
            f"\n**{poz['hisse'].replace('.IS','')}**\n{'+' if pnl>=0 else ''}{pnl:.1f}%\n{trend_metni}\n"
            f"Stop:\n{poz['guncel_stop']:.2f}\nNegatif haber:\n{'Bilinmiyor (veri alınamadı)' if not haber.get('kullanilabilir', True) else 'Var' if haber['negatif'] else 'Yok'}"
        )
    if basit_mesaj_gonder("\n".join(satirlar)):
        _json_kaydet(POZISYON_OZET_DOSYA, {"tarih": bugun})


def ana_tarama() -> None:
    if not tarama_kilidi.acquire(blocking=False):
        log.info("Previous scan still running; overlapping scan skipped")
        return
    try:
        _ana_tarama()
    finally:
        tarama_kilidi.release()


def _ana_tarama() -> None:
    if not piyasa_acik_mi():
        log.info("😴 Piyasa kapalı, tarama atlanıyor.")
        return

    log.info("🕵️ [ANA TARAMA] Teknik analiz ve sinyal taraması başlıyor... (Haberler cache'den okunuyor)")
    son_sinyaller = son_sinyalleri_yukle()

    # 🔒 Pozisyon dosyasını /al ve /sat komutlarıyla aynı anda değiştirmemek için kilit
    with pozisyon_kilidi:
        pozisyon_takip = pozisyon_takip_yukle()
        with ThreadPoolExecutor(max_workers=4) as executor:
            sonuclar = list(executor.map(lambda h: analiz_et(h, son_sinyaller, pozisyon_takip), hisseler))
        pozisyon_takip_kaydet(pozisyon_takip)

    son_sinyalleri_kaydet(son_sinyaller)
    gunluk_performans_ozetini_gonder_gerekirse(pozisyon_takip)
    log.info(f"🏁 [TARAMA BİTTİ] Yeni Sinyal: {sum(1 for s in sonuclar if s is not None)} | Açık Pozisyon: {len(pozisyon_takip['acik'])}")
