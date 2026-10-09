"""Bounded Yahoo diagnostics only. No strategy, execution, or live integration."""
import argparse
from datetime import datetime
from hashlib import sha256
import json
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import requests


TZ = ZoneInfo('Europe/Istanbul')
BASKET = ('ASELS.IS', 'THYAO.IS', 'GARAN.IS', 'TUPRS.IS', 'BIMAS.IS',
          'KCHOL.IS', 'FROTO.IS', 'TCELL.IS', 'EREGL.IS', 'SISE.IS')
COLUMNS = ['Open', 'High', 'Low', 'Close', 'Volume']
INTERVALS = {'15m': 15, '30m': 30, '60m': 60, '1h': 60}
SESSION_SOURCE = 'https://www.borsaistanbul.com/files/equity-market-procedure.pdf'


def normalize_timestamps(values, source_tz=None):
    """Preserve time-of-day. Naive CSV timestamps require an explicit timezone."""
    index = pd.DatetimeIndex(values)
    if index.hasnans:
        raise ValueError('Invalid intraday timestamp')
    if index.tz is None:
        if source_tz is None:
            raise ValueError('Naive timestamps require source_tz')
        index = index.tz_localize(source_tz, ambiguous='raise', nonexistent='raise')
    return index.tz_convert(TZ)


def deduplicate_candles(frame):
    """Diagnostic canonical view; preserve first source row and expose conflicts."""
    result = frame.copy()
    result.index = normalize_timestamps(result.index)
    duplicate_times = result.index[result.index.duplicated(keep=False)].unique()
    conflicts = []
    for stamp in duplicate_times:
        rows = result.loc[[stamp]]
        if any(rows[column].nunique(dropna=False) > 1 for column in rows.columns):
            conflicts.append(stamp.isoformat())
    discarded = result.index[result.index.duplicated(keep='first')]
    canonical = result.loc[~result.index.duplicated(keep='first')].sort_index(kind='stable')
    return canonical, {'duplicate_rows': len(discarded), 'discarded_timestamps': [t.isoformat() for t in discarded],
                        'conflicting_timestamps': conflicts, 'policy': 'first source row; diagnostic view only; raw response retained'}


def filter_session(frame, interval_minutes, *, opening, closing):
    """Whole nominal bars inside a SPECIFIED full/half-day continuous session.

    Not a production exchange calendar. Bars crossing an auction boundary are
    excluded, not relabeled or truncated. Partial/latest snapshots are not fills.
    """
    if interval_minutes <= 0:
        raise ValueError('Interval must be positive')
    index = normalize_timestamps(frame.index)
    def offset(text):
        hour, minute = map(int, text.split(':'))
        if not 0 <= hour < 24 or not 0 <= minute < 60:
            raise ValueError('Invalid session time')
        return pd.Timedelta(hours=hour, minutes=minute)
    start, end = offset(opening), offset(closing)
    if end <= start:
        raise ValueError('Session close must follow open')
    day = index.normalize()  # Only to build boundaries; NEVER replace bar index.
    mask = ((index >= day + start) & (index + pd.Timedelta(minutes=interval_minutes) <= day + end)
            & (index.dayofweek < 5))
    result = frame.loc[mask].copy()
    result.index = index[mask]
    return result


def missing_candles(index, interval_minutes, sessions, *, phase_minute=0):
    """Report candidate missing slots on explicit session dates; never fill them.

    sessions: date string -> (continuous-open, continuous-close), or None for a
    known closure. Missing whole dates require this external schedule as well.
    """
    actual = normalize_timestamps(index)
    if interval_minutes <= 0 or not 0 <= phase_minute < interval_minutes:
        raise ValueError('Invalid interval/phase')
    expected = []
    for date, hours in sessions.items():
        if hours is None:
            continue
        opening, closing = (pd.Timestamp(f'{date} {clock}', tz=TZ) for clock in hours)
        first = opening.normalize() + pd.Timedelta(minutes=phase_minute)
        while first < opening:
            first += pd.Timedelta(minutes=interval_minutes)
        expected.extend(pd.date_range(first, closing - pd.Timedelta(minutes=interval_minutes),
                                      freq=f'{interval_minutes}min'))
    return pd.DatetimeIndex(expected, tz=TZ).difference(actual)


