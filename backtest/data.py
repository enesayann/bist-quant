"""Daily historical data boundary; local CSV and Yahoo chart providers."""
from datetime import datetime, time, timedelta
from pathlib import Path
import logging
import re
from typing import Protocol

import numpy as np
import pandas as pd

from bot.config import TR_TZ
from bot.market_data import MarketDataError, chart_quote


log = logging.getLogger('backtest.data')
MAX_REMOVED_FRACTION = .05


class DataProvider(Protocol):
    def fetch(self, ticker: str, start: str, end: str) -> pd.DataFrame: ...


def normalize_ticker(value):
    ticker = value.strip().upper()
    if not re.fullmatch(r'[A-Z0-9]{1,12}(?:\.IS)?', ticker):
        raise ValueError('Expected a BIST ticker such as ASELS or ASELS.IS')
    return ticker if ticker.endswith('.IS') else ticker + '.IS'


def validate_frame(frame):
    required = ['Open', 'High', 'Low', 'Close', 'Volume']
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        raise MarketDataError('No historical candles')
    if not isinstance(frame.index, pd.DatetimeIndex) or frame.index.hasnans:
        raise MarketDataError('Historical data requires a valid DatetimeIndex')
    if any(c not in frame for c in required):
        raise MarketDataError('Historical data requires Open, High, Low, Close, Volume')
    df = frame[required].copy()
    if df.index.tz is not None:
        df.index = df.index.tz_convert(TR_TZ).tz_localize(None)
    df.index = df.index.normalize()
    if df.index.has_duplicates or not df.index.is_monotonic_increasing:
        raise MarketDataError('Historical dates must be unique and increasing')
    try:
        for column in required:
            if any(isinstance(v, (bool, np.bool_)) for v in df[column]):
                raise ValueError('Boolean candle value')
            df[column] = pd.to_numeric(df[column], errors='raise').astype(float)
    except (TypeError, ValueError) as error:
        raise MarketDataError('Non-numeric historical candles') from error
    # A missing Open deliberately remains a candle: do not jump over it to
    # obtain a more favorable later open. Missing other fields are invalid.
    if not np.isfinite(df[['High', 'Low', 'Close', 'Volume']].to_numpy()).all():
        raise MarketDataError('Non-finite historical OHLCV')
    if np.isinf(df.Open).any():
        raise MarketDataError('Non-finite historical Open')
    if (df[['Open', 'High', 'Low', 'Close']] <= 0).any().any() or (df.Volume < 0).any():
        raise MarketDataError('Prices must be positive and volume nonnegative')
    if ((df.High < df.Low) | (df.Close > df.High) | (df.Close < df.Low)
            | (df.Open > df.High) | (df.Open < df.Low)).any():
        raise MarketDataError('Inconsistent OHLC prices')
    return df


