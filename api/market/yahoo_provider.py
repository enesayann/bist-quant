"""Normalize Yahoo chart metadata and daily candles without strategy work."""
import math
import pandas as pd
import requests

from api.errors import AnalysisError
from api.models import normalize_symbol
from backtest.data import clean_history
from bot.market_data import chart_quote, MarketDataError
from intraday import IntradayError
from intraday.session import TZ
from .models import HistoryPoint, ProviderSnapshot, PublicError, Quality, Quote
from .session import MarketCalendar


def finite(value, *, positive=False, nonnegative=False):
    if value is None or isinstance(value, bool):
        return None
    try:
        value = float(value)
        if not math.isfinite(value) or positive and value <= 0 or nonnegative and value < 0:
            return None
        return value
    except (ValueError, TypeError, OverflowError):
        return None


def timestamp(value):
    value = finite(value, positive=True)
    if value is None:
        return None
    try:
        return pd.Timestamp(value, unit='s', tz='UTC').tz_convert(TZ)
    except (ValueError, OverflowError):
        return None


class YahooMarketDataProvider:
    name = 'Yahoo Finance'

    def __init__(self, session_factory=None, calendar=None):
        self.session_factory = session_factory or requests.Session
        self.calendar = calendar or MarketCalendar()

    def fetch_snapshot(self, symbol, as_of):
        symbol = normalize_symbol(symbol)
        now = pd.Timestamp(as_of).tz_convert(TZ)
        url = f'https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=1y'
        try:
            with self.session_factory() as session:
                session.headers.update({'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36', 'Accept': 'application/json'})
                session.trust_env = False
                response = session.get(url, timeout=(3, 8), allow_redirects=False)
                response.raise_for_status()
                payload = response.json()
        except requests.Timeout as error:
            raise AnalysisError('provider_timeout', 'Market-data provider timed out.', 504) from error
        except requests.RequestException as error:
            raise AnalysisError('provider_unavailable', 'Market-data provider is unavailable.', 502) from error
        try:
            return self.normalize(payload, symbol, now)
        except (MarketDataError, ValueError, TypeError, KeyError, IndexError) as error:
            raise AnalysisError('invalid_market_data', 'Provider data could not be safely normalized.', 502) from error

    def normalize(self, payload, symbol, now):
        result, arrays = chart_quote(payload)
        meta = result.get('meta') or {}
        if not isinstance(meta, dict):
            raise MarketDataError('Invalid provider metadata')
        times = result.get('timestamp')
        if not isinstance(times, list) or not times:
            raise AnalysisError('no_data', 'No market history is available for this ticker.', 422)
        columns = [('Open', 'open'), ('High', 'high'), ('Low', 'low'), ('Close', 'close'), ('Volume', 'volume')]
        if any(not isinstance(arrays.get(key), list) or len(arrays[key]) != len(times) for _, key in columns):
            raise MarketDataError('Mismatched daily arrays')
        stamps = [timestamp(value) for value in times]
        if any(stamp is None for stamp in stamps):
            raise MarketDataError('Invalid daily timestamps')
        quality = Quality(downloaded_rows=len(times))
        eligible, original = [], {}
        lower = now - pd.DateOffset(years=1)
        for i, stamp in enumerate(stamps):
            if stamp > now:
                quality.future_rows += 1
                quality.warnings.append(f'{symbol} source row {i}: future timestamp removed ({stamp.isoformat()}).')
            elif stamp < lower.normalize():
                quality.warnings.append(f'{symbol} source row {i}: outside one-year source range removed.')
            elif not self.calendar.completed(stamp, now):
                quality.incomplete_rows += 1
                quality.warnings.append(f'{symbol} {stamp.date()} source row {i}: incomplete or non-session daily bar excluded.')
            else:
                eligible.append(i)
                original.setdefault(stamp.date().isoformat(), stamp.isoformat())
        frame = pd.DataFrame({column: [arrays[key][i] for i in eligible] for column, key in columns},
                             index=pd.DatetimeIndex([stamps[i] for i in eligible]))
        points, history_error = [], None
        try:
            frame = clean_history(frame, symbol)
            quality.warnings.extend(frame.attrs['validation']['warnings'])
            points = [HistoryPoint(timestamp=original[index.date().isoformat()], date=index.date().isoformat(), close=float(row.Close), volume=float(row.Volume)) for index, row in frame.iterrows()]
        except MarketDataError:
            frame = pd.DataFrame()
            history_error = PublicError(code='no_history', message='Completed history failed existing OHLCV validation or contains no usable candles.')
            quality.warnings.append(history_error.message)
        quality.usable_rows = len(points)
        quality.removed_rows = quality.downloaded_rows-quality.usable_rows
        warnings = list(quality.warnings)
        quote_stamp = timestamp(meta.get('regularMarketTime'))
        meta_price = finite(meta.get('regularMarketPrice'), positive=True)
        if meta.get('regularMarketPrice') is not None and meta_price is None:
            warnings.append('Non-finite/nonpositive provider quote price is unavailable.')
        if quote_stamp is not None and quote_stamp > now:
            warnings.append('Future provider quote timestamp rejected; its price is not used.')
            quote_stamp, meta_price = None, None
        price, basis = meta_price, 'provider_quote'
        if meta_price is None and points:
            price, basis = points[-1].close, 'last_completed_close'
        if price is None:
            raise AnalysisError('no_data', 'No usable provider quote or completed close is available.', 422)
        reference_day = quote_stamp.date() if basis == 'provider_quote' and quote_stamp is not None else pd.Timestamp(points[-1].date).date() if points else None
        previous = None
        if reference_day is not None and not frame.empty:
            try:
                previous_day = self.calendar.previous_session(reference_day)
                candidates = frame.loc[frame.index.date == previous_day]
                if not candidates.empty:
                    previous = float(candidates.Close.iloc[-1])
            except IntradayError:
                pass
        # chartPreviousClose is the chart-range reference, NOT yesterday's close.
        # Do not use it as a daily change baseline.
        if previous is None and quote_stamp is not None:
            previous = finite(meta.get('previousClose'), positive=True)
        fields = {'day_open': finite(meta.get('regularMarketOpen'), positive=True),
                  'day_high': finite(meta.get('regularMarketDayHigh'), positive=True),
                  'day_low': finite(meta.get('regularMarketDayLow'), positive=True),
                  'volume': finite(meta.get('regularMarketVolume'), nonnegative=True)}
        for key, meta_key in [('day_open', 'regularMarketOpen'), ('day_high', 'regularMarketDayHigh'), ('day_low', 'regularMarketDayLow'), ('volume', 'regularMarketVolume')]:
            if meta.get(meta_key) is not None and fields[key] is None:
                warnings.append(f'Invalid/non-finite provider {meta_key} excluded; only a valid same-day raw field can replace it.')
        if reference_day is not None:
            same_day = [i for i, stamp in enumerate(stamps) if stamp <= now and stamp.date() == reference_day]
            if same_day:
                i = same_day[-1]
                for key, array_key in [('day_open', 'open'), ('day_high', 'high'), ('day_low', 'low'), ('volume', 'volume')]:
                    if fields[key] is None:
                        fields[key] = finite(arrays[array_key][i], positive=key != 'volume', nonnegative=key == 'volume')
        if fields['day_high'] is not None and fields['day_low'] is not None and fields['day_high'] < fields['day_low']:
            fields['day_high'], fields['day_low'] = None, None
            warnings.append('Inconsistent provider daily range is unavailable.')
        if fields['day_open'] is not None and ((fields['day_high'] is not None and fields['day_open'] > fields['day_high']) or (fields['day_low'] is not None and fields['day_open'] < fields['day_low'])):
            fields['day_open'] = None
            warnings.append('Provider day open outside the daily range is unavailable.')
        delay = finite(meta.get('exchangeDataDelayedBy'), nonnegative=True)
        latest_bar = points[-1].timestamp if points else None
        freshness_time = quote_stamp.isoformat() if basis == 'provider_quote' and quote_stamp is not None else latest_bar if basis == 'last_completed_close' else None
        quote = Quote(symbol=symbol, ticker=symbol.removesuffix('.IS'), price=price, previous_close=previous,
                      change=price-previous if previous is not None else None,
                      change_pct=(price/previous-1)*100 if previous is not None else None,
                      **fields, currency=meta.get('currency') if isinstance(meta.get('currency'), str) else None,
                      quote_time=quote_stamp.isoformat() if quote_stamp is not None and basis == 'provider_quote' else None,
                      last_bar_time=latest_bar, provider=self.name, price_basis=basis, fetched_at=now.isoformat(),
                      provider_delay_status='delayed' if delay is not None and delay > 0 else 'unknown',
                      market_status=self.calendar.info(now).status,
                      freshness_status=self.calendar.freshness(freshness_time, now, completed_close=basis == 'last_completed_close'),
                      warnings=warnings)
        return ProviderSnapshot(quote=quote, points=points, quality=quality, history_error=history_error)