def frame_from_chart(payload):
    chart = payload.get('chart', {})
    if chart.get('error'):
        raise ValueError(str(chart['error']))
    try:
        result = chart['result'][0]
        timestamps = result['timestamp']
        quote = result['indicators']['quote'][0]
        if not timestamps or any(isinstance(t, bool) or not isinstance(t, (int, float)) or not np.isfinite(t) for t in timestamps):
            raise ValueError('Invalid epoch timestamps')
        arrays = {column: quote[column.lower()] for column in COLUMNS}
        if any(not isinstance(values, list) or len(values) != len(timestamps) for values in arrays.values()):
            raise ValueError('Mismatched intraday arrays')
        index = normalize_timestamps(pd.to_datetime(timestamps, unit='s', utc=True))
        frame = pd.DataFrame(arrays, index=index)
        # Numeric diagnostics do not invent prices. The original JSON remains
        # authoritative, including nulls; no corrected dataset is fed to a bot.
        for column in COLUMNS:
            frame[column] = pd.to_numeric(frame[column], errors='raise').astype(float)
        return result, frame
    except (KeyError, IndexError, TypeError) as error:
        raise ValueError('Malformed intraday chart') from error


def analyze_payload(payload, interval, as_of, requested_start=None, requested_end=None):
    result, frame = frame_from_chart(payload)
    meta = result['meta']
    canonical, duplicates = deduplicate_candles(frame)
    minutes = INTERVALS[interval]
    clock_minutes = canonical.index.hour * 60 + canonical.index.minute
    phase = int(pd.Series(clock_minutes % minutes).mode().iloc[0])
    regular = filter_session(canonical, minutes, opening='10:00', closing='18:00')
    finite = np.isfinite(frame[COLUMNS].to_numpy()).all(axis=1)
    issues = []
    for stamp, row in frame.loc[~finite].iterrows():
        issues.append({'timestamp': stamp.isoformat(), 'columns': [c for c in COLUMNS if not np.isfinite(row[c])],
                       'reason': 'missing/non-finite values'})
    invalid = ((frame[['Open', 'High', 'Low', 'Close']] <= 0).any(axis=1) | (frame.Volume < 0)
               | (frame.High < frame.Low) | (frame.Open < frame.Low) | (frame.Open > frame.High)
               | (frame.Close < frame.Low) | (frame.Close > frame.High))
    for stamp in frame.index[invalid]:
        issues.append({'timestamp': stamp.isoformat(), 'reason': 'nonpositive price, negative volume or inconsistent OHLC'})
    dates = sorted(set(regular.index.strftime('%Y-%m-%d')))
    schedules = {date: ('10:00', '18:00') for date in dates}
    gaps = missing_candles(regular.index, minutes, schedules, phase_minute=phase)
    outside_range = []
    if requested_start is not None:
        outside_range += [t.isoformat() for t in frame.index[frame.index < requested_start]]
    if requested_end is not None:
        outside_range += [t.isoformat() for t in frame.index[frame.index >= requested_end]]
    zero = frame.index[frame.Volume == 0]
    partial = frame.index[frame.index + pd.Timedelta(minutes=minutes) > as_of]
    start_end = {date: {'first': group.index[0].isoformat(), 'last': group.index[-1].isoformat(), 'rows': len(group)}
                 for date, group in canonical.groupby(canonical.index.strftime('%Y-%m-%d'))}
    return {'raw_rows': len(frame), 'first_timestamp': frame.index.min().isoformat(), 'last_timestamp': frame.index.max().isoformat(),
            'oldest_age_calendar_days': float((as_of - frame.index.min()).total_seconds() / 86400),
            'observed_span_days': float((frame.index.max() - frame.index.min()).total_seconds() / 86400),
            'metadata': {k: meta.get(k) for k in ('exchangeTimezoneName', 'timezone', 'gmtoffset', 'currency',
                                               'dataGranularity', 'currentTradingPeriod', 'regularMarketTime', 'validRanges')},
            'labels': sorted(set(frame.index.strftime('%H:%M'))), 'modal_start_phase_minutes': phase,
            'duplicates': duplicates, 'invalid_rows': issues, 'null_cells': {c: int(frame[c].isna().sum()) for c in COLUMNS},
            'infinite_cells': {c: int(np.isinf(frame[c]).sum()) for c in COLUMNS},
            'zero_volume_rows': len(zero), 'zero_volume_timestamps': [t.isoformat() for t in zero[:20]],
            'interior_zero_volume_rows': int((regular.Volume == 0).sum()),
            'full_interval_regular_rows': len(regular), 'excluded_boundary_or_outside_rows': len(canonical) - len(regular),
            'regular_rows_per_day': regular.groupby(regular.index.strftime('%Y-%m-%d')).size().to_dict(),
            'daily_first_last': start_end, 'candidate_missing_slots': len(gaps), 'candidate_missing_examples': [t.isoformat() for t in gaps[:20]],
            'missing_slot_scope': 'Observed days only under an explicit full-day hypothesis; long-window half-days/halts require a certified calendar before classifying gaps.',
            'partial_at_retrieval_rows': len(partial), 'outside_requested_range_rows': len(outside_range),
            'outside_requested_range_examples': outside_range[:20],
            'indicator_fields': list(result['indicators']), 'events': result.get('events', {})}


