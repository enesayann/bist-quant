"""Analysis responsibilities extracted from the original bot."""
from .config import (
    BALINA_HACIM_CARPANI,
    EMA200_ICIN_MIN_VERI,
    HABER_MAX_PUAN,
    HACIM_MAX_PUAN,
    ICHIMOKU_ICIN_MIN_VERI,
    MAKS_RISK_YUZDESI,
    MIN_GUVEN_SKORU,
    MIN_VERI_UZUNLUGU,
    MOMENTUM_MAX_PUAN,
    PORTFOY_BUYUKLUGU_TL,
    TEMEL_MAX_PUAN,
    TREND_MAX_PUAN,
    VOLATILITE_MAX_PUAN,
    YAHOO_VERI_ARALIGI,
    log,
)
from .http_client import session
from .config import TR_TZ, tarama_durum_kilidi
from .market_data import chart_frame, temel_verileri_getir, MarketDataError
from .telegram_api import basit_mesaj_gonder
from .scoring import toplam_skorlar
from .storage import StorageError
from .config import api_warning
from .indicators import (
    guclu_destek_direnc_hesapla,
    guvenli_sayi,
    hesapla_adx,
    hesapla_atr_wilder,
    hesapla_bollinger,
    hesapla_cmf,
    hesapla_donchian,
    hesapla_ema,
    hesapla_historical_volatilite,
    hesapla_ichimoku_basit,
    hesapla_macd,
    hesapla_mfi,
    hesapla_obv,
    hesapla_rsi_wilder,
    hesapla_stoch_rsi,
    hesapla_supertrend,
    hesapla_vwap_yaklasik,
)
from .news import haber_duyarlilik_kontrol
from .portfolio import pozisyon_buyuklugu_hesapla, pozisyon_kontrol_et
from .scoring import (
    destek_direnc_ayarlamasi,
    haber_puani_hesapla,
    hacim_puani_hesapla,
    momentum_puani_hesapla,
    siniflandirma_etiketi,
    temel_puani_hesapla,
    trend_puani_hesapla,
    volatilite_puani_hesapla,
)
from .storage import cooldown_da_mi
from datetime import datetime
from typing import Optional
import numpy as np
import random
import requests
import time

