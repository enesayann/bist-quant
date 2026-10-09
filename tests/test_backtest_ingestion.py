"""Offline provider cleaning, audit visibility and missing-session execution."""
from copy import deepcopy
import json
from unittest.mock import Mock

import numpy as np
import pandas as pd

from backtest.data import CSVProvider, YahooProvider, clean_history
from backtest.engine import run_backtest
from backtest.report import save_report
from tests.helpers import OfflineTestCase, response
from tests.test_backtest_signals import historical_frame, test_signal


class CleaningTests(OfflineTestCase):
    def frame(self):
        return historical_frame(100)

    def test_one_nan_ohlc_row_removed_and_diagnosed(self):
        frame = self.frame()
        day = frame.index[10]
        frame.loc[day, 'Close'] = np.nan
        cleaned = clean_history(frame, 'ASELS.IS')
        self.assertEqual(len(cleaned), 99)
        self.assertNotIn(day, cleaned.index)
        audit = cleaned.attrs['validation']
        self.assertEqual((audit['rows_downloaded'], audit['rows_removed'], audit['usable_rows']), (100, 1, 99))
        row = audit['removed_rows'][0]
        self.assertEqual((row['ticker'], row['date'], row['reason']), ('ASELS.IS', str(day.date()), 'missing Close'))
        self.assertIsNone(row['values']['Close'])
        pd.testing.assert_frame_equal(cleaned, frame.drop(index=day))

    def test_missing_open_removed_at_provider_boundary(self):
        frame = self.frame()
        frame.iloc[10, frame.columns.get_loc('Open')] = np.nan
        cleaned = clean_history(frame, 'ASELS.IS')
        self.assertEqual(len(cleaned), 99)
        self.assertEqual(cleaned.attrs['validation']['removed_rows'][0]['category'], 'missing_ohlc')

    def test_missing_volume_drops_whole_candle_without_inventing_volume(self):
        frame = self.frame()
        frame.loc[frame.index[10], 'Volume'] = np.nan
        cleaned = clean_history(frame, 'ASELS.IS')
        self.assertNotIn(frame.index[10], cleaned.index)
        self.assertEqual(cleaned.attrs['validation']['removed_rows'][0]['category'], 'missing_volume')
        pd.testing.assert_series_equal(cleaned.Volume, frame.Volume.drop(frame.index[10]))

    def test_all_null_yahoo_style_candle_is_removed(self):
        frame = self.frame()
        frame.loc[frame.index[10], :] = np.nan
        cleaned = clean_history(frame, 'ASELS.IS')
        self.assertEqual(len(cleaned), 99)
        self.assertEqual(cleaned.attrs['validation']['removed_rows'][0]['reason'], 'missing Open, High, Low, Close, Volume')

    def test_infinity_rejected_with_date_and_column(self):
        for column in ('Open', 'High', 'Low', 'Close', 'Volume'):
            for value in (np.inf, -np.inf):
                with self.subTest(column=column, value=value):
                    frame = self.frame()
                    frame.loc[frame.index[10], column] = value
                    with self.assertRaisesRegex(ValueError, f'ASELS.IS {frame.index[10].date()}.*infinite {column}'):
                        clean_history(frame, 'ASELS.IS')

    def test_negative_volume_is_not_silently_dropped(self):
        frame = self.frame()
        frame.loc[frame.index[10], 'Volume'] = -1
        with self.assertRaisesRegex(ValueError, f'{frame.index[10].date()}.*negative Volume'):
            clean_history(frame, 'ASELS.IS')

    def test_high_below_low_rejected(self):
        frame = self.frame()
        frame.loc[frame.index[10], 'High'] = frame.Low.iloc[10] - 1
        with self.assertRaisesRegex(ValueError, 'High < Low'):
            clean_history(frame, 'ASELS.IS')

    def test_nonpositive_or_inconsistent_prices_rejected(self):
        for column, value in (('Low', -1), ('Open', 0), ('Close', 9999)):
            frame = self.frame()
            frame.loc[frame.index[10], column] = value
            with self.assertRaises(ValueError):
                clean_history(frame, 'ASELS.IS')

    def test_duplicate_dates_keep_first_source_row_deterministically(self):
        frame = self.frame()
        duplicate = frame.iloc[[10]].copy()
        duplicate.Volume += 5
        source = pd.concat([frame, duplicate])
        first = clean_history(source, 'ASELS.IS')
        second = clean_history(source, 'ASELS.IS')
        pd.testing.assert_frame_equal(first, frame)
        pd.testing.assert_frame_equal(first, second)
        row = first.attrs['validation']['removed_rows'][0]
        self.assertEqual((row['source_row'], row['category'], row['values']['Volume']), (100, 'duplicate', 1005))

    def test_chronological_sorting_is_stable_and_reported(self):
        source = self.frame().iloc[::-1]
        cleaned = clean_history(source, 'ASELS.IS')
        pd.testing.assert_frame_equal(cleaned, self.frame())
        self.assertEqual(cleaned.attrs['validation']['rows_removed'], 0)
        self.assertIn('sorted chronologically', cleaned.attrs['validation']['warnings'][0])

    def test_completely_unusable_dataset_fails(self):
        source = historical_frame(3)
        source[:] = np.nan
        with self.assertRaisesRegex(ValueError, 'completely unusable dataset'):
            clean_history(source, 'ASELS.IS')

    def test_excessive_missing_rows_fail(self):
        source = self.frame()
        source.iloc[:6, source.columns.get_loc('Volume')] = np.nan
        with self.assertRaisesRegex(ValueError, '6/100 removed; maximum 5%'):
            clean_history(source, 'ASELS.IS')

    def test_valid_dataset_values_remain_unchanged(self):
        source = self.frame()
        original = source.copy(deep=True)
        cleaned = clean_history(source, 'ASELS.IS')
        pd.testing.assert_frame_equal(cleaned, original)
        pd.testing.assert_frame_equal(source, original)
        self.assertEqual(cleaned.attrs['validation']['removed_rows'], [])

    def test_explicit_numeric_conversion_and_bad_tokens(self):
        source = self.frame().astype(str)
        cleaned = clean_history(source, 'ASELS.IS')
        pd.testing.assert_frame_equal(cleaned, self.frame())
        source.loc[source.index[10], 'Close'] = 'broken'
        with self.assertRaisesRegex(ValueError, 'nonnumeric Close'):
            clean_history(source, 'ASELS.IS')

    def test_boolean_values_and_invalid_dates_fail(self):
        source = self.frame().astype(object)
        source.iloc[10, 0] = True
        with self.assertRaisesRegex(ValueError, 'boolean Open'):
            clean_history(source, 'ASELS.IS')
        source = self.frame().reset_index(drop=True)
        with self.assertRaisesRegex(ValueError, 'invalid historical dates'):
            clean_history(source, 'ASELS.IS')

    def test_quality_failure_in_requested_range_not_diluted_by_warmup(self):
        source = self.frame()
        source.loc[source.index[90], 'Volume'] = np.nan
        cleaned = clean_history(source, 'ASELS.IS')  # 1% of downloaded history
        with self.assertRaisesRegex(ValueError, 'requested period.*1/10'):
            run_backtest({'ASELS.IS': cleaned}, str(source.index[90].date()), str(source.index[-1].date()))


