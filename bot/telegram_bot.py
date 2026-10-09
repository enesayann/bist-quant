"""Telegram bot responsibilities extracted from the original bot."""
from .config import TELEGRAM_OFFSET_DOSYA, TR_TZ, log, pozisyon_kilidi
from .market_data import tek_hisse_veri_getir
from .news import acik_pozisyon_negatif_haber_kontrol
from .portfolio import kar_zarar_tl_metni, pozisyon_ac
from .scoring import skor_etiketi, tut_azalt_cik_skoru_hesapla
from .storage import _json_kaydet, _json_yukle, pozisyon_takip_kaydet, pozisyon_takip_yukle
from .telegram_api import basit_mesaj_gonder, telegram_guncellemelerini_al
from .config import telegram_credentials
from .storage import StorageError
from .indicators import guvenli_sayi
from datetime import datetime
import re
import threading

def ticker_normalize(ham: str) -> str:
    ham = ham.strip().upper()
    if not re.fullmatch(r"[A-Z0-9]{1,12}(?:\.IS)?", ham):
        raise ValueError("Invalid ticker")
    return ham if ham.endswith(".IS") else f"{ham}.IS"


def komut_al(args: list[str]) -> str:
    if len(args) < 2:
        return "Kullanım: /al ASELS 132.40 [adet]\nÖrnek: /al ASELS 132.40 500"
    try:
        hisse = ticker_normalize(args[0])
        fiyat = float(args[1].replace(",", "."))
    except ValueError:
        return "Geçersiz fiyat. Örnek: /al ASELS 132.40 500"
    if guvenli_sayi(fiyat) is None or fiyat <= 0:
        return "Geçersiz fiyat: sonlu ve pozitif bir sayı girin."

    adet = None
    if len(args) >= 3:
        try:
            adet = float(args[2].replace(",", "."))
        except ValueError:
            return "Geçersiz adet. Örnek: /al ASELS 132.40 500"
        if guvenli_sayi(adet) is None or adet <= 0:
            return "Geçersiz adet: sonlu ve pozitif bir sayı girin."

    with pozisyon_kilidi:
        pozisyon_takip = pozisyon_takip_yukle()
        if any(p["hisse"] == hisse for p in pozisyon_takip["acik"]):
            return f"⚠️ {hisse} için zaten açık bir pozisyon var. Önce /sat {args[0]} ile kapatın."

        df = tek_hisse_veri_getir(hisse)
        if df is None:
            return f"❌ {hisse} için veri alınamadı, pozisyon eklenemedi."
        atr = df["ATR"].iloc[-1]
        if guvenli_sayi(atr) is None or atr <= 0:
            return f"❌ {hisse} için ATR hesaplanamadı, pozisyon eklenemedi."

        stop, tp1, tp2 = fiyat - 1.5 * atr, fiyat + 2 * atr, fiyat + 3 * atr
        pozisyon_ac(hisse, fiyat, stop, tp1, tp2, float(atr), "MANUEL GİRİŞ", pozisyon_takip, adet)
        pozisyon_takip_kaydet(pozisyon_takip)

    tutar_satiri = f"\nTutar: {adet:.0f} adet (~{adet*fiyat:,.0f} TL)" if adet else "\n💡 İpucu: /al ASELS 132.40 500 şeklinde adet de belirtirsen TL bazında kâr/zarar gösterebilirim."
    return (
        f"✅ **Pozisyon Eklendi**\n\n🏷️ {hisse}\nGiriş: {fiyat:.2f} TL{tutar_satiri}\n"
        f"Stop: {stop:.2f} TL\nHedef 1: {tp1:.2f} TL\nHedef 2: {tp2:.2f} TL\n\n"
        f"Bu pozisyon artık her 15 dakikada otomatik takip edilecek."
    )