def analiz_et(hisse: str, son_sinyaller: dict, pozisyon_takip: dict) -> Optional[str]:
    with tarama_durum_kilidi:
        pozisyon_var_mi = any(p["hisse"] == hisse for p in pozisyon_takip["acik"])
        cooldown_aktif = cooldown_da_mi(hisse, son_sinyaller)
    if cooldown_aktif and not pozisyon_var_mi: return None

    try:
        time.sleep(random.uniform(0.1, 0.8))  # 🚦 jitter: 6 thread aynı anda patlamasın, Yahoo ban riskini azaltır
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{hisse}?interval=1d&range={YAHOO_VERI_ARALIGI}"
        r = session.get(url, timeout=20)
        r.raise_for_status()
        data = r.json()
        result, df = chart_frame(data, MIN_VERI_UZUNLUGU)
        fiyat = guvenli_sayi(result.get("meta", {}).get("regularMarketPrice"))
        if fiyat is None or fiyat <= 0:
            raise MarketDataError("Invalid Yahoo regular market price")
        fk, peg, pb, forward_pe, temettu = temel_verileri_getir(hisse)

        df["SMA_20"], df["SMA_50"] = df["Close"].rolling(20).mean(), df["Close"].rolling(50).mean()
        df["EMA20"], df["EMA50"] = hesapla_ema(df["Close"], 20), hesapla_ema(df["Close"], 50)
        ema200_var = len(df) >= EMA200_ICIN_MIN_VERI
        df["EMA200"] = hesapla_ema(df["Close"], 200) if ema200_var else np.nan
        df["Vol_20"] = df["Volume"].rolling(20).mean()
        df["RSI"], df["ATR"], df["ADX"] = hesapla_rsi_wilder(df["Close"]), hesapla_atr_wilder(df), hesapla_adx(df)
        df["MACD"], df["MACD_Sinyal"] = hesapla_macd(df["Close"])
        df["BB_Ust"], df["BB_Orta"], df["BB_Alt"] = hesapla_bollinger(df["Close"])
        df["OBV"], df["MFI"], df["CMF"] = hesapla_obv(df["Close"], df["Volume"]), hesapla_mfi(df), hesapla_cmf(df)
        df["StochRSI_K"], df["StochRSI_D"] = hesapla_stoch_rsi(df["RSI"])
        df["VWAP_Yaklasik"] = hesapla_vwap_yaklasik(df)
        df["Donchian_Ust"], df["Donchian_Alt"] = hesapla_donchian(df)
        df["Hist_Vol"], df["SuperTrend_Yon"] = hesapla_historical_volatilite(df["Close"]), hesapla_supertrend(df)

        ichimoku_var = len(df) >= ICHIMOKU_ICIN_MIN_VERI
        if ichimoku_var: df["Tenkan"], df["Kijun"], df["Senkou_A"], df["Senkou_B"] = hesapla_ichimoku_basit(df)

        # --- Pozisyon takibi: indikatörler hazır olduğu için artık burada çalışabilir ---
        if pozisyon_var_mi: pozisyon_kontrol_et(hisse, df, pozisyon_takip)
        if cooldown_aktif: return None

        atr_degeri = df["ATR"].iloc[-1]
        if guvenli_sayi(atr_degeri) is None or atr_degeri <= 0:
            raise MarketDataError("Invalid ATR; signal skipped")

        son_3_gun_sma_ustunde = (df["Close"].tail(3) > df["SMA_20"].tail(3)).all()
        uzun_vadeli_yukselis = fiyat > df["SMA_50"].iloc[-1]
        ema_kisa_pozitif = fiyat > df["EMA20"].iloc[-1] > df["EMA50"].iloc[-1]
        trend_onayli = son_3_gun_sma_ustunde and uzun_vadeli_yukselis and ema_kisa_pozitif

        trend_p, trend_d = trend_puani_hesapla(df, fiyat, ema200_var, ichimoku_var)
        momentum_p, momentum_d = momentum_puani_hesapla(df, fiyat)
        hacim_p, hacim_d = hacim_puani_hesapla(df)
        volatilite_p, volatilite_d = volatilite_puani_hesapla(df, fiyat)
        temel_p, temel_d = temel_puani_hesapla(fk, peg, pb, forward_pe, temettu)
        destek, direnc = guclu_destek_direnc_hesapla(df)
        destek_direnc_ayar, destek_direnc_notu = destek_direnc_ayarlamasi(fiyat, destek, direnc)

        haber = haber_duyarlilik_kontrol(hisse)  # ARTIK GOOGLE'A GİTMEZ, CACHE'DEN OKUR
        haber_p, haber_d = haber_puani_hesapla(haber)

        nihai_skor, teknik_puan = toplam_skorlar(trend_p, momentum_p, hacim_p, volatilite_p, temel_p, haber_p, destek_direnc_ayar)

        mevcut_hacim, ortalama_hacim, dunku_fiyat = df["Volume"].iloc[-1], df["Vol_20"].iloc[-1], df["Close"].iloc[-2]
        hacim_kati = (mevcut_hacim / ortalama_hacim) if ortalama_hacim > 0 else 0
        balina_hareketi = (hacim_kati >= BALINA_HACIM_CARPANI) and (fiyat > dunku_fiyat)

        guven_skoru = min(10, int(teknik_puan / 10))
        puan_barajı_uygulanir = True

        if haber["patron_aliyor"]:
            guven_skoru = min(10, guven_skoru + 3)
            etiket = "👔 [PATRON AVCISI: ŞİRKET GERİ ALIMI]"
            trend_notu = "✅ Trend de destekliyor" if trend_onayli else "⚠️ Teknik trend zayıf, ama içeriden alım çok güçlü"
            notlar = f"📢 KAP/Haber: _{haber['baslik']}_\n📈 Teknik Puan: {teknik_puan:.0f}/100\n{trend_notu}"
            puan_barajı_uygulanir = False
        elif balina_hareketi:
            guven_skoru = min(10, guven_skoru + 2)
            etiket = "🐋 [BALİNA RADARI: DEV PARA GİRİŞİ]"
            notlar = f"🚨 Anormal Hacim: Normalin {hacim_kati:.1f} katı!\n📈 Teknik Puan: {teknik_puan:.0f}/100"
            if haber["pozitif"]: guven_skoru = min(10, guven_skoru + 1); notlar += f"\n📰 Destekleyici Haber: _{haber['baslik']}_"
            puan_barajı_uygulanir = False
        elif haber["pozitif"] and teknik_puan >= 60:
            guven_skoru = min(10, guven_skoru + 1)
            etiket = "💥 [ÇİFTE KAVRULMUŞ: TEKNİK + HABER]"
            notlar = f"📈 Güçlü Teknik ({teknik_puan:.0f}/100)\n📰 Kilit Haber: _{haber['baslik']}_"
        elif haber["pozitif"]:
            etiket = "🚨 [SICAK HABER RADARI]"
            notlar = f"⚠️ Teknik Zayıf ({teknik_puan:.0f}/100) ama HABER ÇOK GÜÇLÜ!\n📰 Haber: _{haber['baslik']}_"
            guven_skoru = max(guven_skoru, 6); puan_barajı_uygulanir = False
        elif trend_onayli and teknik_puan >= 60:
            etiket = "💎 [ELMAS SİNYAL - SADECE TEKNİK]"
            notlar = f"📈 Kusursuz Teknik ({teknik_puan:.0f}/100)\n📰 Haber Akışı: Olağan/Sakin"
        else: return None

        if puan_barajı_uygulanir and guven_skoru < MIN_GUVEN_SKORU: return None

        stop_loss, hedef_1, hedef_2 = fiyat - (atr_degeri * 1.5), fiyat + (atr_degeri * 2), fiyat + (atr_degeri * 3)
        risk_birim = fiyat - stop_loss
        rr1, rr2 = ((hedef_1 - fiyat) / risk_birim if risk_birim > 0 else 0), ((hedef_2 - fiyat) / risk_birim if risk_birim > 0 else 0)
        lot = pozisyon_buyuklugu_hesapla(fiyat, stop_loss)

        savas_plani = f"⚔️ **DİNAMİK SAVAŞ PLANI (ATR ONAYLI)**\n🟢 **Giriş:** {fiyat:.2f} TL\n🎯 **Hedef 1:** {hedef_1:.2f} TL\n🚀 **Hedef 2:** {hedef_2:.2f} TL\n🛑 **Stop-Loss:** {stop_loss:.2f} TL *(~%{((fiyat - stop_loss) / fiyat) * 100:.1f})*"
        ek_bilgi = f"\n\n📐 **Risk/Ödül:** 1:{rr1:.1f} (H1) | 1:{rr2:.1f} (H2)\n💰 **Pozisyon Büyüklüğü** ({PORTFOY_BUYUKLUGU_TL:,.0f} TL / %{MAKS_RISK_YUZDESI*100:.0f} risk): {lot} lot (~{lot*fiyat:,.0f} TL)\n🏷️ **Sınıf:** {siniflandirma_etiketi(guven_skoru)}\n📊 **Nihai Skor Dağılımı:** Trend {trend_p:.0f}/{TREND_MAX_PUAN} | Momentum {momentum_p:.0f}/{MOMENTUM_MAX_PUAN} | Hacim {hacim_p:.0f}/{HACIM_MAX_PUAN} | Volatilite {volatilite_p:.0f}/{VOLATILITE_MAX_PUAN} | Temel {temel_p:.0f}/{TEMEL_MAX_PUAN} | Haber {haber_p:.0f}/{HABER_MAX_PUAN} → **{nihai_skor:.0f}/100**"

        mesaj = f"{etiket}\n\n🏷️ Hisse: {hisse}\n\n{notlar}\n\n{savas_plani}{ek_bilgi}\n\n🎯 **GÜVEN SKORU: {guven_skoru}/10**\n{'⭐' * guven_skoru + '⚪' * (10 - guven_skoru)}"

        if basit_mesaj_gonder(mesaj):
            with tarama_durum_kilidi:
                son_sinyaller[hisse] = datetime.now(TR_TZ).isoformat()
            log.info(f"✅ Sinyal gönderildi: {hisse} ({etiket}) — Skor: {nihai_skor:.0f}/100")
            return hisse

    except requests.exceptions.ConnectionError as error:
        api_warning("Yahoo analysis", error, "[%s] Yahoo bağlantısı kurulamadı; bu tur atlanıyor", hisse)
        return None
    except requests.exceptions.Timeout as error:
        api_warning("Yahoo analysis", error, "[%s] İstek zaman aşımına uğradı; bu tur atlanıyor", hisse)
        return None
    except StorageError:
        raise  # State corruption must prevent the coordinator from committing this scan.
    except (requests.RequestException, ValueError, KeyError, TypeError, IndexError) as error:
        api_warning("Yahoo analysis", error, "[%s] Analysis unavailable: %s", hisse, type(error).__name__)
        return None
    except Exception as error:
        log.error("[%s] Unexpected analysis failure: %s", hisse, type(error).__name__)
        return None
