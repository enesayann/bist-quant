"""Portfolio responsibilities extracted from the original bot."""
from .config import (
    ADX_ESIK,
    BALINA_HACIM_CARPANI,
    MAKS_RISK_YUZDESI,
    PORTFOY_BUYUKLUGU_TL,
    TR_TZ,
    UYARI_COOLDOWN_SAAT,
    log,
)
from .news import acik_pozisyon_negatif_haber_kontrol
from .scoring import tut_azalt_cik_skoru_hesapla
from .telegram_api import basit_mesaj_gonder
from .config import istanbul_datetime, tarama_durum_kilidi
from .indicators import guvenli_sayi
from datetime import datetime, timedelta
from typing import Optional
import numpy as np
import pandas as pd

def pozisyon_buyuklugu_hesapla(fiyat: float, stop_fiyati: float) -> int:
    if guvenli_sayi(fiyat) is None or guvenli_sayi(stop_fiyati) is None or fiyat <= 0:
        raise ValueError("Position sizing requires finite prices and a positive entry")
    hisse_basi_risk = fiyat - stop_fiyati
    return 0 if hisse_basi_risk <= 0 else max(0, int((PORTFOY_BUYUKLUGU_TL * MAKS_RISK_YUZDESI) / hisse_basi_risk))


def pozisyon_ac(hisse: str, fiyat: float, stop: float, tp1: float, tp2: float, atr: float, etiket: str, pozisyon_takip: dict, adet: Optional[float] = None) -> None:
    if any(guvenli_sayi(value) is None for value in (fiyat, stop, tp1, tp2, atr)) or fiyat <= 0 or atr <= 0:
        raise ValueError("Position prices must be finite; entry and ATR must be positive")
    if not stop < fiyat < tp1 < tp2:
        raise ValueError("Invalid position stop/target order")
    if adet is not None and (guvenli_sayi(adet) is None or adet <= 0):
        raise ValueError("Quantity must be finite and positive")
    if any(p["hisse"] == hisse for p in pozisyon_takip["acik"]):
        raise ValueError("Position already open for " + hisse)
    pozisyon_takip["acik"].append({
        "hisse": hisse, "giris_fiyati": fiyat, "stop": stop, "guncel_stop": stop,
        "tp1": tp1, "tp2": tp2, "atr": atr, "etiket": etiket, "adet": adet,
        "acilis_tarihi": datetime.now(TR_TZ).isoformat(), "tp1_vuruldu": False,
        "en_yuksek_fiyat": fiyat, "son_uyarilar": {},
    })


def uyari_gonderilebilir_mi(poz: dict, tip: str) -> bool:
    """Aynı uyarı tipinin (haber/hacim/trend) art arda spam olmasını engeller."""
    zaman_str = poz.setdefault("son_uyarilar", {}).get(tip)
    if not zaman_str:
        return True
    return datetime.now(TR_TZ) - istanbul_datetime(zaman_str) > timedelta(hours=UYARI_COOLDOWN_SAAT)


def uyari_gonderildi_isaretle(poz: dict, tip: str) -> None:
    poz.setdefault("son_uyarilar", {})[tip] = datetime.now(TR_TZ).isoformat()


def kar_zarar_tl_metni(poz: dict, fiyat: float) -> str:
    """adet biliniyorsa TL bazında kâr/zararı da ekler, bilinmiyorsa boş döner."""
    adet = poz.get("adet")
    if not adet:
        return ""
    tl = (fiyat - poz["giris_fiyati"]) * adet
    return f" (~{tl:+,.0f} TL)"


def kapanis_mesaji_gonder(poz: dict) -> None:
    mesaj = f"{'✅' if poz['pnl_yuzde'] > 0 else '❌'} **POZİSYON KAPANDI: {poz['hisse']}**\n\nSonuç: {poz['sonuc']}\nGiriş: {poz['giris_fiyati']:.2f} TL → Çıkış: {poz['kapanis_fiyati']:.2f} TL\nGetiri: %{poz['pnl_yuzde']:.2f}{kar_zarar_tl_metni(poz, poz['kapanis_fiyati'])}\nOrijinal Sinyal: {poz['etiket']}"
    basit_mesaj_gonder(mesaj)


