"""Offline annual resets, descriptive stability, cost comparisons and reports."""
from contextlib import redirect_stdout, redirect_stderr
from io import StringIO
import importlib.util
import json
from pathlib import Path
from unittest.mock import Mock

import pandas as pd

from backtest.multi_year import run_multi_year, chained_capital_view
from backtest.multi_year_cli import main, parser
from backtest.multi_year_report import save_multi_year_report
from tests.helpers import OfflineTestCase
from tests.test_backtest_execution import replay_frame
from tests.test_backtest_validation import first_signal


def annual_frame(year, losing=False):
    frame = replay_frame().astype(float)
    frame.index = frame.index + pd.DateOffset(years=year - 2023)
    if losing:
        frame.iloc[-1] = [110, 115, 104, 105, 1000]
    return frame


def fixture_multi_year(symbols=('A.IS', 'B.IS'), generator=first_signal, frames=None, include_chained=True):
    frames = frames if frames is not None else {year: {ticker: annual_frame(year) for ticker in symbols}
                                               for year in (2023, 2024, 2025)}
    return run_multi_year(frames_by_year=frames, tickers=symbols, signal_generator=generator,
                          include_chained_view=include_chained)


class MultiYearCapitalTests(OfflineTestCase):
    def test_each_year_resets_full_capital_and_risk_model(self):
        result = fixture_multi_year(symbols=('A.IS',))
        for year, annual in result.annual.items():
            for scenario, data in annual.scenarios.items():
                replay = data['aggregate']
                self.assertEqual(replay.config.initial_capital, 100000)
                self.assertEqual(replay.config.risk_per_trade, .01)
                self.assertEqual(replay.config.max_positions, 5)
                self.assertEqual(replay.config.execution_model, 'next_open')
                self.assertEqual(replay.config.intrabar_policy, 'stop_first')
                self.assertEqual(replay.equity.cash.iloc[0], 100000)
        endings = [r['ending_capital_tl'] for r in result.comparison if r['scenario'] == 'baseline']
        self.assertEqual(endings, [100330] * 3)
        self.assertEqual(result.stability['baseline']['cumulative_net_pnl_tl'], 990)
        self.assertEqual(result.stability['baseline']['total_capital_allocated_tl'], 300000)
        self.assertAlmostEqual(result.stability['baseline']['return_on_total_allocated_capital_pct'], .33)

    def test_combined_comparison_has_all_years_and_both_scenarios(self):
        result = fixture_multi_year()
        self.assertEqual(len(result.comparison), 6)
        self.assertEqual([(r['year'], r['scenario']) for r in result.comparison],
                         [(year, scenario) for scenario in ('realism', 'baseline') for year in (2023, 2024, 2025)])
        for row in result.comparison:
            self.assertEqual(row['status'], 'complete')
            self.assertEqual((row['valid_signals'], row['executed_trades'], row['skipped_signals']), (2, 2, 0))

    def test_secondary_chain_links_returns_without_changing_annual_replays(self):
        result = fixture_multi_year(symbols=('A.IS',))
        baseline = [r for r in result.chained_view if r['scenario'] == 'baseline']
        self.assertEqual(baseline[0]['illustrated_start_tl'], 100000)
        self.assertEqual(baseline[1]['illustrated_start_tl'], baseline[0]['illustrated_end_tl'])
        self.assertAlmostEqual(baseline[-1]['illustrated_end_tl'], 100000 * 1.0033 ** 3)
        self.assertTrue(all(r['method'] == 'return_linked_illustration_no_replay' for r in baseline))
        self.assertTrue(all(y.scenarios['baseline']['aggregate'].config.initial_capital == 100000
                            for y in result.annual.values()))

    def test_optional_chain_disabled_does_not_change_primary_results(self):
        enabled = fixture_multi_year()
        disabled = fixture_multi_year(include_chained=False)
        self.assertEqual(disabled.chained_view, [])
        self.assertEqual(enabled.comparison, disabled.comparison)
        self.assertEqual(enabled.per_ticker, disabled.per_ticker)

    def test_provider_fetches_separate_year_windows_once_per_ticker(self):
        provider = Mock()
        provider.fetch.side_effect = lambda ticker, start, end: annual_frame(int(end[:4]))
        result = run_multi_year(provider=provider, tickers=('A.IS',), signal_generator=first_signal)
        self.assertEqual(provider.fetch.call_count, 3)
        self.assertEqual([call.args[1:] for call in provider.fetch.call_args_list],
                         [('2021-01-01', '2023-12-31'), ('2022-01-01', '2024-12-31'), ('2023-01-02', '2025-12-31')])
        self.assertEqual(result.years, [2023, 2024, 2025])

    def test_later_year_input_cannot_change_earlier_year_signals(self):
        original = {year: {'A.IS': annual_frame(year), 'B.IS': annual_frame(year)} for year in (2023, 2024, 2025)}
        first = fixture_multi_year(frames=original)
        changed = {year: {ticker: frame.copy() for ticker, frame in values.items()} for year, values in original.items()}
        changed[2025]['A.IS'][['Open', 'High', 'Low', 'Close']] *= 2
        second = fixture_multi_year(frames=changed)
        self.assertEqual(first.annual[2023].scenarios['realism']['aggregate'].signals,
                         second.annual[2023].scenarios['realism']['aggregate'].signals)
        self.assertEqual(first.annual[2023].scenarios['realism']['aggregate'].trades,
                         second.annual[2023].scenarios['realism']['aggregate'].trades)


