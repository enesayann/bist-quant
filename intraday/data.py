"""Strict 1h OHLCV schema, local bounds/completion gates and structured audit."""
from copy import deepcopy
from dataclasses import dataclass
import math
import re

import numpy as np
import pandas as pd

from . import GapError, IntradayError
from .session import BistCalendar, HOUR, TZ, aware_timestamp, request_times


COLUMNS = ['open', 'high', 'low', 'close', 'volume']
CONTRACT_VERSION = 'intraday-1h-v0'


def ticker_name(value):
    result = value.strip().upper()
    if not re.fullmatch(r'[A-Z0-9]{1,12}(?:\.IS)?', result):
        raise IntradayError('Expected a BIST ticker such as ASELS.IS')
    return result if result.endswith('.IS') else result + '.IS'


def empty_candles():
    return pd.DataFrame({c: pd.Series(dtype=float) for c in COLUMNS}, index=pd.DatetimeIndex([], tz=TZ, name='timestamp'))


def safe_value(value):
    if not pd.api.types.is_scalar(value):
        return repr(value)
    if value is None or pd.isna(value):
        return None
    if isinstance(value, (int, float, np.number)):
        try:
            return float(value) if math.isfinite(value) else str(value)
        except (TypeError, OverflowError):
            return repr(value)
    return str(value)


def normalize_candles(raw, ticker, start, end, as_of, *, calendar=None, source_timezone=None, source='unknown'):
    """Discard bad rows explicitly; never fill, truncate or relabel candles.

    Range filtering precedes OHLCV inspection, so a malicious future price row
    cannot affect historical values or their validation. Timestamp/schema errors
    that prevent bounding a row reject the input. First VALID duplicate wins;
    differing valid duplicates are reported and refused by strict consumers.
    """
    calendar = calendar or BistCalendar()
    ticker = ticker_name(ticker)
    start, end, as_of = request_times(start, end, as_of)
    calendar.ensure_range(start, end)
    if not isinstance(raw, pd.DataFrame):
        raise IntradayError('OHLCV input must be a DataFrame')
    missing = [c for c in COLUMNS if c not in raw.columns]
    if missing:
        raise IntradayError('Missing required OHLCV columns: ' + ', '.join(missing))
    timestamps = raw['timestamp'].tolist() if 'timestamp' in raw else raw.index.tolist()
    parsed = [aware_timestamp(t, source_timezone) for t in timestamps]
    diagnostics = {'ticker': ticker, 'requested_start': start.isoformat(), 'requested_end': end.isoformat(),
                   'as_of': as_of.isoformat(), 'timezone': 'Europe/Istanbul', 'interval': '1h',
                   'contract_version': CONTRACT_VERSION, 'calendar_version': calendar.version,
                   'provider_source': source, 'downloaded_rows': len(raw), 'input_rows': len(raw),
                   'removed_rows': 0, 'duplicates': 0, 'outside_range_rows': 0, 'outside_session_rows': 0,
                   'incomplete_rows': 0, 'valid_zero_volume_rows': 0, 'final_usable_rows': 0,
                   'events': [], 'duplicate_conflicts': [], 'missing_candle_gaps': [], 'cache_hit': False,
                   'gap_detection_performed': False,
                   'price_basis': 'unverified', 'volume_adjustment_basis': 'unverified',
                   'corporate_action_risks': ['OHLC split/dividend adjustment and volume basis are unverified; no auto-adjustment applied.']}
    accepted = {}
    seen = set()

    def event(number, stamp, reason, detail=None, *, removed=True, outside_session=False):
        row = raw.iloc[number]
        diagnostics['events'].append({'ticker': ticker, 'timestamp': stamp.isoformat(), 'session_date': str(stamp.date()),
                                      'source_row': number, 'reason': reason, 'detail': detail,
                                      'removed': removed, 'outside_session': outside_session,
                                      'values': {c: safe_value(row[c]) for c in COLUMNS}})
        if removed:
            diagnostics['removed_rows'] += 1
        if outside_session and removed:
            diagnostics['outside_session_rows'] += 1

    for number, stamp in enumerate(parsed):
        if not start <= stamp < end:
            diagnostics['outside_range_rows'] += 1
            event(number, stamp, 'outside_requested_range')
            continue
        if stamp + HOUR > end or stamp + HOUR > as_of:
            diagnostics['incomplete_rows'] += 1
            event(number, stamp, 'incomplete_candle', 'crosses_requested_end' if stamp + HOUR > end else 'not_completed_as_of')
            continue
        row = raw.iloc[number]
        try:
            zero = not isinstance(row.volume, (bool, np.bool_)) and float(row.volume) == 0
        except (TypeError, ValueError, OverflowError):
            zero = False
        tradable, reason, detail = calendar.classify(stamp, bool(zero))
        if not tradable:
            event(number, stamp, reason, detail, outside_session=True)
            continue
        if stamp in seen:
            diagnostics['duplicates'] += 1
        seen.add(stamp)
        values = []
        bad_numeric = False
        for c in COLUMNS:
            value = row[c]
            if isinstance(value, (bool, np.bool_)):
                bad_numeric = True
                break
            try:
                values.append(float(value))
            except (TypeError, ValueError, OverflowError):
                if value is None or pd.isna(value):
                    values.append(float('nan'))
                else:
                    bad_numeric = True
                    break
        if bad_numeric:
            event(number, stamp, 'invalid_ohlc', 'nonnumeric_or_boolean_ohlcv')
            continue
        if any(math.isnan(v) for v in values):
            event(number, stamp, 'missing_ohlcv')
            continue
        if not all(math.isfinite(v) for v in values):
            event(number, stamp, 'invalid_ohlc', 'infinite_ohlcv')
            continue
        opening, high, low, close, volume = values
        if volume < 0:
            event(number, stamp, 'invalid_volume', 'negative_volume')
            continue
        if min(opening, high, low, close) <= 0 or high < max(opening, close, low) or low > min(opening, close, high):
            event(number, stamp, 'invalid_ohlc', 'nonpositive_or_inconsistent_prices')
            continue
        if stamp in accepted:
            conflict = tuple(values) != accepted[stamp]
            event(number, stamp, 'duplicate_timestamp', 'conflicting_valid_duplicate' if conflict else 'identical_duplicate')
            if conflict:
                diagnostics['duplicate_conflicts'].append(stamp.isoformat())
            continue
        accepted[stamp] = tuple(values)
        if volume == 0:
            diagnostics['valid_zero_volume_rows'] += 1
            event(number, stamp, 'valid_zero_volume', 'inside_full_continuous_bar', removed=False)
    result = empty_candles()
    if accepted:
        result = pd.DataFrame.from_dict(accepted, orient='index', columns=COLUMNS).astype(float).sort_index(kind='stable')
        result.index = pd.DatetimeIndex(result.index, name='timestamp').tz_convert(TZ).as_unit('ns')
    diagnostics['final_usable_rows'] = len(result)
    return result, diagnostics


