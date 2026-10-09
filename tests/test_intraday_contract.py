"""Offline one-hour bounds/schema/session/replay/cache contract tests."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
from unittest.mock import Mock

import numpy as np
import pandas as pd

from intraday import CacheError, CacheMiss, GapError, IntradayError
from intraday.cache import IntradayCache, csv_bytes
from intraday.cli import main
from intraday.data import (COLUMNS, IntradayData, enforce_quality, finalize_diagnostics,
                          normalize_candles, validate_contract)
from intraday.provider import CacheProvider, CSVProvider, YahooProvider
from intraday.replay import SessionReplay, save_replay_audit
from intraday.session import BistCalendar, HOUR, TZ, aware_timestamp, is_complete
from tests.helpers import OfflineTestCase, response


START = pd.Timestamp('2026-10-06 10:00', tz=TZ)
END = pd.Timestamp('2026-10-06 18:00', tz=TZ)
ASOF = pd.Timestamp('2026-10-09 20:00', tz=TZ)


def raw_frame(index=None):
    index = pd.date_range('2026-10-06 10:30', periods=7, freq='1h', tz=TZ) if index is None else index
    return pd.DataFrame({'open': 100., 'high': 102., 'low': 99., 'close': 101., 'volume': 1000.}, index=index)


def chart(frame=None, ticker='ASELS.IS'):
    frame = raw_frame() if frame is None else frame
    values = {c: [None if pd.isna(v) else v for v in frame[c].tolist()] for c in COLUMNS}
    return {'chart': {'error': None, 'result': [{
        'meta': {'symbol': ticker, 'exchangeTimezoneName': 'Europe/Istanbul', 'dataGranularity': '1h', 'instrumentType': 'EQUITY'},
        'timestamp': [int(t.timestamp()) for t in frame.index],
        'indicators': {'quote': [values]},
    }]}}


def yahoo(frame=None, cache=None, ticker='ASELS.IS'):
    session = Mock()
    session.get.return_value = response(chart(frame, ticker))
    return YahooProvider(cache=cache, session=session), session


class BoundsAndSchemaTests(OfflineTestCase):
    def test_future_current_provider_row_is_excluded_hard_regression(self):
        frame = pd.concat([raw_frame(), raw_frame(pd.DatetimeIndex(['2026-10-09 18:00'], tz=TZ))])
        frame.iloc[-1, frame.columns.get_loc('close')] = 999999
        provider, _ = yahoo(frame)
        data = provider.fetch('ASELS.IS', START, END, as_of=ASOF)
        self.assertEqual(len(data.candles), 7)
        self.assertTrue((data.candles.index < END).all())
        self.assertEqual(data.diagnostics['outside_range_rows'], 1)
        self.assertEqual(data.candles.close.tolist(), [101] * 7)
        self.assertTrue(all(s.current_candle.timestamp < END for s in SessionReplay(data)))

    def test_rows_before_start_and_exact_exclusive_end_removed(self):
        source = raw_frame(pd.date_range('2026-10-06 09:30', periods=4, freq='1h', tz=TZ))
        start, end = source.index[1], source.index[3]
        frame, audit = normalize_candles(source, 'ASELS.IS', start, end, ASOF)
        self.assertEqual(list(frame.index), list(source.index[1:3]))
        self.assertEqual(audit['outside_range_rows'], 2)

    def test_end_inside_a_bar_never_exposes_post_end_ohlc(self):
        source = raw_frame().iloc[:2]
        end = pd.Timestamp('2026-10-06 12:15', tz=TZ)
        data, audit = normalize_candles(source, 'ASELS.IS', START, end, ASOF)
        self.assertEqual(len(data), 1)
        self.assertEqual(audit['events'][0]['detail'], 'crosses_requested_end')
        self.assertTrue((data.index + HOUR <= end).all())

    def test_out_of_range_malformed_prices_cannot_taint_dataset(self):
        source = pd.concat([raw_frame(), raw_frame(pd.DatetimeIndex(['2026-10-09 11:30'], tz=TZ))])
        source.loc[source.index[-1], :] = np.inf
        provider, _ = yahoo(source)
        data = provider.fetch('ASELS.IS', START, END, as_of=ASOF)
        self.assertEqual(len(data.candles), 7)
        self.assertEqual(data.diagnostics['events'][-1]['reason'], 'outside_requested_range')

    def test_utc_normalized_to_istanbul_without_date_collapse(self):
        source = raw_frame()
        source.index = source.index.tz_convert('UTC')
        frame, _ = normalize_candles(source, 'ASELS.IS', START, END, ASOF)
        self.assertEqual(str(frame.index.tz), 'Europe/Istanbul')
        self.assertEqual(frame.index.strftime('%H:%M').tolist(), ['10:30', '11:30', '12:30', '13:30', '14:30', '15:30', '16:30'])
        self.assertFalse(frame.index.has_duplicates)

    def test_naive_timestamp_requires_explicit_source_timezone(self):
        source = raw_frame()
        source.index = source.index.tz_localize(None)
        with self.assertRaises(IntradayError):
            normalize_candles(source, 'ASELS.IS', START, END, ASOF)
        frame, _ = normalize_candles(source, 'ASELS.IS', START, END, ASOF, source_timezone='Europe/Istanbul')
        self.assertEqual(len(frame), 7)
        with self.assertRaises(IntradayError):
            aware_timestamp('2026-10-06 10:30')

    def test_nan_infinity_negative_volume_and_bad_high_low_explicitly_removed(self):
        variants = [('close', np.nan, 'missing_ohlcv'), ('close', np.inf, 'invalid_ohlc'),
                    ('volume', -1, 'invalid_volume'), ('high', 98, 'invalid_ohlc'),
                    ('low', 103, 'invalid_ohlc'), ('open', 0, 'invalid_ohlc')]
        for column, value, reason in variants:
            with self.subTest(column=column, value=value):
                source = raw_frame()
                source.iloc[2, source.columns.get_loc(column)] = value
                frame, audit = normalize_candles(source, 'ASELS.IS', START, END, ASOF)
                self.assertEqual(len(frame), 6)
                self.assertEqual(audit['events'][0]['reason'], reason)
                diagnostics = finalize_diagnostics(frame, audit, BistCalendar(), START, END, ASOF)
                self.assertEqual(diagnostics['missing_candle_gaps'][0]['missing_timestamp'], source.index[2].isoformat())
                with self.assertRaises(GapError):
                    enforce_quality(diagnostics, 'strict')

    def test_nonnumeric_boolean_and_missing_schema_rejected(self):
        for value in ('broken', True):
            source = raw_frame().astype(object)
            source.iloc[1, source.columns.get_loc('volume')] = value
            frame, audit = normalize_candles(source, 'ASELS.IS', START, END, ASOF)
            self.assertEqual(len(frame), 6)
            self.assertEqual(audit['events'][0]['detail'], 'nonnumeric_or_boolean_ohlcv')
        with self.assertRaises(IntradayError):
            normalize_candles(raw_frame().drop(columns='volume'), 'ASELS.IS', START, END, ASOF)

    def test_duplicate_identical_rows_deterministic_and_sorted(self):
        source = pd.concat([raw_frame().iloc[::-1], raw_frame().iloc[[2]]])
        first, audit = normalize_candles(source, 'ASELS.IS', START, END, ASOF)
        second, _ = normalize_candles(source, 'ASELS.IS', START, END, ASOF)
        pd.testing.assert_frame_equal(first, second)
        self.assertTrue(first.index.is_monotonic_increasing)
        self.assertEqual(audit['duplicates'], 1)
        self.assertEqual(audit['events'][0]['reason'], 'duplicate_timestamp')

    def test_first_valid_duplicate_wins_when_first_occurrence_is_malformed(self):
        bad = raw_frame().iloc[[1]].copy()
        bad['close'] = np.nan
        source = pd.concat([bad, raw_frame()])
        frame, audit = normalize_candles(source, 'ASELS.IS', START, END, ASOF)
        self.assertEqual(len(frame), 7)
        self.assertEqual(audit['duplicates'], 1)
        self.assertEqual(frame.close.iloc[1], 101)

    def test_conflicting_valid_source_duplicates_refused(self):
        other = raw_frame().iloc[[2]].copy()
        other['volume'] = 500
        provider, _ = yahoo(pd.concat([raw_frame(), other]))
        with self.assertRaisesRegex(IntradayError, 'Conflicting source duplicates'):
            provider.fetch('ASELS.IS', START, END, as_of=ASOF, gap_policy='warn')

    def test_payload_schema_ticker_timezone_granularity_checks(self):
        for mutate in (lambda r: r['meta'].update(symbol='FROTO.IS'),
                       lambda r: r['meta'].update(exchangeTimezoneName='UTC'),
                       lambda r: r['meta'].update(dataGranularity='30m'),
                       lambda r: r['meta'].update(instrumentType='ETF'),
                       lambda r: r['timestamp'].pop(),
                       lambda r: r['timestamp'].__setitem__(0, True)):
            body = chart()
            mutate(body['chart']['result'][0])
            session = Mock()
            session.get.return_value = response(body)
            with self.assertRaises(IntradayError):
                YahooProvider(session=session).fetch('ASELS.IS', START, END, as_of=ASOF)


class SessionAndGapTests(OfflineTestCase):
    def test_full_day_native_grid_and_boundaries(self):
        calendar = BistCalendar()
        session = calendar.session('2026-10-06')
        self.assertEqual((session.start.hour, session.end.hour), (10, 18))
        self.assertEqual(session.accepted_starts().strftime('%H:%M').tolist(), ['10:30','11:30','12:30','13:30','14:30','15:30','16:30'])
        for clock in ('09:30', '10:00', '17:30', '18:00'):
            self.assertFalse(calendar.classify(pd.Timestamp('2026-10-06 ' + clock, tz=TZ))[0])
        self.assertTrue(calendar.classify(pd.Timestamp('2026-10-06 10:30', tz=TZ))[0])

    def test_half_day_calendar_and_holiday_no_fake_gaps(self):
        calendar = BistCalendar()
        half = calendar.session('2026-03-19')
        self.assertTrue(half.half_day)
        self.assertEqual(half.accepted_starts().strftime('%H:%M').tolist(), ['10:30', '11:30'])
        self.assertFalse(calendar.session('2026-03-20').open)
        self.assertFalse(calendar.session('2026-10-10').open)
        self.assertEqual(len(calendar.expected(pd.Timestamp('2026-03-19', tz=TZ), pd.Timestamp('2026-03-23', tz=TZ), ASOF)), 2)

    def test_unknown_year_requires_explicit_calendar(self):
        with self.assertRaisesRegex(IntradayError, 'Unsupported BIST calendar year'):
            BistCalendar().session('2027-01-04')

    def test_boundary_zero_volume_removed_interior_zero_volume_retained(self):
        source = pd.concat([raw_frame(pd.DatetimeIndex(['2026-10-06 09:30'], tz=TZ)), raw_frame(),
                            raw_frame(pd.DatetimeIndex(['2026-10-06 18:00'], tz=TZ))])
        source['volume'] = 0
        start, end = pd.Timestamp('2026-10-06 00:00', tz=TZ), pd.Timestamp('2026-10-07 00:00', tz=TZ)
        frame, audit = normalize_candles(source, 'ASELS.IS', start, end, ASOF)
        self.assertEqual(len(frame), 7)
        self.assertEqual(audit['valid_zero_volume_rows'], 7)
        self.assertEqual(audit['outside_session_rows'], 2)
        self.assertEqual(sum(e['reason'] == 'zero_volume_boundary' for e in audit['events']), 2)

    def test_expected_sequence_and_strict_vs_warn(self):
        provider, _ = yahoo()
        complete = provider.fetch('ASELS.IS', START, END, as_of=ASOF)
        self.assertEqual(complete.diagnostics['missing_candle_gaps'], [])
        broken = raw_frame().drop(raw_frame().index[3])
        provider, _ = yahoo(broken)
        with self.assertRaises(GapError) as caught:
            provider.fetch('ASELS.IS', START, END, as_of=ASOF)
        warning = provider.fetch('ASELS.IS', START, END, as_of=ASOF, gap_policy='warn')
        self.assertEqual(len(warning.candles), 6)
        self.assertEqual(len(warning.diagnostics['missing_candle_gaps']), 1)
        self.assertIn('session_date', caught.exception.diagnostics['missing_candle_gaps'][0])

    def test_whole_missing_session_is_detected(self):
        provider, _ = yahoo()
        with self.assertRaises(GapError) as caught:
            provider.fetch('ASELS.IS', START, pd.Timestamp('2026-10-08', tz=TZ), as_of=ASOF)
        self.assertEqual(len(caught.exception.diagnostics['missing_candle_gaps']), 7)

    def test_completion_exact_boundary_and_incomplete_exclusion(self):
        stamp = raw_frame().index[0]
        self.assertFalse(is_complete(stamp, stamp + HOUR - pd.Timedelta(nanoseconds=1)))
        self.assertTrue(is_complete(stamp, stamp + HOUR))
        provider, _ = yahoo()
        data = provider.fetch('ASELS.IS', START, END, as_of=stamp + HOUR)
        self.assertEqual(len(data.candles), 1)
        self.assertEqual(data.diagnostics['expected_completed_candles'], 1)
        self.assertEqual(data.diagnostics['incomplete_rows'], 6)

    def test_known_null_hourly_slot_is_explicit_gap(self):
        index = pd.date_range('2026-04-20 10:30', periods=7, freq='1h', tz=TZ)
        source = raw_frame(index)
        source.iloc[0, :] = np.nan
        provider, _ = yahoo(source)
        with self.assertRaises(GapError) as caught:
            provider.fetch('ASELS.IS', pd.Timestamp('2026-04-20', tz=TZ), pd.Timestamp('2026-04-21', tz=TZ), as_of=ASOF)
        self.assertEqual(caught.exception.diagnostics['missing_candle_gaps'][0]['missing_timestamp'], '2026-04-20T10:30:00+03:00')
        self.assertEqual(caught.exception.diagnostics['events'][0]['reason'], 'missing_ohlcv')


class ReplayTests(OfflineTestCase):
    def dataset(self):
        return yahoo()[0].fetch('ASELS.IS', START, END, as_of=ASOF)

    def test_future_is_never_visible_and_history_grows(self):
        snapshots = list(SessionReplay(self.dataset()))
        self.assertEqual([len(s.history) for s in snapshots], list(range(1, 8)))
        for step in snapshots:
            self.assertTrue((step.history.index + HOUR <= step.replay_timestamp).all())
            self.assertEqual(step.current_candle.bar_end, step.replay_timestamp)
            self.assertTrue(step.current_candle.tradable)

    def test_mutating_returned_history_does_not_affect_later_steps(self):
        iterator = iter(SessionReplay(self.dataset()))
        first = next(iterator)
        first.history.iloc[0, 0] = 999999
        second = next(iterator)
        self.assertEqual(second.history.open.iloc[0], 100)

    def test_incomplete_candle_not_exposed_at_replay_cutoff(self):
        cutoff = pd.Timestamp('2026-10-06 12:00', tz=TZ)
        replay = SessionReplay(self.dataset(), as_of=cutoff)
        steps = list(replay)
        self.assertEqual(len(steps), 1)
        self.assertEqual(steps[0].current_candle.timestamp.hour, 10)

    def test_strict_replay_stops_at_affected_gap_segment(self):
        broken = raw_frame().drop(raw_frame().index[3])
        data = yahoo(broken)[0].fetch('ASELS.IS', START, END, as_of=ASOF, gap_policy='warn')
        iterator = iter(SessionReplay(data))
        self.assertEqual([len(next(iterator).history) for _ in range(3)], [1, 2, 3])
        with self.assertRaises(GapError):
            next(iterator)
        self.assertEqual(len(list(SessionReplay(data, gap_policy='warn'))), 6)

    def test_trailing_gap_cannot_end_replay_silently(self):
        data = yahoo(raw_frame().iloc[:-1])[0].fetch('ASELS.IS', START, END, as_of=ASOF, gap_policy='warn')
        iterator = iter(SessionReplay(data))
        for _ in range(6):
            next(iterator)
        with self.assertRaises(GapError):
            next(iterator)

    def test_replay_cannot_extend_provider_asof(self):
        data = yahoo()[0].fetch('ASELS.IS', START, END, as_of=pd.Timestamp('2026-10-06 11:30', tz=TZ))
        self.assertEqual(len(list(SessionReplay(data, as_of=ASOF))), 1)


class CacheTests(OfflineTestCase):
    def test_first_fetch_miss_second_identical_hit_and_offline_equal(self):
        cache = IntradayCache('cache')
        provider, session = yahoo(cache=cache)
        first = provider.fetch('ASELS.IS', START, END, as_of=ASOF)
        second = provider.fetch('ASELS.IS', START, END, as_of=ASOF)
        offline = CacheProvider(cache).fetch('ASELS.IS', START, END, as_of=ASOF)
        self.assertEqual(session.get.call_count, 1)
        self.assertFalse(first.diagnostics['cache_hit'])
        self.assertTrue(second.diagnostics['cache_hit'])
        self.assertEqual(second.diagnostics['downloaded_rows'], 0)
        pd.testing.assert_frame_equal(first.candles, second.candles)
        pd.testing.assert_frame_equal(first.candles, offline.candles)

    def test_safe_range_merge_and_immutable_snapshots(self):
        cache = IntradayCache('cache')
        session = Mock()
        session.get.side_effect = [response(chart(raw_frame().iloc[:3])), response(chart())]
        provider = YahooProvider(cache=cache, session=session)
        provider.fetch('ASELS.IS', START, pd.Timestamp('2026-10-06 13:30', tz=TZ), as_of=ASOF)
        before = cache.load('ASELS.IS')[1]['csv_sha256']
        extended = provider.fetch('ASELS.IS', START, END, as_of=ASOF)
        self.assertEqual(len(extended.candles), 7)
        self.assertEqual(extended.diagnostics['cache_identical_overlaps'], 3)
        self.assertTrue((cache.directory('ASELS.IS') / f'{before}.csv').is_file())
        self.assertEqual(session.get.call_count, 2)

    def test_malformed_overlap_never_overwrites_valid_cached_row(self):
        cache = IntradayCache('cache')
        broken = raw_frame()
        broken.iloc[1, broken.columns.get_loc('close')] = np.nan
        session = Mock()
        session.get.side_effect = [response(chart(raw_frame().iloc[:3])), response(chart(broken))]
        provider = YahooProvider(cache=cache, session=session)
        provider.fetch('ASELS.IS', START, pd.Timestamp('2026-10-06 13:30', tz=TZ), as_of=ASOF)
        data = provider.fetch('ASELS.IS', START, END, as_of=ASOF)
        self.assertEqual(len(data.candles), 7)
        self.assertEqual(data.candles.close.iloc[1], 101)
        self.assertEqual(data.diagnostics['validated_cached_rows_reused'], 1)
        self.assertTrue(any(e['reason'] == 'missing_ohlcv' for e in data.diagnostics['events']))

    def test_valid_cache_revision_conflict_refused_without_mutation(self):
        cache = IntradayCache('cache')
        changed = raw_frame()
        changed.iloc[0, changed.columns.get_loc('volume')] = 2000
        session = Mock()
        session.get.side_effect = [response(chart(raw_frame().iloc[:3])), response(chart(changed))]
        provider = YahooProvider(cache=cache, session=session)
        first = provider.fetch('ASELS.IS', START, pd.Timestamp('2026-10-06 13:30', tz=TZ), as_of=ASOF)
        manifest = (cache.directory('ASELS.IS') / 'manifest.json').read_bytes()
        with self.assertRaises(CacheError):
            provider.fetch('ASELS.IS', START, END, as_of=ASOF)
        self.assertEqual((cache.directory('ASELS.IS') / 'manifest.json').read_bytes(), manifest)
        self.assertEqual(cache.load('ASELS.IS')[0].volume.iloc[0], first.candles.volume.iloc[0])

    def test_known_gap_reproduces_offline_without_another_network_call(self):
        cache = IntradayCache('cache')
        provider, session = yahoo(raw_frame().drop(raw_frame().index[3]), cache=cache)
        with self.assertRaises(GapError):
            provider.fetch('ASELS.IS', START, END, as_of=ASOF)
        with self.assertRaises(GapError):
            CacheProvider(cache).fetch('ASELS.IS', START, END, as_of=ASOF)
        self.assertEqual(session.get.call_count, 1)

    def test_incomplete_fetch_does_not_claim_future_cache_coverage(self):
        cache = IntradayCache('cache')
        provider, session = yahoo(cache=cache)
        provider.fetch('ASELS.IS', START, END, as_of=pd.Timestamp('2026-10-06 11:30', tz=TZ))
        with self.assertRaises(CacheMiss):
            CacheProvider(cache).fetch('ASELS.IS', START, END, as_of=ASOF)
        data = provider.fetch('ASELS.IS', START, END, as_of=ASOF)
        self.assertEqual(len(data.candles), 7)
        self.assertEqual(session.get.call_count, 2)

    def test_cache_integrity_and_calendar_version_mismatch_rejected(self):
        cache = IntradayCache('cache')
        yahoo(cache=cache)[0].fetch('ASELS.IS', START, END, as_of=ASOF)
        folder = cache.directory('ASELS.IS')
        manifest_path = folder / 'manifest.json'
        manifest = json.loads(manifest_path.read_text())
        snapshot = folder / (manifest['csv_sha256'] + '.csv')
        content = snapshot.read_bytes()
        snapshot.write_bytes(content + b'corruption')
        with self.assertRaises(CacheError):
            cache.load('ASELS.IS')
        snapshot.write_bytes(content)
        manifest['calendar_version'] = 'unknown'
        manifest_path.write_text(json.dumps(manifest))
        with self.assertRaises(CacheError):
            cache.load('ASELS.IS')

    def test_missing_cache_and_concurrent_writer_lock_fail_explicitly(self):
        cache = IntradayCache('cache')
        with self.assertRaises(CacheMiss):
            CacheProvider(cache).fetch('ASELS.IS', START, END, as_of=ASOF)
        folder = cache.directory('ASELS.IS')
        folder.mkdir(parents=True)
        (folder / '.write.lock').write_text('other writer')
        with self.assertRaises(CacheError):
            yahoo(cache=cache)[0].fetch('ASELS.IS', START, END, as_of=ASOF)

    def test_csv_contract_timezone_and_bounds_same_as_yahoo(self):
        raw = raw_frame()
        raw.index.name = 'timestamp'
        Path('candles.csv').write_bytes(csv_bytes(raw))
        offline = CSVProvider('candles.csv').fetch('ASELS.IS', START, END, as_of=ASOF)
        online = yahoo()[0].fetch('ASELS.IS', START, END, as_of=ASOF)
        pd.testing.assert_frame_equal(offline.candles, online.candles)
        naive = raw.copy()
        naive.index = naive.index.tz_localize(None)
        naive.to_csv('naive.csv')
        with self.assertRaises(IntradayError):
            CSVProvider('naive.csv').fetch('ASELS.IS', START, END, as_of=ASOF)
        accepted = CSVProvider('naive.csv', source_timezone='Europe/Istanbul').fetch('ASELS.IS', START, END, as_of=ASOF)
        self.assertEqual(len(accepted.candles), 7)


class MetadataAndCorporateTests(OfflineTestCase):
    def test_corporate_events_recorded_but_future_events_excluded(self):
        body = chart()
        body['chart']['result'][0]['events'] = {'splits': {
            'past': {'date': int(START.timestamp()), 'numerator': 10, 'denominator': 1},
            'future': {'date': int(ASOF.timestamp()), 'numerator': 2, 'denominator': 1}}}
        session = Mock()
        session.get.return_value = response(body)
        data = YahooProvider(session=session).fetch('ASELS.IS', START, END, as_of=ASOF)
        self.assertEqual(len(data.diagnostics['corporate_action_events']), 1)
        self.assertEqual(data.diagnostics['price_basis'], 'unverified')
        self.assertFalse(data.diagnostics['corporate_action_events'][0]['adjustment_basis_verified'])

    def test_cached_and_replay_corporate_event_lists_obey_narrower_time_cutoff(self):
        body = chart()
        body['chart']['result'][0]['events'] = {'splits': {
            'early': {'date': int(START.timestamp()), 'numerator': 10, 'denominator': 1},
            'later': {'date': int(pd.Timestamp('2026-10-06 12:30', tz=TZ).timestamp()), 'numerator': 2, 'denominator': 1}}}
        session = Mock()
        session.get.return_value = response(body)
        cache = IntradayCache('cache')
        data = YahooProvider(cache=cache, session=session).fetch('ASELS.IS', START, END, as_of=ASOF)
        cutoff = pd.Timestamp('2026-10-06 11:30', tz=TZ)
        replay = SessionReplay(data, as_of=cutoff)
        self.assertEqual(len(replay.diagnostics['corporate_action_events']), 1)
        narrow = CacheProvider(cache).fetch('ASELS.IS', START, pd.Timestamp('2026-10-06 12:30', tz=TZ), as_of=ASOF)
        self.assertEqual(len(narrow.diagnostics['corporate_action_events']), 1)
        self.assertEqual(session.get.call_count, 1)

    def test_suspicious_discontinuity_flag_does_not_invent_adjustment(self):
        source = raw_frame()
        source.loc[source.index[3:], COLUMNS[:4]] *= 2
        data = yahoo(source)[0].fetch('ASELS.IS', START, END, as_of=ASOF)
        self.assertEqual(data.candles.open.iloc[3], 200)
        self.assertEqual(len(data.diagnostics['suspicious_discontinuities']), 1)

    def test_replay_audit_required_metadata_and_csv(self):
        data = yahoo()[0].fetch('ASELS.IS', START, END, as_of=ASOF)
        replay = SessionReplay(data)
        directory = save_replay_audit(replay.diagnostics, candles=data.candles, run_id='offline')
        audit = json.loads((directory / 'diagnostics.json').read_text())
        for field in ('ticker', 'requested_start', 'requested_end', 'actual_first_candle', 'actual_last_candle',
                      'timezone', 'interval', 'downloaded_rows', 'removed_rows', 'duplicates', 'outside_range_rows',
                      'outside_session_rows', 'missing_candle_gaps', 'final_usable_rows', 'provider_source', 'cache_hit'):
            self.assertIn(field, audit)
        self.assertTrue((directory / 'candles.csv').is_file())
        self.assertTrue((directory / 'summary.md').is_file())

    def test_invalid_request_and_cli_offline_failure_create_audit(self):
        for start, end in ((END, START), (START, START)):
            with self.assertRaises(IntradayError):
                yahoo()[0].fetch('ASELS.IS', start, end, as_of=ASOF)
        with self.assertRaises(IntradayError):
            yahoo()[0].fetch('../secret', START, END, as_of=ASOF)
        from contextlib import redirect_stderr
        from io import StringIO
        with redirect_stderr(StringIO()):
            status = main(['--offline', '--ticker', 'ASELS.IS', '--start', START.isoformat(), '--end', END.isoformat()])
        self.assertEqual(status, 1)
        self.assertEqual(len(list(Path('backtest_results/intraday_replay_audit').glob('*/diagnostics.json'))), 1)
        path = next(Path('backtest_results/intraday_replay_audit').glob('*/diagnostics.json'))
        failure = json.loads(path.read_text())
        self.assertIsNone(failure['downloaded_rows'])
        self.assertIsNone(failure['final_usable_rows'])
        self.assertFalse(failure['gap_detection_performed'])