class MultiYearDescriptiveTests(OfflineTestCase):
    def test_multi_year_ticker_aggregation_and_zero_years(self):
        generator = lambda ticker, history: None if ticker == 'B.IS' else first_signal(ticker, history)
        result = fixture_multi_year(generator=generator)
        rows = [r for r in result.per_ticker if r['scenario'] == 'baseline' and r['portfolio_mode'] == 'shared']
        a, b = rows
        self.assertEqual((a['total_trades'], a['cumulative_net_pnl_tl'], a['profitable_years'], a['losing_years']), (3, 990, 3, 0))
        self.assertEqual([a[f'{year}_trades'] for year in result.years], [1, 1, 1])
        self.assertEqual((b['total_trades'], b['cumulative_net_pnl_tl'], b['zero_trade_years']), (0, 0, '2023,2024,2025'))
        self.assertEqual(len(result.per_ticker), 8)  # Two scenarios, two modes, two tickers.

    def test_profitable_losing_year_counts_best_worst_and_variability(self):
        frames = {year: {'A.IS': annual_frame(year, losing=year == 2024)} for year in (2023, 2024, 2025)}
        result = fixture_multi_year(symbols=('A.IS',), frames=frames)
        summary = result.stability['baseline']
        self.assertEqual((summary['profitable_years'], summary['losing_years'], summary['flat_years']), (2, 1, 0))
        self.assertEqual((summary['best_year'], summary['worst_year']), (2023, 2024))
        self.assertAlmostEqual(summary['average_yearly_return_pct'], .11)
        self.assertAlmostEqual(summary['median_yearly_return_pct'], .33)
        self.assertAlmostEqual(summary['yearly_return_sample_std_pp'], .66 / (3 ** .5))
        self.assertAlmostEqual(summary['yearly_return_range_pp'], .66)
        self.assertEqual(summary['total_closed_trades'], 3)
        self.assertEqual(summary['pooled_profit_factor'], 2)

    def test_concentration_reconciles_and_reports_largest_contributors(self):
        frames = {year: {'A.IS': annual_frame(year), 'B.IS': annual_frame(year, losing=True)}
                  for year in (2023, 2024, 2025)}
        result = fixture_multi_year(frames=frames)
        summary = result.stability['baseline']
        self.assertEqual(summary['strongest_positive_ticker']['ticker'], 'A.IS')
        self.assertEqual(summary['weakest_negative_ticker']['ticker'], 'B.IS')
        self.assertAlmostEqual(sum(r['net_pnl_tl'] for r in summary['per_ticker_concentration']), summary['cumulative_net_pnl_tl'])
        self.assertTrue(all(r['pnl_share_pct'] is None for r in summary['per_ticker_concentration']))
        self.assertEqual(set(summary['largest_ticker_contribution_per_year']), {'2023', '2024', '2025'})

    def test_warnings_for_single_profitable_year_zero_trades_and_concentration(self):
        def generator(ticker, history):
            return first_signal(ticker, history) if history.index[-1].year == 2023 else None
        result = fixture_multi_year(symbols=('A.IS',), generator=generator)
        text = '\n'.join(result.warnings)
        for phrase in ('fewer than 30', 'only one observed year', 'exceeds 50%', '2024 has zero',
                       'fewer than 3 observed total trades', 'profit factor undefined', 'not statistically significant'):
            self.assertIn(phrase, text)
        self.assertEqual(result.stability['baseline']['profitable_years'], 1)

    def test_failed_ticker_year_is_na_and_not_silently_zero(self):
        frames = {year: {'A.IS': annual_frame(year), 'B.IS': annual_frame(year)} for year in (2023, 2024, 2025)}
        frames[2024].pop('B.IS')
        result = fixture_multi_year(frames=frames)
        row = next(r for r in result.per_ticker if r['ticker'] == 'B.IS' and r['scenario'] == 'realism' and r['portfolio_mode'] == 'shared')
        self.assertIsNone(row['2024_trades'])
        self.assertIsNone(row['2024_net_pnl_tl'])
        self.assertIsNone(row['total_trades'])
        self.assertEqual(row['observed_trades'], 2)
        self.assertFalse(row['coverage_complete'])
        self.assertIsNone(result.stability['realism']['cumulative_net_pnl_tl'])
        chain = [r for r in result.chained_view if r['scenario'] == 'realism']
        self.assertIsNone(chain[1]['illustrated_end_tl'])
        self.assertIsNone(chain[2]['illustrated_start_tl'])
        self.assertTrue(any('incomplete year/basket coverage' in warning for warning in result.warnings))

    def test_all_failed_years_keep_requested_rows_and_undefined_metrics(self):
        result = fixture_multi_year(frames={2023: {}, 2024: {}, 2025: {}})
        self.assertTrue(all(r['status'] == 'aggregate_failed' for r in result.comparison))
        self.assertIsNone(result.stability['realism']['average_yearly_return_pct'])
        self.assertEqual(len(result.per_ticker), 8)
        self.assertTrue(all(r['observed_net_pnl_tl'] is None for r in result.per_ticker))


