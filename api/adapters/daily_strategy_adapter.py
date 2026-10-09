"""Reuse causal indicator preparation, category scoring and signal decisions.

No bot runtime, news cache, fundamental lookup, position or Telegram calls.
"""
from datetime import datetime, timedelta

import pandas as pd
import requests

from backtest.data import YahooProvider, clean_history
from backtest.signals import prepare_indicators, signal_from_history, support_resistance
from bot import config, scoring
from bot.market_data import MarketDataError

from api.errors import AnalysisError
from api.models import (
    AnalysisResponse, CacheInfo, DataQuality, Freshness, Indicators,
    Market, PricePoint, Risk, Scores, Strategy,
)


class BoundedSession:
    """API-owned transport; no shared bot sessions, retries or caches."""
    def __init__(self):
        self.session = requests.Session()
        self.session.headers['User-Agent'] = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36'
        self.session.headers['Accept'] = 'application/json, text/plain, */*'
        self.session.trust_env = False

    def get(self, url, **kwargs):
        kwargs['timeout'] = (3, 12)
        # Do not follow provider redirects into unbounded additional requests.
        kwargs['allow_redirects'] = False
        return self.session.get(url, **kwargs)

    def close(self):
        self.session.close()


class DailyStrategyAdapter:
    def __init__(self, provider=None, now=None):
        self.provider = provider
        self.now = now or (lambda: datetime.now(config.TR_TZ))

    def analyze(self, symbol, ttl_seconds=60):
        now = self.now().astimezone(config.TR_TZ)
        end = now.date() - timedelta(days=1)
        start = (pd.Timestamp(end) - pd.DateOffset(years=2)).date()
        session = None
        try:
            provider = self.provider
            if provider is None:
                session = BoundedSession()
                provider = YahooProvider(session=session)
            frame = provider.fetch(symbol, start.isoformat(), end.isoformat())
            if not isinstance(frame, pd.DataFrame) or frame.empty:
                raise AnalysisError('no_data', 'No daily candles are available for this ticker.', 422)
            # Defensive boundary for injectable providers. YahooProvider already cleans.
            quality = frame.attrs.get('validation')
            frame = clean_history(frame, symbol)
            if quality is None:
                quality = frame.attrs['validation']
            if len(frame) < config.MIN_VERI_UZUNLUGU:
                raise AnalysisError('insufficient_data', f'At least {config.MIN_VERI_UZUNLUGU} usable daily candles are required.', 422)
            if frame.index[-1].date() > end or frame.index[0].date() < start:
                raise AnalysisError('invalid_data', 'Provider returned candles outside the requested completed-bar period.')
            return self._response(symbol, frame, quality, now, ttl_seconds)
        except requests.Timeout as error:
            raise AnalysisError('provider_timeout', 'The market-data provider timed out. Try again later.', 504) from error
        except requests.RequestException as error:
            raise AnalysisError('provider_unavailable', 'The market-data provider is unavailable. Try again later.') from error
        except MarketDataError as error:
            no_data = 'no historical candles' in str(error).lower() or 'missing yahoo historical timestamps' in str(error).lower()
            raise AnalysisError('no_data' if no_data else 'invalid_data',
                                'No daily candles are available for this ticker.' if no_data else 'Provider candles failed OHLCV validation; no analysis was produced.',
                                422 if no_data else 502) from error
        finally:
            if session is not None:
                session.close()

    def _response(self, symbol, frame, quality, now, ttl_seconds):
        history = prepare_indicators(frame)
        price, previous = float(history.Close.iloc[-1]), float(history.Close.iloc[-2])
        trend, _ = scoring.trend_puani_hesapla(history, price, len(history) >= config.EMA200_ICIN_MIN_VERI,
                                              len(history) >= config.ICHIMOKU_ICIN_MIN_VERI)
        momentum, _ = scoring.momentum_puani_hesapla(history, price)
        volume, _ = scoring.hacim_puani_hesapla(history)
        volatility, _ = scoring.volatilite_puani_hesapla(history, price)
        support, resistance = support_resistance(history)
        adjustment, _ = scoring.destek_direnc_ayarlamasi(price, support, resistance)
        final, technical = scoring.toplam_skorlar(trend, momentum, volume, volatility, 0, 0, adjustment)
        signal = signal_from_history(symbol, history)
        last = history.iloc[-1]
        indicator_map = {'rsi': 'RSI', 'ema20': 'EMA20', 'ema50': 'EMA50', 'ema200': 'EMA200',
                         'atr': 'ATR', 'adx': 'ADX', 'macd': 'MACD', 'macd_signal': 'MACD_Sinyal',
                         'mfi': 'MFI', 'cmf': 'CMF', 'obv': 'OBV', 'vwap': 'VWAP_Yaklasik',
                         'historical_volatility_pct': 'Hist_Vol', 'supertrend': 'SuperTrend_Yon'}
        indicators = Indicators(**{key: last[column] for key, column in indicator_map.items()})
        if len(history) < config.EMA200_ICIN_MIN_VERI:
            indicators.ema200 = None
        if indicators.atr is None or indicators.atr <= 0:
            raise AnalysisError('invalid_indicators', 'A valid positive ATR could not be calculated; analysis unavailable.', 422)
        expected = now.date() - timedelta(days=1)
        while expected.weekday() >= 5:
            expected -= timedelta(days=1)
        last_bar = history.index[-1].date()
        warnings = ['Fundamentals and news are unavailable (null). Existing scoring receives zero contributions; weights and the 80-point technical denominator are unchanged.',
                    'Completed daily close analysis, not a live quote. VWAP is the engine daily approximation; SuperTrend is direction (+1/-1), not a price level.',
                    'Market status is unknown: no holiday-aware exchange calendar is connected.']
        if last_bar < expected:
            warnings.append('Last usable candle precedes the expected weekday. The provider may be delayed, the latest row invalid, or the exchange closed for a holiday.')
        return AnalysisResponse(
            ticker=symbol.removesuffix('.IS'), symbol=symbol, as_of=now.isoformat(),
            data_freshness=Freshness(last_bar=last_bar.isoformat(), expected_last_bar=expected.isoformat(), is_stale=last_bar < expected),
            market=Market(price=price, previous_close=previous, change=price-previous, change_pct=(price/previous-1)*100),
            scores=Scores(overall=final, technical=technical, trend=trend, momentum=momentum, volume=volume,
                          volatility=volatility, support_resistance_adjustment=adjustment,
                          category_maxima={'trend': config.TREND_MAX_PUAN, 'momentum': config.MOMENTUM_MAX_PUAN,
                                           'volume': config.HACIM_MAX_PUAN, 'volatility': config.VOLATILITE_MAX_PUAN}),
            indicators=indicators,
            strategy=Strategy(score=final, technical_score=technical, state='setup' if signal else 'no_setup',
                              signal=signal.signal_type if signal else None, classification=signal.classification if signal else None),
            risk=Risk(atr_pct=indicators.atr/price*100),
            price_series=[PricePoint(date=index.date().isoformat(), value=float(value)) for index, value in history.Close.tail(365).items()],
            data_quality=DataQuality(**{key: quality[key] for key in ('rows_downloaded', 'rows_removed', 'usable_rows', 'warnings')}),
            cache=CacheInfo(ttl_seconds=ttl_seconds), warnings=warnings,
        )
