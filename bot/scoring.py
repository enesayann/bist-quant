"""Scoring responsibilities extracted from the original bot."""
from .config import (
    ADX_ESIK,
    ADX_GUCLU_TREND_PUAN,
    BALINA_HACIM_CARPANI,
    BOLLINGER_ALT_BANT_DONUS_PUAN,
    CMF_ESIK,
    CMF_POZITIF_PUAN,
    DESTEK_DIRENC_MAX_AYAR,
    DESTEK_DIRENC_YUZDE,
    DONCHIAN_KIRILIM_PUAN,
    DONCHIAN_YAKINLIK_YUZDE,
    EMA_KISMI_DIZILIM_PUAN,
    EMA_TAM_DIZILIM_PUAN,
    FK_DUSUK_PUAN,
    FK_ESIK,
    FORWARD_PE_IYILESME_PUAN,
    HABER_MAX_PUAN,
    HABER_POZITIF_NET_PUAN,
    HACIM_MAX_PUAN,
    HACIM_PATLAMASI_CARPANI,
    HACIM_PATLAMASI_PUAN,
    HH_HL_YAPI_PUAN,
    HISTORICAL_VOL_SAGLIKLI_PUAN,
    HIST_VOL_MAKS_YUZDE,
    HIST_VOL_MIN_YUZDE,
    ICHIMOKU_BULUT_USTU_PUAN,
    KAP_KAYNAKLI_EK_PUAN,
    MACD_DEVAM_BULLISH_PUAN,
    MACD_TAZE_KESISIM_PUAN,
    MFI_SAGLIKLI_BANT_PUAN,
    MOMENTUM_MAX_PUAN,
    OBV_YUKSELEN_TREND_PUAN,
    PATRON_OLAY_PUAN,
    PB_ESIK,
    PB_UYGUN_PUAN,
    PEG_ESIK,
    PEG_UYGUN_PUAN,
    RSI_SAGLIKLI_BANT_PUAN,
    RSI_YUKSELEN_YON_PUAN,
    SON_5_GUN_HACIM_ARTISI_PUAN,
    STOCH_RSI_DONUS_PUAN,
    SUPERTREND_YUKARI_PUAN,
    TEMEL_MAX_PUAN,
    TEMETTU_VAR_PUAN,
    TREND_MAX_PUAN,
    VOLATILITE_MAX_PUAN,
    VWAP_USTUNDE_PUAN,
)
from .indicators import guvenli_sayi, higher_high_higher_low_mi
import pandas as pd

def trend_puani_hesapla(df: pd.DataFrame, fiyat: float, ema200_var: bool, ichimoku_var: bool) -> tuple[float, dict]:
    puan, detay = 0.0, {}
    ema20, ema50 = df["EMA20"].iloc[-1], df["EMA50"].iloc[-1]
    if ema200_var and fiyat > ema20 > ema50 > df["EMA200"].iloc[-1]: puan += EMA_TAM_DIZILIM_PUAN; detay["ema_dizilimi"] = "tam"
    elif fiyat > ema20 > ema50: puan += EMA_KISMI_DIZILIM_PUAN; detay["ema_dizilimi"] = "kısmi"
    if df["SuperTrend_Yon"].iloc[-1] == 1: puan += SUPERTREND_YUKARI_PUAN; detay["supertrend"] = "yukarı"
    if pd.notna(df["ADX"].iloc[-1]) and df["ADX"].iloc[-1] > ADX_ESIK: puan += ADX_GUCLU_TREND_PUAN; detay["adx"] = round(df["ADX"].iloc[-1], 1)
    if higher_high_higher_low_mi(df): puan += HH_HL_YAPI_PUAN; detay["swing_yapisi"] = "HH-HL"
    if ichimoku_var and fiyat > max(df["Senkou_A"].iloc[-1], df["Senkou_B"].iloc[-1]) and df["Tenkan"].iloc[-1] > df["Kijun"].iloc[-1]:
        puan += ICHIMOKU_BULUT_USTU_PUAN; detay["ichimoku"] = "bulut üstü"
    return min(TREND_MAX_PUAN, puan), detay