class MultiYearCostTests(OfflineTestCase):
    def test_cost_drag_ending_return_and_gross_profit_denominator(self):
        result = fixture_multi_year(symbols=('A.IS',))
        for year in result.years:
            row = next(r for r in result.cost_drag if r['year'] == year)
            baseline = result.annual[year].scenarios['baseline']['aggregate']
            realism = result.annual[year].scenarios['realism']['aggregate']
            expected = baseline.metrics['ending_capital_tl'] - realism.metrics['ending_capital_tl']
            self.assertAlmostEqual(row['ending_capital_difference_tl'], expected)
            self.assertAlmostEqual(row['total_return_difference_pp'], expected / 100000 * 100)
            self.assertEqual(row['baseline_gross_profit_tl'], 330)
            self.assertAlmostEqual(row['cost_drag_pct_of_gross_profit'], expected / 330 * 100)
            self.assertLess(row['realism_commissions_paid_tl'], row['ending_capital_difference_tl'])
        combined = result.cost_drag[-1]
        self.assertEqual(combined['baseline_gross_profit_tl'], 990)
        self.assertAlmostEqual(combined['ending_capital_difference_tl'], sum(r['ending_capital_difference_tl'] for r in result.cost_drag[:-1]))
        self.assertAlmostEqual(combined['allocated_capital_return_difference_pp'],
                               combined['ending_capital_difference_tl'] / 300000 * 100)
        self.assertAlmostEqual(combined['allocated_capital_return_difference_pp'],
                               combined['total_return_difference_pp'] / 3)

    def test_zero_gross_profit_cost_ratio_is_undefined(self):
        result = fixture_multi_year(generator=lambda ticker, history: None)
        self.assertTrue(all(r['cost_drag_pct_of_gross_profit'] is None for r in result.cost_drag))
        self.assertEqual(result.cost_drag[-1]['ending_capital_difference_tl'], 0)

    def test_loss_only_baseline_does_not_use_net_loss_as_gross_profit(self):
        frames = {year: {'A.IS': annual_frame(year, losing=True)} for year in (2023, 2024, 2025)}
        result = fixture_multi_year(symbols=('A.IS',), frames=frames)
        self.assertEqual(result.cost_drag[-1]['baseline_gross_profit_tl'], 0)
        self.assertIsNone(result.cost_drag[-1]['cost_drag_pct_of_gross_profit'])
        self.assertGreater(result.cost_drag[-1]['ending_capital_difference_tl'], 0)


