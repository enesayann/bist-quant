"""Small Yahoo, immutable-cache and standalone-CSV providers for one timeframe."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
from typing import Protocol

import numpy as np
import pandas as pd
import requests

from . import CacheMiss, IntradayError
from .cache import IntradayCache, read_csv_candles
from .data import (IntradayData, enforce_quality, finalize_diagnostics, normalize_candles,
                   ticker_name, validate_contract)
from .session import BistCalendar, TZ, aware_timestamp, request_times


class Provider(Protocol):
    def fetch(self, ticker, start, end, *, as_of=None, gap_policy='strict') -> IntradayData: ...


def request_arguments(ticker, start, end, as_of, gap_policy, calendar):
    if gap_policy not in ('strict', 'warn'):
        raise IntradayError('Gap policy must be strict or warn')
    ticker = ticker_name(ticker)
    start, end, as_of = request_times(start, end, as_of)
    calendar.ensure_range(start, end)
    return ticker, start, end, as_of


def cache_provenance(diagnostics, manifest, start, end, as_of):
    diagnostics['cache_revision_sha256'] = manifest['csv_sha256']
    diagnostics['original_provider_source'] = manifest['source_identity']
    audits = [a for a in manifest['source_audits']
              if aware_timestamp(a['requested_start']) < end and aware_timestamp(a['requested_end']) > start]
    diagnostics['source_downloaded_rows'] = sum(a['downloaded_rows'] for a in audits)
    diagnostics['source_audit_provenance'] = deepcopy(audits)
    diagnostics['duplicate_conflicts'] = sorted({stamp for a in audits for stamp in a.get('duplicate_conflicts', [])
                                                if start <= aware_timestamp(stamp) < min(end, as_of)})
    diagnostics['corporate_action_events'] = [event for a in audits for event in a.get('corporate_action_events', [])
                                             if start <= aware_timestamp(event['timestamp']) < end
                                             and aware_timestamp(event['timestamp']) <= as_of]
    return diagnostics


def make_data(ticker, frame, audit, start, end, as_of, calendar, gap_policy):
    validate_contract(frame, calendar)
    audit = finalize_diagnostics(frame, audit, calendar, start, end, as_of)
    audit['gap_policy'] = gap_policy
    enforce_quality(audit, gap_policy)
    return IntradayData(ticker, start, end, as_of, frame.copy(deep=True), audit, calendar)


class YahooProvider:
    def __init__(self, cache=None, calendar=None, session=None, raw_output=None):
        self.calendar = calendar or BistCalendar()
        self.cache = cache
        self.session = session
        self.raw_output = Path(raw_output) if raw_output else None

    def fetch(self, ticker, start, end, *, as_of=None, gap_policy='strict'):
        ticker, start, end, as_of = request_arguments(ticker, start, end, as_of, gap_policy, self.calendar)
        if self.cache is not None:
            cached, manifest = self.cache.load(ticker)
            if self.cache.covers(manifest, start, end, as_of):
                selected, audit = normalize_candles(cached, ticker, start, end, as_of,
                                                    calendar=self.calendar, source='local_cache')
                audit['downloaded_rows'] = 0
                audit['cache_hit'] = True
                cache_provenance(audit, manifest, start, end, as_of)
                return make_data(ticker, selected, audit, start, end, as_of, self.calendar, gap_policy)
        if self.session is None:
            self.session = requests.Session()  # Isolated from the production bot's HTTP state.
            self.session.headers['User-Agent'] = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36'
        params = {'interval': '1h', 'period1': int(start.timestamp()), 'period2': int(end.timestamp()),
                  'includePrePost': 'false', 'events': 'div,splits'}
        try:
            response = self.session.get(f'https://query1.finance.yahoo.com/v8/finance/chart/{ticker}', params=params, timeout=25)
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError) as error:
            raise IntradayError(f'{ticker}: Yahoo intraday request failed: {error}') from error
        encoded = json.dumps(payload, ensure_ascii=False, allow_nan=True).encode('utf-8')
        digest = sha256(encoded).hexdigest()
        raw_path = None
        if self.raw_output:
            self.raw_output.mkdir(parents=True, exist_ok=True)
            raw_path = self.raw_output / f'{ticker}_{digest}.json'
            if not raw_path.exists():
                raw_path.write_bytes(encoded)
        try:
            chart = payload['chart']
            if chart.get('error'):
                raise ValueError(str(chart['error']))
            result = chart['result'][0]
            if result.get('meta', {}).get('symbol') != ticker:
                raise ValueError('Yahoo ticker does not match requested ticker')
            if result.get('meta', {}).get('instrumentType') != 'EQUITY':
                raise ValueError('The BIST v0 session contract supports ordinary equities only')
            if result.get('meta', {}).get('dataGranularity') not in ('1h', '60m'):
                raise ValueError('Yahoo did not return the requested 1h granularity')
            timezone = result.get('meta', {}).get('exchangeTimezoneName')
            if timezone != 'Europe/Istanbul':
                raise ValueError(f'Unexpected Yahoo exchange timezone {timezone!r}')
            timestamps = result['timestamp']
            if not isinstance(timestamps, list) or any(isinstance(t, bool) or not isinstance(t, (int, float)) or not np.isfinite(t) for t in timestamps):
                raise ValueError('Invalid Yahoo epoch timestamps')
            quote = result['indicators']['quote'][0]
            arrays = {c: quote[c] for c in ('open', 'high', 'low', 'close', 'volume')}
            if any(not isinstance(v, list) or len(v) != len(timestamps) for v in arrays.values()):
                raise ValueError('Mismatched Yahoo OHLCV/timestamp arrays')
            index = pd.to_datetime(timestamps, unit='s', utc=True).tz_convert(TZ)
            raw = pd.DataFrame(arrays, index=index)
        except (KeyError, IndexError, TypeError, ValueError) as error:
            raise IntradayError(f'{ticker}: malformed Yahoo intraday payload: {error}',
                                 {'ticker': ticker, 'requested_start': start.isoformat(), 'requested_end': end.isoformat(),
                                  'provider_source': 'yahoo_chart', 'raw_payload_sha256': digest,
                                  'raw_payload_path': str(raw_path) if raw_path else None}) from error
        selected, audit = normalize_candles(raw, ticker, start, end, as_of, calendar=self.calendar, source='yahoo_chart')
        audit.update(cache_hit=False, raw_payload_sha256=digest, raw_payload_path=str(raw_path) if raw_path else None,
                     source_request=params, source_downloaded_rows=len(raw), corporate_action_events=[],
                     source_current_trading_period=result['meta'].get('currentTradingPeriod'),
                     session_metadata_is_not_calendar=True)
        for kind, events in result.get('events', {}).items():
            for event in events.values():
                stamp = pd.Timestamp(event['date'], unit='s', tz='UTC').tz_convert(TZ)
                if start <= stamp < end and stamp <= as_of:
                    audit['corporate_action_events'].append({'kind': kind, 'timestamp': stamp.isoformat(), 'payload': deepcopy(event),
                                                             'adjustment_basis_verified': False})
        if audit['duplicate_conflicts']:
            raise IntradayError('Conflicting source duplicates; cache not updated', audit)
        if self.cache is not None:
            incoming_index = selected.index.copy()
            merged, manifest, overlap = self.cache.merge(ticker, selected, start, end, as_of, audit)
            selected, _ = normalize_candles(merged, ticker, start, end, as_of, calendar=self.calendar, source='cache_merge')
            audit['cache_identical_overlaps'] = overlap
            audit['validated_cached_rows_reused'] = sum(t not in incoming_index for t in selected.index)
            cache_provenance(audit, manifest, start, end, as_of)
        return make_data(ticker, selected, audit, start, end, as_of, self.calendar, gap_policy)


class CacheProvider:
    def __init__(self, cache):
        self.cache = cache
        self.calendar = cache.calendar

    def fetch(self, ticker, start, end, *, as_of=None, gap_policy='strict'):
        ticker, start, end, as_of = request_arguments(ticker, start, end, as_of, gap_policy, self.calendar)
        frame, manifest = self.cache.load(ticker)
        if not self.cache.covers(manifest, start, end, as_of):
            raise CacheMiss(f'{ticker}: cache does not cover requested completed segment')
        selected, audit = normalize_candles(frame, ticker, start, end, as_of, calendar=self.calendar, source='local_cache')
        audit.update(downloaded_rows=0, cache_hit=True)
        cache_provenance(audit, manifest, start, end, as_of)
        return make_data(ticker, selected, audit, start, end, as_of, self.calendar, gap_policy)


class CSVProvider:
    def __init__(self, path, calendar=None, source_timezone=None):
        self.path = Path(path)
        self.calendar = calendar or BistCalendar()
        self.source_timezone = source_timezone

    def fetch(self, ticker, start, end, *, as_of=None, gap_policy='strict'):
        ticker, start, end, as_of = request_arguments(ticker, start, end, as_of, gap_policy, self.calendar)
        raw = read_csv_candles(self.path, self.source_timezone)
        selected, audit = normalize_candles(raw, ticker, start, end, as_of, calendar=self.calendar, source='local_csv')
        audit.update(downloaded_rows=0, source_file=str(self.path.resolve()), cache_hit=False,
                     source_file_sha256=sha256(self.path.read_bytes()).hexdigest())
        return make_data(ticker, selected, audit, start, end, as_of, self.calendar, gap_policy)