def compare_aggregation(lower_payload, higher_payload, higher_interval):
    """Compare real child bars with native vendor bars; no empty bars generated."""
    _, lower = frame_from_chart(lower_payload)
    _, higher = frame_from_chart(higher_payload)
    lower, _ = deduplicate_candles(lower)
    higher, _ = deduplicate_candles(higher)
    minutes = INTERVALS[higher_interval]
    regular = filter_session(higher, minutes, opening='10:00', closing='18:00')
    matched, missing_children, mismatches, boundary_mismatches = 0, 0, [], []
    for stamp, row in higher.iterrows():
        wanted = pd.date_range(stamp, periods=minutes // 15, freq='15min')
        children = lower.reindex(wanted)
        if children.isna().any().any():
            if stamp in regular.index:
                missing_children += 1
            continue
        values = {'Open': children.Open.iloc[0], 'High': children.High.max(), 'Low': children.Low.min(),
                  'Close': children.Close.iloc[-1], 'Volume': children.Volume.sum()}
        different = [c for c in COLUMNS if not np.isclose(values[c], row[c], rtol=1e-7, atol=1e-6)]
        evidence = {'timestamp': stamp.isoformat(), 'columns': different,
                    'native_volume': float(row.Volume), 'sum_child_volume': float(values['Volume'])}
        if stamp in regular.index:
            if different:
                mismatches.append(evidence)
            else:
                matched += 1
        elif different:
            boundary_mismatches.append(evidence)
    return {'matched_full_interior_bars': matched, 'incomplete_child_groups': missing_children,
            'interior_mismatches': mismatches, 'boundary_mismatches': boundary_mismatches}


def run_probes(output, *, session=None, as_of=None, progress=print, replay_directory=None):
    """At most 40 fresh requests: short breadth + 6 boundaries + 2 action checks.

    4 earlier bootstrap responses may be reused. No retry/download loop, broker,
    scheduler, strategy or full-universe behavior is present.
    """
    root = Path(output)
    root.mkdir(parents=True, exist_ok=True)
    raw = Path(replay_directory) if replay_directory is not None else root / ('raw_' + datetime.now(TZ).strftime('%Y%m%d_%H%M%S'))
    if replay_directory is None:
        raw.mkdir(exist_ok=False)
    as_of = pd.Timestamp(as_of or datetime.now(TZ)).tz_convert(TZ)
    if session is None:
        session = requests.Session()  # Diagnostic-only, default zero retries.
        session.headers['User-Agent'] = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36'
    records, payloads, fresh, blocked = [], {}, 0, False

    def request(probe_id, ticker, interval, params, kind, bootstrap=False):
        nonlocal fresh, blocked
        entry = {'probe_id': probe_id, 'ticker': ticker, 'interval': interval, 'kind': kind,
                 'requested_params': dict(params), 'retrieved_at': datetime.now(TZ).isoformat()}
        try:
            bootstrap_path = root / f'bootstrap_{interval}.json'
            reuse = False
            if bootstrap and bootstrap_path.is_file():
                cached = bootstrap_path.read_bytes()
                try:
                    market_time = json.loads(cached)['chart']['result'][0]['meta']['regularMarketTime']
                    last_market = pd.Timestamp(market_time, unit='s', tz='UTC').tz_convert(TZ)
                    reuse = last_market.date() == as_of.date() and 0 <= (as_of - last_market).total_seconds() <= 86400
                except (KeyError, IndexError, ValueError, TypeError):
                    pass
            if reuse:
                content = cached
                entry.update(http_status=200, source='earlier_same_audit_bootstrap', raw_path=str(bootstrap_path))
            elif replay_directory is not None:
                path = raw / f'{probe_id}.json'
                content = path.read_bytes()
                entry.update(http_status=None, source='saved_actual_yahoo_response', raw_path=str(path),
                             retrieved_at=datetime.fromtimestamp(path.stat().st_mtime, TZ).isoformat(),
                             http_status_not_preserved=True)
            else:
                if blocked:
                    raise ValueError('Remaining network probes stopped after Yahoo access/rate limit')
                if fresh >= 40:
                    raise ValueError('Diagnostic request budget exceeded')
                fresh += 1
                query = dict(interval=interval, includePrePost='false', events='div,splits', **params)
                response = session.get(f'https://query1.finance.yahoo.com/v8/finance/chart/{ticker}', params=query, timeout=20)
                if response.status_code in (403, 429):
                    blocked = True
                content = response.content
                path = raw / f'{probe_id}.json'
                path.write_bytes(content)
                entry.update(http_status=response.status_code, source='direct_yahoo_chart', raw_path=str(path), url=response.url)
            entry['raw_sha256'] = sha256(content).hexdigest()
            payload = json.loads(content)
            payloads[probe_id] = payload
            if (entry['http_status'] or 0) >= 400 or payload.get('chart', {}).get('error'):
                entry.update(status='rejected', yahoo_error=payload.get('chart', {}).get('error'))
            elif interval == '1d':
                result = payload['chart']['result'][0]
                entry.update(status='ok', daily_reference={'rows': len(result.get('timestamp', [])),
                              'indicator_fields': list(result['indicators']), 'events': result.get('events', {})})
            else:
                start = pd.Timestamp(params['period1'], unit='s', tz='UTC').tz_convert(TZ) if 'period1' in params else None
                end = pd.Timestamp(params['period2'], unit='s', tz='UTC').tz_convert(TZ) if 'period2' in params else None
                entry.update(status='ok', analysis=analyze_payload(payload, interval, as_of, start, end))
        except (ValueError, KeyError, IndexError, TypeError, OSError, requests.RequestException) as error:
            entry.update(status='failed', error=str(error))
        records.append(entry)
        if progress:
            progress(f'{probe_id}: {entry["status"]}; ' + (f'{entry["analysis"]["raw_rows"]} raw bars' if 'analysis' in entry else str(entry.get('yahoo_error', entry.get('error', 'reference saved')))))
        return entry

    for ticker in BASKET:
        for interval in ('15m', '30m', '60m'):
            request(f'{ticker.replace(".IS", "")}_{interval}_5d', ticker, interval, {'range': '5d'}, 'short_breadth', ticker == 'ASELS.IS')
    request('ASELS_1h_alias_5d', 'ASELS.IS', '1h', {'range': '5d'}, 'alias_check', True)
    now = int(as_of.timestamp())
    for interval, maximum in (('15m', 60), ('30m', 60), ('60m', 730)):
        request(f'ASELS_{interval}_within_limit', 'ASELS.IS', interval,
                {'period1': now - maximum * 86400 + 3600, 'period2': now}, 'retention_success_boundary')
        request(f'ASELS_{interval}_beyond_limit', 'ASELS.IS', interval,
                {'period1': now - (maximum + 1) * 86400, 'period2': now - (maximum - 1) * 86400}, 'retention_rejection_boundary')
    reference = request('FROTO_daily_actions', 'FROTO.IS', '1d', {'range': '2y'}, 'corporate_action_reference')
    split_probe_id = None
    if reference['status'] == 'ok':
        splits = reference['daily_reference']['events'].get('splits', {})
        if splits:
            event = max(splits.values(), key=lambda item: item['date'])
            stamp = int(event['date'])
            if now - stamp < 725 * 86400:
                split_probe_id = 'FROTO_60m_split_window'
                request(split_probe_id, 'FROTO.IS', '60m', {'period1': stamp - 3 * 86400, 'period2': stamp + 3 * 86400}, 'split_window_reference')
    comparisons = {}
    for interval in ('30m', '60m'):
        try:
            comparisons[interval] = compare_aggregation(payloads['ASELS_15m_5d'], payloads[f'ASELS_{interval}_5d'], interval)
        except (KeyError, ValueError) as error:
            comparisons[interval] = {'unavailable': str(error)}
    try:
        _, hourly = frame_from_chart(payloads['ASELS_60m_5d'])
        _, alias = frame_from_chart(payloads['ASELS_1h_alias_5d'])
        alias_equal = hourly.equals(alias)
    except (KeyError, ValueError):
        alias_equal = None
    diagnosis = {'scope': 'Data feasibility and architecture audit only; no v2 strategy or backtest implemented.',
                 'as_of': as_of.isoformat(), 'fixed_basket': list(BASKET), 'fresh_requests': fresh,
                 'bootstrap_responses_reused': sum(r.get('source') == 'earlier_same_audit_bootstrap' for r in records),
                 'saved_responses_replayed': sum(r.get('source') == 'saved_actual_yahoo_response' for r in records),
                 'session_hypothesis': {'timezone': 'Europe/Istanbul', 'full_day_continuous': ['10:00', '18:00'],
                                        'policy': 'whole nominal interval inside explicit continuous-session window',
                                        'source': SESSION_SOURCE, 'not_a_complete_exchange_calendar': True},
                 'probes': records, 'native_vs_real_child_aggregation': comparisons,
                 '60m_1h_alias_equal_in_short_sample': alias_equal,
                 'split_probe_id': split_probe_id,
                 'limits_are_observations_not_provider_contract': True}
    (root / 'diagnosis.json').write_text(json.dumps(diagnosis, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    return diagnosis


def main(argv=None):
    parser = argparse.ArgumentParser(description='Bounded intraday data audit only; no strategy or backtest execution.')
    parser.add_argument('--probe-real', action='store_true', required=True, help='Explicitly perform the bounded Yahoo audit')
    parser.add_argument('--output', default='backtest_results/intraday_data_audit')
    args = parser.parse_args(argv)
    diagnosis = run_probes(args.output)
    print(f'Diagnosis: {(Path(args.output) / "diagnosis.json").resolve()}')
    return 0 if all(r['status'] == 'ok' for r in diagnosis['probes'] if r['kind'] == 'short_breadth') else 1


if __name__ == '__main__':
    raise SystemExit(main())