def _acik_pozisyon_ek_kontroller(hisse: str, df: pd.DataFrame, poz: dict, fiyat: float) -> None:
    """Hâlâ açık olan bir pozisyon için negatif haber, büyük satış hacmi ve
    trend zayıflama/güçlenme uyarılarını kontrol eder (cooldown korumalı)."""
    haber = acik_pozisyon_negatif_haber_kontrol(hisse)
    if haber["negatif"] and uyari_gonderilebilir_mi(poz, "negatif_haber"):
        if basit_mesaj_gonder(f"🚨 **NEGATİF HABER**\n\n{hisse.replace('.IS','')}\n\nBaşlık:\n\n{haber['baslik']}\n\nDikkatli olun."):
            uyari_gonderildi_isaretle(poz, "negatif_haber")

    ort_hacim, mevcut_hacim = df["Vol_20"].iloc[-1], df["Volume"].iloc[-1]
    onceki_kapanis = df["Close"].iloc[-2]
    hacim_kati = (mevcut_hacim / ort_hacim) if pd.notna(ort_hacim) and ort_hacim > 0 else 0
    if hacim_kati >= BALINA_HACIM_CARPANI and fiyat < onceki_kapanis and uyari_gonderilebilir_mi(poz, "hacim"):
        if basit_mesaj_gonder(f"🐋 **Büyük Satış Hacmi**\n\n{hisse.replace('.IS','')}\n\nNormal hacmin\n{hacim_kati:.1f} katı satış geldi."):
            uyari_gonderildi_isaretle(poz, "hacim")

    ema20, ema50 = df["EMA20"].iloc[-1], df["EMA50"].iloc[-1]
    macd_asagi = len(df) >= 2 and df["MACD"].iloc[-2] > df["MACD_Sinyal"].iloc[-2] and df["MACD"].iloc[-1] < df["MACD_Sinyal"].iloc[-1]
    macd_yukari_devam = df["MACD"].iloc[-1] > df["MACD_Sinyal"].iloc[-1]
    rsi_son, adx_son = df["RSI"].iloc[-1], df["ADX"].iloc[-1]
    obv_yukseliyor = len(df) >= 10 and df["OBV"].iloc[-1] > df["OBV"].iloc[-10]

    if ema20 < ema50 and macd_asagi and pd.notna(rsi_son) and rsi_son < 45 and uyari_gonderilebilir_mi(poz, "trend_zayif"):
        if basit_mesaj_gonder(f"⚠️ **Trend Zayıflıyor**\n\n{hisse.replace('.IS','')}\n\nMomentum düşüyor."):
            uyari_gonderildi_isaretle(poz, "trend_zayif")

    if ema20 > ema50 and macd_yukari_devam and obv_yukseliyor and pd.notna(adx_son) and adx_son > ADX_ESIK and uyari_gonderilebilir_mi(poz, "trend_guclu"):
        if basit_mesaj_gonder(f"💪 **Pozisyon Güçleniyor**\n\n{hisse.replace('.IS','')}\n\nTrend devam ediyor."):
            uyari_gonderildi_isaretle(poz, "trend_guclu")

    # --- 🔴 Kırmızı bölge uyarısı: skor 40'ın altına düşerse proaktif haber ver ---
    skor, skor_detay = tut_azalt_cik_skoru_hesapla(df, fiyat, poz, haber["negatif"], False)
    if skor < 40 and uyari_gonderilebilir_mi(poz, "risk_skoru"):
        nedenler = []
        if skor_detay["trend_faktoru"] < 0: nedenler.append("trend bozuluyor")
        if skor_detay["momentum_faktoru"] < 0: nedenler.append("momentum zayıf")
        if skor_detay["hacim_faktoru"] < 0: nedenler.append("satış hacmi yüksek")
        if skor_detay["hedef_mesafe_faktoru"] < 0: nedenler.append("stop'a yaklaşıyor")
        if skor_detay["haber_faktoru"] < 0: nedenler.append("negatif haber")
        neden_metni = ", ".join(nedenler) if nedenler else "genel zayıflama"
        if basit_mesaj_gonder(
            f"🔴 **RİSK UYARISI: ÇIKMAYI DEĞERLENDİR**\n\n{hisse.replace('.IS','')}\n\n"
            f"Skor: {skor}/100\nSebep: {neden_metni}{kar_zarar_tl_metni(poz, fiyat)}\n\n"
            f"Pozisyonu gözden geçirmeni öneririm."
        ):
            uyari_gonderildi_isaretle(poz, "risk_skoru")


def pozisyon_kontrol_et(hisse: str, df: pd.DataFrame, pozisyon_takip: dict) -> None:
    # Every worker replaces the shared acik list; serialize the whole transition.
    with tarama_durum_kilidi:
        _pozisyon_kontrol_et(hisse, df, pozisyon_takip)


