"""Causal indicators and the live strategy's neutral-news decision branches."""
from dataclasses import asdict, dataclass

import pandas as pd

from bot import config as live, indicators as ind, scoring


def confirmed_pivots(frame, window=live.PIVOT_PENCERE):
    """Return pivot values only after `window` subsequent candles confirm them.

    A trailing 2*w+1 window compares its middle candle with the whole window.
    Values are indexed by confirmation date, never backdated to pivot date.
    """
    width = 2 * window + 1
    highs, lows = frame.High.shift(window), frame.Low.shift(window)
    return (highs[highs == frame.High.rolling(width).max()].dropna(),
            lows[lows == frame.Low.rolling(width).min()].dropna())


def support_resistance(history, lookback=live.DESTEK_DIRENC_LOOKBACK):
    recent = history.tail(lookback)
    highs, lows = confirmed_pivots(recent)
    return (float(lows.min() if len(lows) else recent.Low.min()),
            float(highs.max() if len(highs) else recent.High.max()))


def prepare_indicators(frame):
    """Only trailing rolling/EWM/positive-shift calculations run on full data.

    No pivots, support/resistance or decision is computed on the full series.
    Future rows cannot change any earlier row of these causal indicators.
    """
    df = frame.copy()
    close = df.Close
    df['SMA_20'], df['SMA_50'] = close.rolling(20).mean(), close.rolling(50).mean()
    for period in (20, 50, 200):
        df[f'EMA{period}'] = ind.hesapla_ema(close, period)
    df['Vol_20'] = df.Volume.rolling(20).mean()
    df['RSI'] = ind.hesapla_rsi_wilder(close)
    df['ATR'] = ind.hesapla_atr_wilder(df)
    df['ADX'] = ind.hesapla_adx(df)
    df['MACD'], df['MACD_Sinyal'] = ind.hesapla_macd(close)
    df['BB_Ust'], df['BB_Orta'], df['BB_Alt'] = ind.hesapla_bollinger(close)
    df['OBV'] = ind.hesapla_obv(close, df.Volume)
    df['MFI'], df['CMF'] = ind.hesapla_mfi(df), ind.hesapla_cmf(df)
    df['StochRSI_K'], df['StochRSI_D'] = ind.hesapla_stoch_rsi(df.RSI)
    df['VWAP_Yaklasik'] = ind.hesapla_vwap_yaklasik(df)
    df['Donchian_Ust'], df['Donchian_Alt'] = ind.hesapla_donchian(df)
    df['Hist_Vol'] = ind.hesapla_historical_volatilite(close)
    df['SuperTrend_Yon'] = ind.hesapla_supertrend(df)
    df['Tenkan'], df['Kijun'], df['Senkou_A'], df['Senkou_B'] = ind.hesapla_ichimoku_basit(df)
    return df


@dataclass(frozen=True)
class Signal:
    ticker: str
    signal_date: str
    entry_reference_price: float
    trend_score: float
    momentum_score: float
    volume_score: float
    volatility_score: float
    fundamental_score: float
    news_score: float
    support_resistance_adjustment: float
    final_score: float
    technical_score: float
    confidence: int
    classification: str
    signal_type: str
    initial_stop: float
    tp1: float
    tp2: float
    atr_at_entry: float

    def to_dict(self):
        return asdict(self)


def signal_from_history(ticker, history):
    """Accept an enriched prefix ending at the completed signal candle."""
    if len(history) < live.MIN_VERI_UZUNLUGU:
        return None
    price, atr = float(history.Close.iloc[-1]), float(history.ATR.iloc[-1])
    if ind.guvenli_sayi(atr) is None or atr <= 0 or price - 1.5 * atr <= 0:
        return None
    # The live trend scorer's centered HH/HL is safe here: it receives ONLY
    # this prefix, so its last w candles cannot be unconfirmed pivots.
    trend, _ = scoring.trend_puani_hesapla(
        history, price, len(history) >= live.EMA200_ICIN_MIN_VERI,
        len(history) >= live.ICHIMOKU_ICIN_MIN_VERI)
    momentum, _ = scoring.momentum_puani_hesapla(history, price)
    volume, _ = scoring.hacim_puani_hesapla(history)
    volatility, _ = scoring.volatilite_puani_hesapla(history, price)
    support, resistance = support_resistance(history)
    adjustment, _ = scoring.destek_direnc_ayarlamasi(price, support, resistance)
    # Preserve the live 80-point denominator, including its 10-point
    # fundamental allowance. Do not rescale weights when data is absent.
    final, technical = scoring.toplam_skorlar(trend, momentum, volume, volatility, 0, 0, adjustment)
    confidence = min(10, int(technical / 10))
    average_volume = history.Vol_20.iloc[-1]
    whale = (average_volume > 0 and history.Volume.iloc[-1] / average_volume >= live.BALINA_HACIM_CARPANI
             and price > history.Close.iloc[-2])
    trend_confirmed = (
        (history.Close.tail(3) > history.SMA_20.tail(3)).all()
        and price > history.SMA_50.iloc[-1]
        and price > history.EMA20.iloc[-1] > history.EMA50.iloc[-1])
    if whale:
        confidence = min(10, confidence + 2)
        kind = 'WHALE'
    elif trend_confirmed and technical >= 60 and confidence >= live.MIN_GUVEN_SKORU:
        kind = 'TECHNICAL'
    else:
        return None
    return Signal(ticker, history.index[-1].date().isoformat(), price,
                  float(trend), float(momentum), float(volume), float(volatility), 0.0, 0.0,
                  float(adjustment), float(final), float(technical), confidence,
                  scoring.siniflandirma_etiketi(confidence), kind,
                  price - 1.5 * atr, price + 2 * atr, price + 3 * atr, atr)


def evaluate_signal(ticker, frame, as_of):
    """Public raw-data entry point: truncate BEFORE calculating indicators."""
    history = frame.loc[:pd.Timestamp(as_of)]
    return signal_from_history(ticker, prepare_indicators(history))