class ProviderIntegrationTests(OfflineTestCase):
    def test_csv_invalid_date_is_not_silently_filtered_out(self):
        frame = historical_frame(100)
        frame = frame.reset_index(names='Date')
        frame['Date'] = frame.Date.astype(str)
        frame.loc[10, 'Date'] = 'invalid-date'
        frame.to_csv('ASELS.IS.csv', index=False)
        with self.assertRaisesRegex(ValueError, 'invalid historical CSV dates'):
            CSVProvider('.').fetch('ASELS.IS', '2022-01-01', '2022-12-31')

    def test_yahoo_null_row_is_cleaned_with_source_evidence(self):
        frame = historical_frame(100)
        quote = {c.lower(): frame[c].tolist() for c in frame.columns}
        for values in quote.values():
            values[10] = None
        payload = {'chart': {'error': None, 'result': [{
            'timestamp': [int(date.tz_localize('Europe/Istanbul').timestamp()) for date in frame.index],
            'indicators': {'quote': [quote]},
        }]}}
        original = deepcopy(payload)
        session = Mock()
        session.get.return_value = response(payload)
        cleaned = YahooProvider(session).fetch('ASELS', str(frame.index[0].date()), str(frame.index[-1].date()))
        self.assertEqual(len(cleaned), 99)
        self.assertEqual(cleaned.attrs['validation']['removed_rows'][0]['values'], dict.fromkeys(frame.columns))
        self.assertEqual(payload, original)

    def test_csv_provider_sorts_and_reports_missing_volume(self):
        frame = historical_frame(100)
        frame.iloc[10, frame.columns.get_loc('Volume')] = np.nan
        frame.iloc[::-1].to_csv('ASELS.IS.csv', index_label='Date')
        cleaned = CSVProvider('.').fetch('ASELS', str(frame.index[0].date()), str(frame.index[-1].date()))
        self.assertEqual(len(cleaned), 99)
        self.assertTrue(cleaned.index.is_monotonic_increasing)
        self.assertEqual(cleaned.attrs['validation']['rows_removed'], 1)