def clean_history(frame, ticker, max_removed_fraction=MAX_REMOVED_FRACTION):
    """Clean provider candles without filling any price or volume.

    Missing OHLC/Volume removes the entire candle. Infinity, nonnumeric values,
    nonpositive prices, negative volume and inconsistent OHLC fail explicitly.
    Stable sorting and first-source-row duplicate selection are deterministic.
    Generic engine validation remains strict and unchanged.
    """
    columns = ['Open', 'High', 'Low', 'Close', 'Volume']
    if not 0 <= max_removed_fraction <= 1:
        raise ValueError('Maximum removed fraction must be in [0, 1]')
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        raise MarketDataError(f'{ticker}: no historical candles downloaded')
    if not isinstance(frame.index, pd.DatetimeIndex) or frame.index.hasnans:
        raise MarketDataError(f'{ticker}: invalid historical dates')
    if any(column not in frame for column in columns):
        raise MarketDataError(f'{ticker}: missing required OHLCV columns')
    df = frame[columns].copy()
    if df.index.tz is not None:
        df.index = df.index.tz_convert(TR_TZ).tz_localize(None)
    df.index = df.index.normalize()
    source_dates = [date.date().isoformat() for date in df.index]
    diagnostics = {'ticker': ticker, 'rows_downloaded': len(df), 'rows_removed': 0,
                   'usable_rows': 0, 'max_removed_fraction': max_removed_fraction,
                   'removed_rows': [], 'warnings': []}

    def reject(number, reason):
        day = source_dates[number]
        message = f'{ticker} {day} source row {number}: {reason}'
        log.error(message)
        error = MarketDataError(message)
        error.data_validation = dict(diagnostics, usable_rows=None, failure=message,
                                     invalid_rows=[{'ticker': ticker, 'date': day,
                                                    'source_row': number, 'reason': reason}])
        raise error

    for column in columns:
        for number, value in enumerate(df[column]):
            if isinstance(value, (bool, np.bool_)):
                reject(number, f'boolean {column} value')
        try:
            numeric = pd.to_numeric(df[column], errors='raise').astype(float)
        except (TypeError, ValueError, OverflowError) as error:
            # Identify the exact source cell rather than hiding conversion errors.
            for number, value in enumerate(df[column]):
                try:
                    pd.to_numeric(pd.Series([value]), errors='raise').astype(float)
                except (TypeError, ValueError, OverflowError):
                    reject(number, f'nonnumeric {column} value {value!r}')
            raise MarketDataError(f'{ticker}: cannot convert {column} to numeric') from error
        infinity = np.flatnonzero(np.isinf(numeric.to_numpy()))
        if len(infinity):
            reject(int(infinity[0]), f'infinite {column} value {numeric.iloc[infinity[0]]}')
        df[column] = numeric
    for number, row in enumerate(df.itertuples(index=False)):
        values = dict(zip(columns, row))
        for column in columns[:4]:
            if pd.notna(values[column]) and values[column] <= 0:
                reject(number, f'nonpositive {column} price {values[column]}')
        if pd.notna(values['Volume']) and values['Volume'] < 0:
            reject(number, f'negative Volume {values["Volume"]}')
        if (pd.notna(values['High']) and pd.notna(values['Low'])
                and values['High'] < values['Low']):
            reject(number, 'High < Low')
        for column in ('Open', 'Close'):
            value = values[column]
            if (pd.notna(value) and ((pd.notna(values['High']) and value > values['High'])
                                    or (pd.notna(values['Low']) and value < values['Low']))):
                reject(number, f'{column} outside [Low, High]')

    df['_source_row'] = range(len(df))
    if not df.index.is_monotonic_increasing:
        message = f'{ticker}: source dates sorted chronologically (stable order).'
        diagnostics['warnings'].append(message)
        log.warning(message)
    df = df.sort_index(kind='stable')

    def remove(index, row, reason, category):
        day = index.date().isoformat()
        number = int(row['_source_row'])
        values = {column: None if pd.isna(row[column]) else float(row[column]) for column in columns}
        diagnostics['removed_rows'].append({'ticker': ticker, 'date': day, 'source_row': number,
                                             'reason': reason, 'category': category, 'values': values})
        message = f'{ticker} {day} source row {number}: removed ({reason}).'
        diagnostics['warnings'].append(message)
        log.warning(message)

    duplicates = df.index.duplicated(keep='first')
    for index, row in df.loc[duplicates].iterrows():
        remove(index, row, 'duplicate date; kept first source row', 'duplicate')
    df = df.loc[~duplicates]
    missing = df[columns].isna().any(axis=1)
    for index, row in df.loc[missing].iterrows():
        bad_columns = [column for column in columns if pd.isna(row[column])]
        category = 'missing_ohlc' if any(column != 'Volume' for column in bad_columns) else 'missing_volume'
        remove(index, row, 'missing ' + ', '.join(bad_columns), category)
    df = df.loc[~missing, columns]
    diagnostics['rows_removed'] = len(diagnostics['removed_rows'])
    diagnostics['usable_rows'] = len(df)
    if df.empty:
        error = MarketDataError(f'{ticker}: completely unusable dataset; all {len(frame)} downloaded rows removed')
        error.data_validation = diagnostics
        raise error
    if diagnostics['rows_removed'] / diagnostics['rows_downloaded'] > max_removed_fraction:
        error = MarketDataError(f'{ticker}: too many invalid/duplicate rows: {diagnostics["rows_removed"]}/'
                                f'{diagnostics["rows_downloaded"]} removed; maximum {max_removed_fraction:.0%}')
        error.data_validation = diagnostics
        raise error
    df = validate_frame(df)
    df.attrs['validation'] = diagnostics
    # Source dates support a SEPARATE requested-period quality check in engine;
    # good warmup data must not dilute corruption in the actual trading range.
    df.attrs['downloaded_dates'] = source_dates
    return df