def komut_pozisyonlar() -> str:

    pozisyon_takip = pozisyon_takip_yukle()
    acik = pozisyon_takip["acik"]
    if not acik:
        return "Açık pozisyon yok. /al TICKER FİYAT ile ekleyebilirsin."
    satirlar = ["📋 **Açık Pozisyonlar**"]
    for poz in acik:
        df = tek_hisse_veri_getir(poz["hisse"])
        if df is None:
            satirlar.append(f"\n{poz['hisse']} — veri alınamadı")
            continue
        fiyat = float(df["Close"].iloc[-1])
        pnl = (fiyat - poz["giris_fiyati"]) / poz["giris_fiyati"] * 100
        risk = (poz["guncel_stop"] - poz["giris_fiyati"]) / poz["giris_fiyati"] * 100
        haber = acik_pozisyon_negatif_haber_kontrol(poz["hisse"])
        skor, _ = tut_azalt_cik_skoru_hesapla(df, fiyat, poz, haber["negatif"], False)
        satirlar.append(
            f"\n**{poz['hisse'].replace('.IS','')}**\nAlış: {poz['giris_fiyati']:.2f}\n"
            f"Anlık: {fiyat:.2f}\nKar: %{pnl:.2f}{kar_zarar_tl_metni(poz, fiyat)}\nStop: {poz['guncel_stop']:.2f}\n"
            f"Target1: {poz['tp1']:.2f}\nTarget2: {poz['tp2']:.2f}\nRisk: %{risk:.1f}\n"
            f"Skor: {skor}/100 {skor_etiketi(skor)}"
            + ("\nHaber verisi alınamadı; skor haber açısından eksik." if not haber.get("kullanilabilir", True) else "")
        )
    return "\n".join(satirlar)


def komut_sat(args: list[str]) -> str:
    if not args:
        return "Kullanım: /sat ASELS"
    try:
        hisse = ticker_normalize(args[0])
    except ValueError:
        return "Geçersiz hisse kodu. Örnek: /sat ASELS"
    with pozisyon_kilidi:
        pozisyon_takip = pozisyon_takip_yukle()
        poz = next((p for p in pozisyon_takip["acik"] if p["hisse"] == hisse), None)
        if poz is None:
            return f"❌ {hisse} için açık pozisyon bulunamadı."
        df = tek_hisse_veri_getir(hisse)
        if df is None:
            return f"❌ {hisse} için veri alınamadı; pozisyon kapatılmadı."
        fiyat = float(df["Close"].iloc[-1])
        pnl = (fiyat - poz["giris_fiyati"]) / poz["giris_fiyati"] * 100
        poz.update({"sonuc": "MANUEL KAPANIŞ", "kapanis_fiyati": fiyat, "pnl_yuzde": round(pnl, 2), "kapanis_tarihi": datetime.now(TR_TZ).isoformat()})
        pozisyon_takip["acik"] = [p for p in pozisyon_takip["acik"] if p["hisse"] != hisse]
        pozisyon_takip["kapanan"].append(poz)
        pozisyon_takip_kaydet(pozisyon_takip)
    return f"✅ {hisse} pozisyonu kapatıldı.\nÇıkış: {fiyat:.2f} TL\nSonuç: %{pnl:.2f}{kar_zarar_tl_metni(poz, fiyat)}"


def komut_durum(args: list[str]) -> str:
    if not args:
        return "Kullanım: /durum ASELS"
    try:
        hisse = ticker_normalize(args[0])
    except ValueError:
        return "Geçersiz hisse kodu. Örnek: /durum ASELS"
    pozisyon_takip = pozisyon_takip_yukle()
    poz = next((p for p in pozisyon_takip["acik"] if p["hisse"] == hisse), None)
    if poz is None:
        return f"❌ {hisse} için açık pozisyon bulunamadı."
    df = tek_hisse_veri_getir(hisse)
    if df is None:
        return f"❌ {hisse} için veri alınamadı."
    fiyat = float(df["Close"].iloc[-1])
    pnl = (fiyat - poz["giris_fiyati"]) / poz["giris_fiyati"] * 100
    haber = acik_pozisyon_negatif_haber_kontrol(hisse)
    skor, detay = tut_azalt_cik_skoru_hesapla(df, fiyat, poz, haber["negatif"], False)
    trend_metni = "Yükseliş" if df["EMA20"].iloc[-1] > df["EMA50"].iloc[-1] else "Düşüş"
    return (
        f"📊 **{hisse} Durum Raporu**\n\nGiriş: {poz['giris_fiyati']:.2f} TL ({poz['acilis_tarihi'][:10]})\n"
        f"Anlık: {fiyat:.2f} TL\nKar/Zarar: %{pnl:.2f}{kar_zarar_tl_metni(poz, fiyat)}\nEn Yüksek: {poz.get('en_yuksek_fiyat', poz['giris_fiyati']):.2f} TL\n"
        f"Güncel Stop: {poz['guncel_stop']:.2f} TL\nTarget1: {poz['tp1']:.2f} TL {'✅' if poz['tp1_vuruldu'] else ''}\n"
        f"Target2: {poz['tp2']:.2f} TL\nTrend: {trend_metni}\nRSI: {df['RSI'].iloc[-1]:.1f}\n"
        f"Negatif Haber: {'Bilinmiyor (veri alınamadı)' if not haber.get('kullanilabilir', True) else 'Var — ' + haber['baslik'] if haber['negatif'] else 'Yok'}\n\n"
        f"🎯 **Tut/Azalt/Çık Skoru: {skor}/100**\n{skor_etiketi(skor)}"
    )