def validate_contract(frame, calendar=None):
    """Validation for already canonical cache/replay input; never repairs it."""
    calendar = calendar or BistCalendar()
    if not isinstance(frame.index, pd.DatetimeIndex) or frame.index.tz is None or frame.index.hasnans:
        raise IntradayError('Canonical candles require an aware DatetimeIndex')
    if str(frame.index.tz) != 'Europe/Istanbul' or frame.index.has_duplicates or not frame.index.is_monotonic_increasing:
        raise IntradayError('Canonical timestamps must be unique, increasing, Europe/Istanbul aware')
    if list(frame.columns) != COLUMNS:
        raise IntradayError('Canonical schema must be open,high,low,close,volume indexed by timestamp')
    for stamp, row in frame.iterrows():
        if any(isinstance(v, (bool, np.bool_)) for v in row) or not np.isfinite(row.to_numpy(dtype=float)).all():
            raise IntradayError(f'Non-finite/boolean canonical candle: {stamp.isoformat()}')
        if (row[COLUMNS[:4]] <= 0).any() or row.volume < 0 or row.high < max(row.open, row.close, row.low) or row.low > min(row.open, row.close, row.high):
            raise IntradayError(f'Invalid canonical OHLCV: {stamp.isoformat()}')
        if not calendar.classify(stamp, row.volume == 0)[0]:
            raise IntradayError(f'Canonical candle outside accepted session: {stamp.isoformat()}')
    return frame


def finalize_diagnostics(frame, diagnostics, calendar, start, end, as_of):
    diagnostics = deepcopy(diagnostics)
    expected = calendar.expected(start, end, as_of)
    gaps = expected.difference(frame.index)
    diagnostics['missing_candle_gaps'] = [{'ticker': diagnostics['ticker'], 'missing_timestamp': t.isoformat(),
                                          'session_date': str(t.date()), 'reason': 'missing_expected_candle'} for t in gaps]
    diagnostics['gap_detection_performed'] = True
    diagnostics['final_usable_rows'] = len(frame)
    diagnostics['actual_first_candle'] = frame.index[0].isoformat() if len(frame) else None
    diagnostics['actual_last_candle'] = frame.index[-1].isoformat() if len(frame) else None
    diagnostics['expected_completed_candles'] = len(expected)
    jumps = []
    for i in range(1, len(frame)):
        ratio = frame.open.iloc[i] / frame.close.iloc[i-1]
        if abs(ratio - 1) > .20:
            jumps.append({'timestamp': frame.index[i].isoformat(), 'relative_open_gap': float(ratio - 1),
                          'reason': 'suspicious_price_discontinuity', 'not_a_confirmed_split': True})
    diagnostics['suspicious_discontinuities'] = jumps
    diagnostics['discontinuity_threshold_fraction'] = .20  # Diagnostic only, never a trading rule.
    return diagnostics


def enforce_quality(diagnostics, gap_policy):
    if gap_policy not in ('strict', 'warn'):
        raise IntradayError('Gap policy must be strict or warn')
    if diagnostics.get('duplicate_conflicts'):
        raise IntradayError('Conflicting source duplicate candle(s): ' + ', '.join(diagnostics['duplicate_conflicts']), diagnostics)
    if gap_policy == 'strict' and diagnostics['missing_candle_gaps']:
        gaps = diagnostics['missing_candle_gaps']
        raise GapError(f'{diagnostics["ticker"]}: {len(gaps)} missing completed session candle(s); first '
                       + gaps[0]['missing_timestamp'], diagnostics)


@dataclass
class IntradayData:
    ticker: str
    start: pd.Timestamp
    end: pd.Timestamp
    as_of: pd.Timestamp
    candles: pd.DataFrame
    diagnostics: dict
    calendar: BistCalendar