class CSVProvider:
    """Files named <ticker>.csv with Date,Open,High,Low,Close,Volume."""
    def __init__(self, directory):
        self.directory = Path(directory)

    def fetch(self, ticker, start, end):
        ticker = normalize_ticker(ticker)
        df = pd.read_csv(self.directory / f'{ticker}.csv', parse_dates=['Date'], index_col='Date')
        if not isinstance(df.index, pd.DatetimeIndex) or df.index.hasnans:
            raise MarketDataError(f'{ticker}: invalid historical CSV dates')
        df = df.loc[(df.index >= pd.Timestamp(start)) & (df.index <= pd.Timestamp(end))]
        return clean_history(df, ticker)


class YahooProvider:
    """Reuse the project's Yahoo chart HTTP client, never current meta prices.

    Quote OHLC (not adjusted-close) is used, as in the live bot. Yahoo may
    retrospectively split-adjust/revise history; this is not point-in-time data.
    """
    def __init__(self, session=None):
        if session is None:
            from bot.http_client import session as live_session
            session = live_session
        self.session = session

    def fetch(self, ticker, start, end):
        ticker = normalize_ticker(ticker)
        first, last = pd.Timestamp(start).date(), pd.Timestamp(end).date()
        if first > last:
            raise ValueError('Start must not be after end')
        if last >= datetime.now(TR_TZ).date():
            raise ValueError('Yahoo end must precede today; only completed daily candles are allowed')
        begin = int(datetime.combine(first, time.min, TR_TZ).timestamp())
        finish = int(datetime.combine(last + timedelta(days=1), time.min, TR_TZ).timestamp())
        url = (f'https://query1.finance.yahoo.com/v8/finance/chart/{ticker}'
               f'?interval=1d&period1={begin}&period2={finish}')
        response = self.session.get(url, timeout=30)
        response.raise_for_status()
        result, quote = chart_quote(response.json())
        timestamps = result.get('timestamp')
        if not isinstance(timestamps, list) or not timestamps:
            raise MarketDataError('Missing Yahoo historical timestamps')
        if any(isinstance(t, bool) or not isinstance(t, (int, float)) or not np.isfinite(t) for t in timestamps):
            raise MarketDataError('Invalid Yahoo historical timestamps')
        arrays = {column: quote.get(key) for column, key in
                  [('Open', 'open'), ('High', 'high'), ('Low', 'low'), ('Close', 'close'), ('Volume', 'volume')]}
        if any(not isinstance(a, list) or len(a) != len(timestamps) for a in arrays.values()):
            raise MarketDataError('Missing or mismatched Yahoo historical arrays')
        index = pd.to_datetime(timestamps, unit='s', utc=True).tz_convert(TR_TZ).tz_localize(None).normalize()
        df = pd.DataFrame(arrays, index=index)
        df = df.loc[(df.index >= pd.Timestamp(start)) & (df.index <= pd.Timestamp(end))]
        return clean_history(df, ticker)
