"""Indicators responsibilities extracted from the original bot."""
from .config import ATR_PERIYODU, DESTEK_DIRENC_LOOKBACK, PIVOT_PENCERE
import numpy as np
import pandas as pd
import math

def hesapla_ema(seri: pd.Series, periyot: int) -> pd.Series: return seri.ewm(span=periyot, adjust=False).mean()


def hesapla_rsi_wilder(close: pd.Series, periyot: int = 14) -> pd.Series:
    delta = close.diff()
    gain, loss = delta.where(delta > 0, 0.0), -delta.where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1/periyot, min_periods=periyot, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/periyot, min_periods=periyot, adjust=False).mean()
    return 100 - (100 / (1 + avg_gain / avg_loss))


def hesapla_true_range(df: pd.DataFrame) -> pd.Series:
    high_low = df["High"] - df["Low"]
    high_close, low_close = (df["High"] - df["Close"].shift()).abs(), (df["Low"] - df["Close"].shift()).abs()
    return pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)


def hesapla_atr_wilder(df: pd.DataFrame, periyot: int = ATR_PERIYODU) -> pd.Series:
    return hesapla_true_range(df).ewm(alpha=1/periyot, min_periods=periyot, adjust=False).mean()


def hesapla_adx(df: pd.DataFrame, periyot: int = 14) -> pd.Series:
    up_move, down_move = df["High"].diff(), -df["Low"].diff()
    pos_dm = pd.Series(np.where((up_move > down_move) & (up_move > 0), up_move, 0.0), index=df.index)
    neg_dm = pd.Series(np.where((down_move > up_move) & (down_move > 0), down_move, 0.0), index=df.index)
    atr = hesapla_atr_wilder(df, periyot)
    pos_di = 100 * (pos_dm.ewm(alpha=1/periyot, min_periods=periyot, adjust=False).mean() / atr)
    neg_di = 100 * (neg_dm.ewm(alpha=1/periyot, min_periods=periyot, adjust=False).mean() / atr)
    dx = 100 * (pos_di - neg_di).abs() / (pos_di + neg_di).replace(0, np.nan)
    return dx.ewm(alpha=1/periyot, min_periods=periyot, adjust=False).mean()


def hesapla_macd(close: pd.Series, hizli: int = 12, yavas: int = 26, sinyal: int = 9):
    macd = hesapla_ema(close, hizli) - hesapla_ema(close, yavas)
    return macd, hesapla_ema(macd, sinyal)


def hesapla_bollinger(close: pd.Series, periyot: int = 20, std_carpani: float = 2.0):
    orta, std = close.rolling(periyot).mean(), close.rolling(periyot).std()
    return orta + std_carpani * std, orta, orta - std_carpani * std


def hesapla_obv(close: pd.Series, volume: pd.Series) -> pd.Series:
    return (np.sign(close.diff()).fillna(0) * volume).cumsum()


def hesapla_mfi(df: pd.DataFrame, periyot: int = 14) -> pd.Series:
    tp = (df["High"] + df["Low"] + df["Close"]) / 3
    rmf, tp_diff = tp * df["Volume"], tp.diff()
    poz, neg = rmf.where(tp_diff > 0, 0.0).rolling(periyot).sum(), rmf.where(tp_diff < 0, 0.0).rolling(periyot).sum()
    return 100 - (100 / (1 + poz / neg.replace(0, np.nan)))


def hesapla_stoch_rsi(rsi: pd.Series, periyot: int = 14):
    min_rsi, max_rsi = rsi.rolling(periyot).min(), rsi.rolling(periyot).max()
    stoch = (rsi - min_rsi) / (max_rsi - min_rsi).replace(0, np.nan)
    k = (stoch * 100).rolling(3).mean()
    return k, k.rolling(3).mean()


def hesapla_cmf(df: pd.DataFrame, periyot: int = 20) -> pd.Series:
    aralik = (df["High"] - df["Low"]).replace(0, np.nan)
    carpan = ((df["Close"] - df["Low"]) - (df["High"] - df["Close"])) / aralik
    return (carpan * df["Volume"]).rolling(periyot).sum() / df["Volume"].rolling(periyot).sum()


def hesapla_vwap_yaklasik(df: pd.DataFrame, periyot: int = 20) -> pd.Series:
    tipik = (df["High"] + df["Low"] + df["Close"]) / 3
    return (tipik * df["Volume"]).rolling(periyot).sum() / df["Volume"].rolling(periyot).sum()