def momentum_puani_hesapla(df: pd.DataFrame, fiyat: float) -> tuple[float, dict]:
    puan, detay = 0.0, {}
    rsi = df["RSI"].iloc[-1]
    if pd.notna(rsi) and 30 < rsi < 60: puan += RSI_SAGLIKLI_BANT_PUAN
    if len(df["RSI"].tail(3)) == 3 and df["RSI"].tail(3).is_monotonic_increasing: puan += RSI_YUKSELEN_YON_PUAN; detay["rsi"] = "yükseliyor"
    macd, sinyal = df["MACD"], df["MACD_Sinyal"]
    if len(macd) >= 2:
        if macd.iloc[-2] < sinyal.iloc[-2] and macd.iloc[-1] > sinyal.iloc[-1]: puan += MACD_TAZE_KESISIM_PUAN; detay["macd"] = "taze kesişim"
        elif macd.iloc[-1] > sinyal.iloc[-1]: puan += MACD_DEVAM_BULLISH_PUAN
    k, d = df["StochRSI_K"], df["StochRSI_D"]
    if len(k) >= 2 and k.iloc[-2] < d.iloc[-2] and k.iloc[-1] > d.iloc[-1] and k.iloc[-1] < 50: puan += STOCH_RSI_DONUS_PUAN
    alt_bant = df["BB_Alt"].iloc[-1]
    if pd.notna(alt_bant) and fiyat >= alt_bant and df["Close"].iloc[-2] < fiyat and (fiyat - alt_bant)/fiyat < 0.03: puan += BOLLINGER_ALT_BANT_DONUS_PUAN
    return min(MOMENTUM_MAX_PUAN, puan), detay


def hacim_puani_hesapla(df: pd.DataFrame) -> tuple[float, dict]:
    puan, detay = 0.0, {}
    if len(df["OBV"]) >= 10 and df["OBV"].iloc[-1] > df["OBV"].iloc[-10]: puan += OBV_YUKSELEN_TREND_PUAN
    vol, ort_vol = df["Volume"].iloc[-1], df["Vol_20"].iloc[-1]
    if pd.notna(ort_vol) and ort_vol > 0 and vol > ort_vol * HACIM_PATLAMASI_CARPANI: puan += HACIM_PATLAMASI_PUAN
    if df["Volume"].tail(5).mean() > df["Volume"].tail(10).head(5).mean(): puan += SON_5_GUN_HACIM_ARTISI_PUAN
    if pd.notna(df["MFI"].iloc[-1]) and 20 < df["MFI"].iloc[-1] < 80: puan += MFI_SAGLIKLI_BANT_PUAN
    if pd.notna(df["CMF"].iloc[-1]) and df["CMF"].iloc[-1] > CMF_ESIK: puan += CMF_POZITIF_PUAN
    if pd.notna(df["VWAP_Yaklasik"].iloc[-1]) and df["Close"].iloc[-1] > df["VWAP_Yaklasik"].iloc[-1]: puan += VWAP_USTUNDE_PUAN
    return min(HACIM_MAX_PUAN, puan), detay


def volatilite_puani_hesapla(df: pd.DataFrame, fiyat: float) -> tuple[float, dict]:
    puan, detay = 0.0, {}
    if pd.notna(df["Donchian_Ust"].iloc[-1]) and abs(fiyat - df["Donchian_Ust"].iloc[-1])/fiyat <= DONCHIAN_YAKINLIK_YUZDE: puan += DONCHIAN_KIRILIM_PUAN
    if pd.notna(df["Hist_Vol"].iloc[-1]) and HIST_VOL_MIN_YUZDE < df["Hist_Vol"].iloc[-1] < HIST_VOL_MAKS_YUZDE: puan += HISTORICAL_VOL_SAGLIKLI_PUAN
    return min(VOLATILITE_MAX_PUAN, puan), detay


def temel_puani_hesapla(fk, peg, pb, forward_pe, temettu) -> tuple[float, dict]:
    fk, peg, pb, forward_pe, temettu = map(guvenli_sayi, (fk, peg, pb, forward_pe, temettu))
    puan, detay = 0.0, {}
    if fk and 0 < fk < FK_ESIK: puan += FK_DUSUK_PUAN
    if peg and 0 < peg < PEG_ESIK: puan += PEG_UYGUN_PUAN
    if pb and 0 < pb < PB_ESIK: puan += PB_UYGUN_PUAN
    if forward_pe and fk and 0 < forward_pe < fk: puan += FORWARD_PE_IYILESME_PUAN
    if temettu and temettu > 0: puan += TEMETTU_VAR_PUAN
    return min(TEMEL_MAX_PUAN, puan), detay


def haber_puani_hesapla(haber: dict) -> tuple[float, dict]:
    puan, detay = 0.0, {}
    if haber["pozitif"]: puan += HABER_POZITIF_NET_PUAN
    if haber["kap_kaynakli"]: puan += KAP_KAYNAKLI_EK_PUAN
    if haber["patron_aliyor"]: puan += PATRON_OLAY_PUAN
    kap_puani = guvenli_sayi(haber["kap_olay_puani"])
    if kap_puani is None:
        raise ValueError("Invalid news event score")
    puan += kap_puani
    return max(0.0, min(HABER_MAX_PUAN, puan)), detay