class MissingSessionTests(OfflineTestCase):
    def replay(self, missing_index, column='Volume', trade=True):
        source = historical_frame(100)
        source.loc[source.index[missing_index], column] = np.nan
        cleaned = clean_history(source, 'ASELS.IS')
        def generator(ticker, history):
            if trade and history.index[-1] == source.index[60]:
                return test_signal(ticker, str(source.index[60].date()), price=float(history.Close.iloc[-1]))
        return run_backtest({'ASELS.IS': cleaned}, str(source.index[60].date()),
                            str(source.index[80].date()), signal_generator=generator)

    def test_removed_next_candle_does_not_defer_entry(self):
        result = self.replay(61)
        self.assertEqual(result.trades, [])
        self.assertTrue(any('order not deferred' in warning for warning in result.warnings))

    def test_open_position_across_removed_candle_fails(self):
        with self.assertRaisesRegex(ValueError, 'cannot simulate an open position across removed candle'):
            self.replay(62)

    def test_missing_final_session_cannot_force_earlier_exit(self):
        with self.assertRaisesRegex(ValueError, 'cannot simulate an open position across removed candle'):
            self.replay(80)

    def test_final_usable_candle_entry_cannot_be_liquidated_before_removed_session(self):
        source = historical_frame(100)
        source.loc[source.index[80], 'Volume'] = np.nan
        cleaned = clean_history(source, 'ASELS.IS')
        def generator(ticker, history):
            if history.index[-1] == source.index[78]:
                return test_signal(ticker, str(history.index[-1].date()), price=float(history.Close.iloc[-1]))
        with self.assertRaisesRegex(ValueError, 'cannot simulate an open position across removed candle'):
            run_backtest({'ASELS.IS': cleaned}, str(source.index[60].date()),
                         str(source.index[80].date()), signal_generator=generator)

    def test_actual_exit_before_future_missing_candle_is_allowed(self):
        source = historical_frame(100)
        source.loc[source.index[80], 'Volume'] = np.nan
        source.loc[source.index[61:80], ['Open', 'High', 'Low', 'Close']] = [107, 108, 106, 107]
        source.loc[source.index[79], 'Low'] = 50
        cleaned = clean_history(source, 'ASELS.IS')
        def generator(ticker, history):
            if history.index[-1] == source.index[60]:
                return test_signal(ticker, str(history.index[-1].date()), price=float(history.Close.iloc[-1]))
        result = run_backtest({'ASELS.IS': cleaned}, str(source.index[60].date()),
                              str(source.index[80].date()), signal_generator=generator)
        self.assertEqual(result.trades[0]['exit_reason'], 'STOP')
        self.assertEqual(result.trades[0]['exit_date'], str(source.index[79].date()))

    def test_missing_warmup_candle_does_not_block_valid_trades(self):
        result = self.replay(10)
        self.assertEqual(len(result.trades), 1)
        self.assertEqual(result.data_validation[0]['requested_rows_removed'], 0)

    def test_validation_counts_and_warnings_exported(self):
        result = self.replay(70, trade=False)
        output = save_report(result, run_id='validation', charts=False)
        summary = (output / 'summary.md').read_text('utf-8')
        self.assertIn('Historical data validation', summary)
        self.assertIn('Rows downloaded', summary)
        self.assertIn('missing Volume', summary)
        audit = json.loads((output / 'data_validation.json').read_text('utf-8'))[0]
        self.assertEqual((audit['rows_downloaded'], audit['rows_removed'], audit['usable_rows']), (100, 1, 99))
        self.assertEqual((audit['requested_rows_downloaded'], audit['requested_rows_removed'], audit['requested_usable_rows']),
                         (21, 1, 20))
        full = json.loads((output / 'results.json').read_text('utf-8'))
        self.assertEqual(full['data_validation'][0], audit)