def hesapla_donchian(df: pd.DataFrame, periyot: int = 20):
    return df["High"].rolling(periyot).max(), df["Low"].rolling(periyot).min()


def hesapla_historical_volatilite(close: pd.Series, periyot: int = 20) -> pd.Series:
    return np.log(close / close.shift(1)).rolling(periyot).std() * np.sqrt(252) * 100


def hesapla_supertrend(df: pd.DataFrame, periyot: int = 10, carpan: float = 3.0) -> pd.Series:
    atr = hesapla_atr_wilder(df, periyot)
    hl2 = (df["High"] + df["Low"]) / 2
    ust_temel, alt_temel = hl2 + carpan * atr, hl2 - carpan * atr
    ust_bant, alt_bant, yon, close = ust_temel.copy(), alt_temel.copy(), pd.Series(1, index=df.index, dtype=int), df["Close"]

    for i in range(1, len(df)):
        # Seed the first valid ATR bands; NaN warmup must not propagate forever.
        if pd.isna(atr.iloc[i]):
            continue
        if pd.isna(ust_bant.iloc[i-1]) or pd.isna(alt_bant.iloc[i-1]):
            ust_bant.iloc[i], alt_bant.iloc[i] = ust_temel.iloc[i], alt_temel.iloc[i]
            continue
        ust_bant.iloc[i] = ust_temel.iloc[i] if ust_temel.iloc[i] < ust_bant.iloc[i-1] or close.iloc[i-1] > ust_bant.iloc[i-1] else ust_bant.iloc[i-1]
        alt_bant.iloc[i] = alt_temel.iloc[i] if alt_temel.iloc[i] > alt_bant.iloc[i-1] or close.iloc[i-1] < alt_bant.iloc[i-1] else alt_bant.iloc[i-1]
        yon.iloc[i] = 1 if close.iloc[i] > ust_bant.iloc[i-1] else -1 if close.iloc[i] < alt_bant.iloc[i-1] else yon.iloc[i-1]
    return yon


def hesapla_ichimoku_basit(df: pd.DataFrame):
    high, low = df["High"], df["Low"]
    tenkan = (high.rolling(9).max() + low.rolling(9).min()) / 2
    kijun = (high.rolling(26).max() + low.rolling(26).min()) / 2
    return tenkan, kijun, ((tenkan + kijun) / 2).shift(26), ((high.rolling(52).max() + low.rolling(52).min()) / 2).shift(26)


def higher_high_higher_low_mi(df: pd.DataFrame, pencere: int = PIVOT_PENCERE) -> bool:
    if len(df) < pencere * 2 + 3: return False
    genislik = 2 * pencere + 1
    ph, pl = df.loc[df["High"] == df["High"].rolling(genislik, center=True).max(), "High"].dropna(), df.loc[df["Low"] == df["Low"].rolling(genislik, center=True).min(), "Low"].dropna()
    if len(ph) < 2 or len(pl) < 2: return False
    return bool(ph.iloc[-1] > ph.iloc[-2] and pl.iloc[-1] > pl.iloc[-2])


def guclu_destek_direnc_hesapla(df: pd.DataFrame, lookback: int = DESTEK_DIRENC_LOOKBACK, fractal_pencere: int = PIVOT_PENCERE) -> tuple[float, float]:
    pencere = df.tail(lookback)
    genislik = 2 * fractal_pencere + 1
    ph, pl = pencere.loc[pencere["High"] == pencere["High"].rolling(genislik, center=True).max(), "High"].dropna(), pencere.loc[pencere["Low"] == pencere["Low"].rolling(genislik, center=True).min(), "Low"].dropna()
    direnc = float(ph.max()) if len(ph) else float(pencere["High"].max())
    destek = float(pl.min()) if len(pl) else float(pencere["Low"].min())
    return destek, direnc


def guvenli_sayi(deger, varsayilan=None):
    if isinstance(deger, dict):
        deger = deger.get("raw")
    if isinstance(deger, (int, float, np.number)) and not isinstance(deger, (bool, np.bool_)):
        try:
            return float(deger) if math.isfinite(deger) else varsayilan
        except OverflowError:
            return varsayilan
    return varsayilan
