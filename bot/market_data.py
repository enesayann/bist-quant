"""Market data responsibilities extracted from the original bot."""
from .config import api_warning
from .http_client import session
from .indicators import (
    guvenli_sayi,
    hesapla_adx,
    hesapla_atr_wilder,
    hesapla_ema,
    hesapla_macd,
    hesapla_obv,
    hesapla_rsi_wilder,
)
from typing import Optional
import pandas as pd
import random
import time
import requests


class MarketDataError(ValueError):
    """Yahoo data is missing, malformed, or unsuitable for analysis."""


def chart_quote(data):
    try:
        chart = data["chart"]
        if chart.get("error"):
            raise MarketDataError("Yahoo chart reported an API error")
        result = chart["result"][0]
        quote = result["indicators"]["quote"][0]
        if not isinstance(result, dict) or not isinstance(quote, dict):
            raise MarketDataError("Invalid Yahoo result/quote")
        return result, quote
    except (KeyError, IndexError, TypeError, AttributeError) as error:
        raise MarketDataError("Missing Yahoo chart result or quote") from error


def chart_frame(data, minimum=30):
    result, quote = chart_quote(data)
    arrays = {column: quote.get(key) for column, key in
              (("High", "high"), ("Low", "low"), ("Close", "close"), ("Volume", "volume"))}
    if any(not isinstance(values, list) for values in arrays.values()):
        raise MarketDataError("Missing Yahoo OHLCV arrays")
    if len({len(values) for values in arrays.values()}) != 1:
        raise MarketDataError("Yahoo OHLCV array lengths differ")
    if any(value is not None and guvenli_sayi(value) is None
           for values in arrays.values() for value in values):
        raise MarketDataError("Non-finite or non-numeric Yahoo OHLCV value")
    df = pd.DataFrame(arrays).dropna()
    if len(df) < minimum:
        raise MarketDataError("Insufficient complete Yahoo candles")
    if (df[["High", "Low", "Close"]] <= 0).any().any() or (df["Volume"] < 0).any():
        raise MarketDataError("Invalid Yahoo price or volume")
    if ((df["High"] < df["Low"]) | (df["Close"] > df["High"]) | (df["Close"] < df["Low"])).any():
        raise MarketDataError("Inconsistent Yahoo OHLC candles")
    return result, df


def temel_verileri_getir(hisse):
    """Missing fundamentals earn no points; do not fabricate a P/E comparison."""
    try:
        response = session.get(f"https://query2.finance.yahoo.com/v10/finance/quoteSummary/{hisse}?modules=summaryDetail,defaultKeyStatistics", timeout=15)
        response.raise_for_status()
        payload = response.json()["quoteSummary"]
        if payload.get("error"):
            raise MarketDataError("Yahoo fundamentals reported an API error")
        result = payload["result"][0]
        summary, stats = result.get("summaryDetail", {}), result.get("defaultKeyStatistics", {})
        return (guvenli_sayi(summary.get("trailingPE")), guvenli_sayi(stats.get("pegRatio")),
                guvenli_sayi(stats.get("priceToBook")), guvenli_sayi(summary.get("forwardPE")),
                guvenli_sayi(summary.get("dividendYield")))
    except (requests.RequestException, ValueError, KeyError, IndexError, TypeError, AttributeError) as error:
        api_warning("Yahoo fundamentals", error, "[%s] Fundamentals unavailable (no fundamental points): %s", hisse, type(error).__name__)
        return None, None, None, None, None

def tek_hisse_veri_getir(hisse: str) -> Optional[pd.DataFrame]:
    """Manuel komutlar (/al, /pozisyonlar, /durum) ve pozisyon takibi için hafif
    veri çekimi: tam taramadaki ağır indikatörler (Ichimoku, SuperTrend, CMF vb.)
    burada gereksiz, sadece TP/SL/trend/hacim kontrolü için gerekenler hesaplanır."""
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{hisse}?interval=1d&range=6mo"
        r = session.get(url, timeout=15)
        r.raise_for_status()
        data = r.json()
        _, df = chart_frame(data)
        df["EMA20"], df["EMA50"] = hesapla_ema(df["Close"], 20), hesapla_ema(df["Close"], 50)
        df["RSI"] = hesapla_rsi_wilder(df["Close"])
        df["ATR"] = hesapla_atr_wilder(df)
        df["ADX"] = hesapla_adx(df)
        df["MACD"], df["MACD_Sinyal"] = hesapla_macd(df["Close"])
        df["OBV"] = hesapla_obv(df["Close"], df["Volume"])
        df["Vol_20"] = df["Volume"].rolling(20).mean()
        return df
    except (requests.RequestException, ValueError) as e:
        api_warning("Yahoo position", e, "[%s] Pozisyon verisi kullanılamıyor: %s", hisse, type(e).__name__)
        return None


def gunluk_fiyat_degisimini_getir(hisse: str) -> Optional[tuple[str, float, float]]:
    """Sadece gün sonu özeti için hafif bir istek: son 5 günlük kapanışlardan
    son iki günü karşılaştırıp günlük yüzde değişimi hesaplar."""
    try:
        time.sleep(random.uniform(0.1, 0.6))  # 🚦 jitter: 8 thread aynı anda patlamasın
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{hisse}?interval=1d&range=5d"
        r = session.get(url, timeout=15)
        r.raise_for_status()
        data = r.json()
        _, quote = chart_quote(data)
        if not isinstance(quote.get("close"), list):
            raise MarketDataError("Missing Yahoo close array")
        closes = [guvenli_sayi(c) for c in quote["close"] if c is not None]
        if any(c is None or c <= 0 for c in closes):
            raise MarketDataError("Invalid Yahoo close prices")
        if len(closes) < 2:
            raise MarketDataError("Insufficient Yahoo close prices")
        fiyat, onceki = closes[-1], closes[-2]
        return hisse, fiyat, ((fiyat - onceki) / onceki) * 100
    except (requests.RequestException, ValueError) as error:
        api_warning("Yahoo daily", error, "[%s] Günlük fiyat değişimi alınamadı: %s", hisse, type(error).__name__)
        return None