def _pozisyon_kontrol_et(hisse: str, df: pd.DataFrame, pozisyon_takip: dict) -> None:
    """Açık pozisyonlar için TP1/TP2/STOP kontrolü + sürekli ATR trailing stop +
    trend/hacim/haber uyarıları. df'in EMA/RSI/MACD/ADX/OBV/ATR indikatörleri
    zaten hesaplanmış olmalı."""
    bugun_high, bugun_low, fiyat = df["High"].iloc[-1], df["Low"].iloc[-1], df["Close"].iloc[-1]
    atr_son = df["ATR"].iloc[-1] if "ATR" in df.columns and pd.notna(df["ATR"].iloc[-1]) else None
    kalanlar = []

    for poz in pozisyon_takip["acik"]:
        if poz["hisse"] != hisse:
            kalanlar.append(poz)
            continue

        # --- Sürekli ATR Trailing Stop: yeni zirve yapıldıkça stop yukarı taşınır ---
        if fiyat > poz.get("en_yuksek_fiyat", poz["giris_fiyati"]):
            poz["en_yuksek_fiyat"] = fiyat
            if atr_son:
                yeni_trailing_stop = fiyat - 1.5 * atr_son
                if yeni_trailing_stop > poz["guncel_stop"]:
                    poz["guncel_stop"] = yeni_trailing_stop
                    log.info(f"[{hisse}] Trailing stop güncellendi: {poz['guncel_stop']:.2f}")

        sonuc, kapandi = None, False
        if bugun_low <= poz["guncel_stop"]:
            cikis = poz["guncel_stop"]
            sonuc = ("WIN TP1 (Stop sonrası)" if poz["tp1_vuruldu"] else "WIN TRAILING STOP") if cikis > poz["giris_fiyati"] else "BREAK EVEN" if cikis == poz["giris_fiyati"] else "LOSS"
            kapandi = True
        elif bugun_high >= poz["tp2"]:
            sonuc, kapandi = "WIN TP2", True
        elif not poz["tp1_vuruldu"] and bugun_high >= poz["tp1"]:
            poz["tp1_vuruldu"] = True
            poz["guncel_stop"] = max(poz["guncel_stop"], poz["giris_fiyati"])
            kar_yuzde = (poz["tp1"] - poz["giris_fiyati"]) / poz["giris_fiyati"] * 100
            basit_mesaj_gonder(
                f"🎯 **HEDEF 1 GELDİ**\n\n{hisse.replace('.IS','')}\n\n"
                f"Giriş:\n{poz['giris_fiyati']:.2f}\n\nAnlık:\n{fiyat:.2f}\n\n"
                f"Kar:\n%{kar_yuzde:.2f}\n\nStop maliyete çekildi."
            )
            log.info(f"[{hisse}] TP1 vuruldu, stop break-even'e çekildi.")

        if kapandi:
            cikis = poz["tp2"] if sonuc == "WIN TP2" else poz["guncel_stop"]
            pnl_yuzde = (cikis - poz["giris_fiyati"]) / poz["giris_fiyati"] * 100
            poz.update({"sonuc": sonuc, "kapanis_fiyati": cikis, "pnl_yuzde": round(pnl_yuzde, 2), "kapanis_tarihi": datetime.now(TR_TZ).isoformat()})
            pozisyon_takip["kapanan"].append(poz)
            log.info(f"[{hisse}] Poz kapandı: {sonuc} (%{pnl_yuzde:.2f})")
            if sonuc == "WIN TP2":
                basit_mesaj_gonder(f"🚀 **HEDEF 2 GELDİ**\n\n{hisse.replace('.IS','')}\n\nKar:\n%{pnl_yuzde:.2f}\n\nPozisyonun büyük kısmı realize edilebilir.")
            elif sonuc == "LOSS":
                basit_mesaj_gonder(f"🛑 **STOP ÇALIŞTI**\n\n{hisse.replace('.IS','')}\n\nKar/Zarar:\n%{pnl_yuzde:.2f}\n\nPozisyon kapatılmalı.")
            else:
                kapanis_mesaji_gonder(poz)
        else:
            _acik_pozisyon_ek_kontroller(hisse, df, poz, fiyat)
            kalanlar.append(poz)

    pozisyon_takip["acik"] = kalanlar


def performans_istatistikleri_hesapla(kapanan: list[dict]) -> dict:
    if not kapanan: return {}
    pnl = [p["pnl_yuzde"] for p in kapanan]
    kaz = [p for p in pnl if p > 0]
    kay = [p for p in pnl if p <= 0]
    win = len(kaz) / len(pnl)
    ort_kaz, ort_kay = float(np.mean(kaz)) if kaz else 0.0, float(np.mean(kay)) if kay else 0.0
    pf = (sum(kaz) / abs(sum(kay))) if sum(kay) != 0 else None
    kum = np.concatenate(([0.0], np.cumsum(pnl)))
    md = float((kum - np.maximum.accumulate(kum)).min()) if len(kum) else 0.0
    return {"toplam_islem": len(pnl), "win_rate_yuzde": round(win * 100, 1), "ortalama_kazanc_yuzde": round(ort_kaz, 2), "ortalama_kayip_yuzde": round(ort_kay, 2), "profit_factor": round(pf, 2) if pf is not None else "∞" if kaz else 0.0, "maksimum_drawdown_yuzde": round(md, 2), "expectancy_yuzde": round(win * ort_kaz + (1 - win) * ort_kay, 2)}