def destek_direnc_ayarlamasi(fiyat: float, destek: float, direnc: float) -> tuple[float, str]:
    if guvenli_sayi(fiyat) is None or fiyat <= 0:
        raise ValueError("Price must be finite and positive")
    if direnc > 0 and abs(fiyat - direnc) / fiyat <= DESTEK_DIRENC_YUZDE: return -DESTEK_DIRENC_MAX_AYAR, "dirence çok yakın (risk)"
    if destek > 0 and abs(fiyat - destek) / fiyat <= DESTEK_DIRENC_YUZDE: return DESTEK_DIRENC_MAX_AYAR, "desteğe yakın (fırsat)"
    return 0.0, "nötr bölge"


def toplam_skorlar(trend, momentum, hacim, volatilite, temel, haber, ayar):
    """Original final and technical score formulas, with finite-value validation."""
    values = (trend, momentum, hacim, volatilite, temel, haber, ayar)
    if any(guvenli_sayi(value) is None for value in values):
        raise ValueError("Non-finite category score")
    toplam = trend + momentum + hacim + volatilite + temel
    nihai = max(0.0, min(100.0, toplam + haber + ayar))
    maksimum = TREND_MAX_PUAN + MOMENTUM_MAX_PUAN + HACIM_MAX_PUAN + VOLATILITE_MAX_PUAN + TEMEL_MAX_PUAN
    teknik = max(0.0, min(100.0, toplam / maksimum * 100 + ayar))
    return nihai, teknik


def siniflandirma_etiketi(guven_skoru: int) -> str:
    return "🟢 LONG" if guven_skoru >= 8 else "🟡 EARLY" if guven_skoru >= 6 else "⚪ WATCHLIST" if guven_skoru >= 4 else "🔴 RISKY"


def tut_azalt_cik_skoru_hesapla(df: pd.DataFrame, fiyat: float, poz: dict, haber_negatif: bool, haber_pozitif: bool) -> tuple[int, dict]:
    """0-100 arası canlı 'Tut/Azalt/Çık' skoru. 50 puan nötr taban üzerine:
    Trend (±20), Momentum/RSI (±15), Hacim (±15), Hedefe-mesafe (±15), Haber (-15/+8)
    faktörleri eklenip 0-100 aralığına sıkıştırılır."""
    detay = {}
    skor = 50.0

    ema20, ema50 = df["EMA20"].iloc[-1], df["EMA50"].iloc[-1]
    trend_pozitif = ema20 > ema50
    trend_f = 8 if trend_pozitif else -8
    macd_pozitif = df["MACD"].iloc[-1] > df["MACD_Sinyal"].iloc[-1]
    trend_f += 6 if macd_pozitif else -6
    adx_son = df["ADX"].iloc[-1]
    if pd.notna(adx_son) and adx_son > ADX_ESIK:
        trend_f += 6 if trend_pozitif else -6
    skor += trend_f
    detay["trend_faktoru"] = trend_f

    rsi_son = df["RSI"].iloc[-1]
    if pd.notna(rsi_son):
        momentum_f = 10 if 45 < rsi_son < 70 else -5 if rsi_son >= 70 else -10
    else:
        momentum_f = 0
    skor += momentum_f
    detay["momentum_faktoru"] = momentum_f

    mevcut_hacim, ort_hacim = df["Volume"].iloc[-1], df["Vol_20"].iloc[-1]
    hacim_kati = (mevcut_hacim / ort_hacim) if pd.notna(ort_hacim) and ort_hacim > 0 else 0
    onceki_kapanis = df["Close"].iloc[-2]
    obv_yukseliyor = len(df) >= 10 and df["OBV"].iloc[-1] > df["OBV"].iloc[-10]
    if hacim_kati >= BALINA_HACIM_CARPANI and fiyat < onceki_kapanis:
        hacim_f = -15
    elif fiyat > onceki_kapanis and obv_yukseliyor:
        hacim_f = 10
    else:
        hacim_f = 0
    skor += hacim_f
    detay["hacim_faktoru"] = hacim_f

    giris, stop, hedef2 = poz["giris_fiyati"], poz["guncel_stop"], poz["tp2"]
    if fiyat >= giris:
        ilerleme = min(1.0, (fiyat - giris) / (hedef2 - giris)) if hedef2 > giris else 0
        hedef_f = 15 * ilerleme
    else:
        gerileme = min(1.0, (giris - fiyat) / (giris - stop)) if giris > stop else 0
        hedef_f = -15 * gerileme
    skor += hedef_f
    detay["hedef_mesafe_faktoru"] = round(hedef_f, 1)

    haber_f = -15 if haber_negatif else (8 if haber_pozitif else 0)
    skor += haber_f
    detay["haber_faktoru"] = haber_f

    return int(max(0, min(100, round(skor)))), detay


def skor_etiketi(skor: int) -> str:
    if skor >= 70:
        return "🟢 Tut"
    if skor >= 40:
        return "🟡 Dikkat"
    return "🔴 Çıkmayı değerlendir"
