"""Offline diagnostic helpers only; no intraday strategy implementation."""
import json
from pathlib import Path
from unittest.mock import Mock

import pandas as pd

from research.intraday_audit import (normalize_timestamps, deduplicate_candles,
                                    filter_session, missing_candles, frame_from_chart,
                                    analyze_payload, compare_aggregation, run_probes)
from tests.helpers import OfflineTestCase


def frame(index):
    return pd.DataFrame({'Open': 100., 'High': 102., 'Low': 99., 'Close': 101., 'Volume': 1000.}, index=index)


def payload(index):
    data = frame(index)
    return {'chart': {'error': None, 'result': [{
        'meta': {'exchangeTimezoneName': 'Europe/Istanbul', 'gmtoffset': 10800, 'dataGranularity': '15m'},
        'timestamp': [int(t.timestamp()) for t in index],
        'indicators': {'quote': [{c.lower(): data[c].tolist() for c in data}]},
    }]}}


class IntradayDiagnosticTests(OfflineTestCase):
    def test_utc_normalization_preserves_intraday_time(self):
        index = pd.DatetimeIndex(['2026-10-06 07:00', '2026-10-06 07:15'], tz='UTC')
        local = normalize_timestamps(index)
        self.assertEqual(str(local.tz), 'Europe/Istanbul')
        self.assertEqual(local.strftime('%H:%M').tolist(), ['10:00', '10:15'])
        self.assertEqual(local[1] - local[0], pd.Timedelta(minutes=15))

    def test_naive_timestamps_need_explicit_source_timezone(self):
        index = pd.DatetimeIndex(['2026-10-06 10:00'])
        with self.assertRaisesRegex(ValueError, 'require source_tz'):
            normalize_timestamps(index)
        self.assertEqual(normalize_timestamps(index, source_tz='Europe/Istanbul')[0].hour, 10)

    def test_invalid_timestamp_rejected(self):
        with self.assertRaises(ValueError):
            normalize_timestamps(pd.DatetimeIndex([pd.NaT], tz='UTC'))

    def test_session_filter_keeps_only_complete_continuous_bars(self):
        index = pd.date_range('2026-10-06 09:30', '2026-10-06 18:00', freq='30min', tz='Europe/Istanbul')
        actual = filter_session(frame(index), 30, opening='10:00', closing='18:00')
        self.assertEqual(len(actual), 16)
        self.assertEqual((actual.index[0].hour, actual.index[-1].strftime('%H:%M')), (10, '17:30'))
        self.assertEqual(str(actual.index.tz), 'Europe/Istanbul')

    def test_hourly_offset_boundaries_are_not_relabelled_or_truncated(self):
        index = pd.date_range('2026-10-06 09:30', '2026-10-06 17:30', freq='60min', tz='Europe/Istanbul')
        actual = filter_session(frame(index), 60, opening='10:00', closing='18:00')
        self.assertEqual(len(actual), 7)
        self.assertEqual((actual.index[0].strftime('%H:%M'), actual.index[-1].strftime('%H:%M')), ('10:30', '16:30'))

    def test_half_day_explicit_session_and_weekend_filter(self):
        index = pd.date_range('2026-03-19 10:00', '2026-03-19 13:00', freq='30min', tz='Europe/Istanbul')
        actual = filter_session(frame(index), 30, opening='10:00', closing='12:30')
        self.assertEqual(len(actual), 5)
        weekend = frame(pd.DatetimeIndex(['2026-10-10 10:00'], tz='Europe/Istanbul'))
        self.assertTrue(filter_session(weekend, 30, opening='10:00', closing='18:00').empty)

    def test_duplicate_first_source_and_conflict_are_reported(self):
        index = pd.DatetimeIndex(['2026-10-06 10:15', '2026-10-06 10:00', '2026-10-06 10:00'], tz='Europe/Istanbul')
        source = frame(index)
        source.iloc[2, source.columns.get_loc('Volume')] = 999
        canonical, issues = deduplicate_candles(source)
        self.assertEqual(len(canonical), 2)
        self.assertTrue(canonical.index.is_monotonic_increasing)
        self.assertEqual(canonical.Volume.iloc[0], 1000)
        self.assertEqual(issues['duplicate_rows'], 1)
        self.assertEqual(issues['conflicting_timestamps'], ['2026-10-06T10:00:00+03:00'])
        self.assertEqual(len(source), 3)

    def test_identical_duplicate_is_not_marked_conflicting(self):
        index = pd.DatetimeIndex(['2026-10-06 10:00'] * 2, tz='Europe/Istanbul')
        canonical, issues = deduplicate_candles(frame(index))
        self.assertEqual(issues['duplicate_rows'], 1)
        self.assertEqual(issues['conflicting_timestamps'], [])

    def test_missing_candle_is_detected_without_filling(self):
        expected = pd.date_range('2026-10-06 10:00', periods=4, freq='15min', tz='Europe/Istanbul')
        actual = expected.delete(2)
        missing = missing_candles(actual, 15, {'2026-10-06': ('10:00', '11:00')})
        self.assertEqual(list(missing), [expected[2]])
        self.assertEqual(len(actual), 3)

    def test_holiday_and_overnight_gaps_are_not_missing_bars(self):
        index = pd.DatetimeIndex(['2026-10-06 10:00', '2026-10-08 10:00'], tz='Europe/Istanbul')
        missing = missing_candles(index, 30, {'2026-10-06': ('10:00', '10:30'),
                                             '2026-10-07': None, '2026-10-08': ('10:00', '10:30')})
        self.assertEqual(len(missing), 0)

    def test_completely_missing_known_session_is_detectable(self):
        index = pd.DatetimeIndex(['2026-10-06 10:00'], tz='Europe/Istanbul')
        missing = missing_candles(index, 30, {'2026-10-06': ('10:00', '10:30'), '2026-10-07': ('10:00', '11:00')})
        self.assertEqual(len(missing), 2)

    def test_hourly_phase_grid_matches_vendor_alignment(self):
        index = pd.date_range('2026-10-06 10:30', periods=7, freq='60min', tz='Europe/Istanbul')
        self.assertEqual(len(missing_candles(index, 60, {'2026-10-06': ('10:00', '18:00')}, phase_minute=30)), 0)

    def test_raw_parser_keeps_null_and_index_timezone_for_diagnosis(self):
        index = pd.date_range('2026-10-06 10:00', periods=2, freq='15min', tz='Europe/Istanbul')
        data = payload(index)
        data['chart']['result'][0]['indicators']['quote'][0]['volume'][1] = None
        _, parsed = frame_from_chart(data)
        self.assertTrue(pd.isna(parsed.Volume.iloc[1]))
        self.assertTrue(parsed.index.equals(index))

    def test_analyzer_exposes_nonfinite_values_partial_bar_and_future_append(self):
        index = pd.date_range('2026-10-06 10:00', periods=3, freq='15min', tz='Europe/Istanbul')
        data = payload(index)
        data['chart']['result'][0]['indicators']['quote'][0]['close'][1] = None
        audit = analyze_payload(data, '15m', index[2] + pd.Timedelta(minutes=5), requested_end=index[2])
        self.assertEqual(audit['null_cells']['Close'], 1)
        self.assertEqual(audit['partial_at_retrieval_rows'], 1)
        self.assertEqual(audit['outside_requested_range_rows'], 1)
        self.assertEqual(audit['raw_rows'], 3)

    def test_aggregation_requires_all_real_children(self):
        low_index = pd.date_range('2026-10-06 10:00', periods=4, freq='15min', tz='Europe/Istanbul')
        high_index = pd.date_range('2026-10-06 10:00', periods=2, freq='30min', tz='Europe/Istanbul')
        lower, higher = payload(low_index), payload(high_index)
        higher['chart']['result'][0]['indicators']['quote'][0]['volume'] = [2000, 2000]
        match = compare_aggregation(lower, higher, '30m')
        self.assertEqual(match['matched_full_interior_bars'], 2)
        broken = payload(low_index.delete(1))
        match = compare_aggregation(broken, higher, '30m')
        self.assertEqual(match['incomplete_child_groups'], 1)

    def test_failed_network_probes_still_write_diagnosis_and_stay_bounded(self):
        session = Mock()
        session.get.side_effect = requests_error()
        result = run_probes('audit', session=session, as_of=pd.Timestamp('2026-10-09 20:00', tz='Europe/Istanbul'), progress=None)
        self.assertLessEqual(session.get.call_count, 40)
        self.assertTrue(Path('audit/diagnosis.json').is_file())
        self.assertTrue(all(r['status'] == 'failed' for r in result['probes']))
        json.loads(Path('audit/diagnosis.json').read_text())

    def test_successful_probe_matrix_finishes_aggregation_and_json_export_offline(self):
        session = Mock()
        def get(url, params, timeout):
            interval = params['interval']
            minutes = {'15m': 15, '30m': 30, '60m': 60, '1h': 60, '1d': 1440}[interval]
            index = pd.date_range('2026-10-09 10:00', periods=max(1, 60 // minutes), freq=f'{minutes}min', tz='Europe/Istanbul')
            body = payload(index)
            body['chart']['result'][0]['meta']['dataGranularity'] = interval
            body['chart']['result'][0]['indicators']['quote'][0]['volume'] = [minutes / 15 * 1000] * len(index)
            result = Mock(status_code=200, url=url)
            result.content = json.dumps(body).encode()
            return result
        session.get.side_effect = get
        diagnosis = run_probes('audit_success', session=session,
                               as_of=pd.Timestamp('2026-10-09 20:00', tz='Europe/Istanbul'), progress=None)
        self.assertEqual(diagnosis['native_vs_real_child_aggregation']['30m']['matched_full_interior_bars'], 2)
        self.assertEqual(diagnosis['native_vs_real_child_aggregation']['60m']['matched_full_interior_bars'], 1)
        self.assertTrue(diagnosis['60m_1h_alias_equal_in_short_sample'])
        self.assertTrue(Path('audit_success/diagnosis.json').is_file())

    def test_access_rate_limit_stops_remaining_network_requests(self):
        session = Mock()
        response = Mock(status_code=429, url='https://query1.finance.yahoo.com/v8/finance/chart/ASELS.IS')
        response.content = json.dumps({'chart': {'result': None, 'error': {'code': 'Too Many Requests'}}}).encode()
        session.get.return_value = response
        diagnosis = run_probes('audit_rate', session=session, as_of=pd.Timestamp('2026-10-09 20:00', tz='Europe/Istanbul'), progress=None)
        self.assertEqual(session.get.call_count, 1)
        self.assertEqual(diagnosis['fresh_requests'], 1)
        self.assertIn('stopped after Yahoo', diagnosis['probes'][1]['error'])


def requests_error():
    import requests
    return requests.ConnectionError('Mocked offline failure')