class MultiYearReportTests(OfflineTestCase):
    def test_annual_and_combined_outputs_and_data_quality_rows(self):
        result = fixture_multi_year()
        output = save_multi_year_report(result, run_id='multi_year', charts=False)
        for name in ('summary.md', 'year_comparison.csv', 'per_ticker_multi_year.csv', 'combined_trades.csv',
                     'independent_combined_trades.csv', 'equity_curves.csv', 'data_quality.csv', 'cost_drag.csv',
                     'chained_capital.csv', 'multi_year.json'):
            self.assertTrue((output / name).is_file())
        for year in result.years:
            summary = (output / 'years' / str(year) / 'summary.md').read_text('utf-8')
            self.assertIn('Primary scenario: **realism**', summary)
            self.assertIn('Skipped signals (all reasons)', summary)
        self.assertEqual(len(pd.read_csv(output / 'year_comparison.csv')), 6)
        self.assertEqual(len(pd.read_csv(output / 'data_quality.csv')), 6)
        self.assertEqual(len(pd.read_csv(output / 'combined_trades.csv')), 12)
        payload = json.loads((output / 'multi_year.json').read_text('utf-8'))
        self.assertEqual(payload['primary_scenario'], 'realism')
        summary = (output / 'summary.md').read_text('utf-8')
        for phrase in ('independently with 100,000', 'sample standard deviation', 'visualization',
                       'not net P&L', 'Look-ahead bias audit', 'not statistically significant'):
            self.assertIn(phrase, summary)

    def test_optional_chain_omitted_from_outputs(self):
        output = save_multi_year_report(fixture_multi_year(include_chained=False), run_id='no_chain', charts=False)
        self.assertFalse((output / 'chained_capital.csv').exists())
        self.assertNotIn('Secondary chained-capital illustration', (output / 'summary.md').read_text('utf-8'))

    def test_optional_charts_render_without_network(self):
        if importlib.util.find_spec('matplotlib') is None:
            self.skipTest('Optional matplotlib is not installed')
        output = save_multi_year_report(fixture_multi_year(symbols=('A.IS',)), run_id='plots', charts=True)
        for name in ('yearly_returns.png', 'yearly_drawdown.png', 'per_ticker_cumulative_pnl.png', 'chained_capital.png'):
            self.assertEqual((output / name).read_bytes()[:8], b'\x89PNG\r\n\x1a\n')

    def test_report_run_directory_no_overwrite_or_traversal(self):
        result = fixture_multi_year()
        save_multi_year_report(result, run_id='same', charts=False)
        with self.assertRaises(FileExistsError):
            save_multi_year_report(result, run_id='same', charts=False)
        with self.assertRaises(ValueError):
            save_multi_year_report(result, run_id='../unsafe', charts=False)

    def test_cli_help_fixed_years_and_existing_settings(self):
        help_text = parser().format_help()
        self.assertIn('2023/2024/2025', help_text)
        self.assertIn('1% risk', help_text)
        self.assertIn('--no-chained-view', help_text)
        self.assertNotIn('--risk-per-trade', help_text)

    def test_missing_csv_cli_reports_every_failed_ticker_year(self):
        with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            status = main(['--csv-dir', '.', '--no-charts'])
        self.assertEqual(status, 1)
        path = next(Path('backtest_results').glob('*/multi_year.json'))
        payload = json.loads(path.read_text('utf-8'))
        self.assertEqual(len(payload['per_ticker']), 40)
        self.assertTrue(all(len(data['failures']) == 10 for data in payload['annual_metadata'].values()))

    def test_invalid_year_order_or_input_source_is_rejected(self):
        with self.assertRaises(ValueError):
            run_multi_year(frames_by_year={}, years=(2024, 2023))
        with self.assertRaises(ValueError):
            run_multi_year(provider=Mock(), frames_by_year={})