def komut_yardim() -> str:
    return (
        "🤖 **Komutlar**\n\n"
        "/al TICKER FİYAT — pozisyon ekle (örn: /al ASELS 132.40)\n"
        "/pozisyonlar — açık pozisyonları listele\n"
        "/sat TICKER — pozisyonu manuel kapat\n"
        "/durum TICKER — detaylı pozisyon raporu"
    )


def komut_isle(mesaj: dict) -> None:
    _, chat_id = telegram_credentials()
    if not isinstance(mesaj, dict) or not isinstance(mesaj.get("chat"), dict):
        return
    if str(mesaj["chat"].get("id")) != chat_id:
        return
    metin = mesaj.get("text", "")
    if not isinstance(metin, str):
        return
    metin = metin.strip()
    if not metin.startswith("/"):
        return
    parcalar = metin.split()
    komut, args = parcalar[0].lower().split("@")[0], parcalar[1:]

    try:
        if komut == "/al": cevap = komut_al(args)
        elif komut == "/pozisyonlar": cevap = komut_pozisyonlar()
        elif komut == "/sat": cevap = komut_sat(args)
        elif komut == "/durum": cevap = komut_durum(args)
        elif komut in ("/yardim", "/help", "/start"): cevap = komut_yardim()
        else: return
    except StorageError:
        log.error("Telegram command failed because state could not be read or saved")
        cevap = "❌ Durum dosyası okunamadı veya kaydedilemedi. Komut tamamlanamadı; logu kontrol edin."
    except (ValueError, KeyError, TypeError) as error:
        log.error("Telegram command failed: %s", type(error).__name__)
        cevap = "❌ Komut işlenemedi; veri ve girdileri kontrol edin."

    basit_mesaj_gonder(cevap)


def telegram_komut_dinleyicisi_baslat(stop_event=None) -> None:
    """Arka planda sürekli Telegram komutlarını dinler (long polling).
    Sadece TELEGRAM_CHAT_ID'den gelen komutlar işlenir (güvenlik).
    İnternet/DNS kesintisinde kademeli bekleme (5s -> 10s -> ... -> maks 2dk)
    uygular; bağlantı geri gelince otomatik 5s'ye sıfırlanır ve log spamlemez."""
    offset = _json_yukle(TELEGRAM_OFFSET_DOSYA, {"offset": 0}).get("offset", 0)
    stop_event = stop_event or threading.Event()
    log.info("📡 Telegram komut dinleyicisi başladı (/al, /pozisyonlar, /sat, /durum)")
    bekleme_saniye = 5
    ardisik_hata_sayisi = 0

    while not stop_event.is_set():
        try:
            guncellemeler = telegram_guncellemelerini_al(offset)
            if guncellemeler or ardisik_hata_sayisi > 0:
                if ardisik_hata_sayisi >= 3:
                    log.info("✅ Telegram bağlantısı geri geldi.")
                bekleme_saniye, ardisik_hata_sayisi = 5, 0

            for g in guncellemeler:
                offset = g["update_id"] + 1
                mesaj = g.get("message")
                if not mesaj:
                    continue
                komut_isle(mesaj)
            if guncellemeler:
                _json_kaydet(TELEGRAM_OFFSET_DOSYA, {"offset": offset})
        except Exception as e:
            ardisik_hata_sayisi += 1
            if ardisik_hata_sayisi in (1, 5) or ardisik_hata_sayisi % 15 == 0:
                # Her hatada değil, sadece 1., 5. ve her 15 hatada bir logla (spam önleme)
                log.warning("Telegram command listener failed (%s consecutive errors): %s", ardisik_hata_sayisi, type(e).__name__)
            stop_event.wait(bekleme_saniye)
            bekleme_saniye = min(bekleme_saniye * 2, 120)  # 5,10,20,40,80,120... 2dk'da sabitlenir
            continue
        stop_event.wait(0.5)  # normal döngüde Telegram'a nefes aldır
