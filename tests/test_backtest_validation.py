"""Offline fixed-basket orchestration, ranked allocation and factual reports."""
from contextlib import redirect_stdout, redirect_stderr
from dataclasses import replace
from io import StringIO
import importlib.util
import json
from pathlib import Path
from unittest.mock import Mock, patch

import pandas as pd

from backtest.data import clean_history
from backtest.engine import run_backtest
from backtest.execution import BacktestConfig
from backtest.validation import VALIDATION_BASKET, concentration_analysis, run_validation
from backtest.validation_cli import main, parser
from backtest.validation_report import save_validation_report
from tests.helpers import OfflineTestCase
from tests.test_backtest_execution import replay_frame
from tests.test_backtest_signals import historical_frame, test_signal


def first_signal(ticker, history):
    return test_signal(ticker, str(history.index[-1].date())) if len(history) == 1 else None


def fixture_validation(symbols=('A.IS', 'B.IS', 'C.IS'), config=None, generator=first_signal):
    frames = {ticker: replay_frame() for ticker in symbols}
    return run_validation(frames=frames, tickers=symbols, start='2023-01-02', end='2023-01-04',
                          config=config, signal_generator=generator)


class RankedReplayTests(OfflineTestCase):
    def test_strongest_five_enter_before_alphabetically_earlier_weaker_signals(self):
        frames = {f'{letter}.IS': replay_frame() for letter in 'ABCDEFG'}
        def generator(ticker, history):
            signal = first_signal(ticker, history)
            return replace(signal, confidence=9 if ticker == 'G.IS' else 8) if signal else None
        result = run_backtest(frames, '2023-01-02', '2023-01-04', BacktestConfig(max_positions=5), generator,
                              allocation_policy='score_confidence')
        fills = [d['ticker'] for d in result.entry_decisions if d['status'] == 'executed']
        self.assertEqual(fills, ['G.IS', 'A.IS', 'B.IS', 'C.IS', 'D.IS'])
        self.assertLessEqual(result.equity.open_positions.max(), 5)
        self.assertEqual(result.selectivity['skipped_by_reason']['concurrency'], 2)

    def test_technical_score_then_final_score_then_symbol_break_ties(self):
        frames = {ticker: replay_frame() for ticker in ['D.IS', 'C.IS', 'B.IS', 'A.IS']}
        technical = {'A.IS': 80, 'B.IS': 90, 'C.IS': 90, 'D.IS': 90}
        final = {'A.IS': 70, 'B.IS': 70, 'C.IS': 75, 'D.IS': 75}
        def generator(ticker, history):
            signal = first_signal(ticker, history)
            return replace(signal, technical_score=technical[ticker], final_score=final[ticker]) if signal else None
        result = run_backtest(frames, '2023-01-02', '2023-01-04', signal_generator=generator,
                              allocation_policy='score_confidence')
        self.assertEqual([d['ticker'] for d in result.entry_decisions if d['status'] == 'executed'],
                         ['C.IS', 'D.IS', 'B.IS', 'A.IS'])

    def test_normal_backtest_default_stays_alphabetical(self):
        frames = {'Z.IS': replay_frame(), 'A.IS': replay_frame()}
        def generator(ticker, history):
            signal = first_signal(ticker, history)
            return replace(signal, confidence=10 if ticker == 'Z.IS' else 7) if signal else None
        result = run_backtest(frames, '2023-01-02', '2023-01-04', BacktestConfig(max_positions=1), generator)
        self.assertEqual(result.trades[0]['ticker'], 'A.IS')
        self.assertEqual(result.allocation_policy, 'alphabetical')

    def test_ranking_uses_signal_candle_not_next_candle_high_or_volume(self):
        frames = {'A.IS': replay_frame(), 'B.IS': replay_frame()}
        frames['A.IS'].iloc[1, frames['A.IS'].columns.get_loc('Volume')] = 1000000
        def generator(ticker, history):
            signal = first_signal(ticker, history)
            return replace(signal, confidence=9 if ticker == 'B.IS' else 7) if signal else None
        result = run_backtest(frames, '2023-01-02', '2023-01-04', BacktestConfig(max_positions=1), generator,
                              allocation_policy='score_confidence')
        self.assertEqual(result.trades[0]['ticker'], 'B.IS')

    def test_reserved_cash_and_constraints_are_counted_without_leverage(self):
        result = fixture_validation(config=BacktestConfig(initial_capital=1000, risk_per_trade=1, max_positions=5))
        aggregate = result.scenarios['baseline']['aggregate']
        self.assertEqual(aggregate.selectivity['executed_entries'], 1)
        self.assertEqual(aggregate.selectivity['skipped_by_reason']['capital'], 2)
        self.assertEqual(aggregate.selectivity['skipped_capital_or_concurrency'], 2)
        self.assertTrue((aggregate.equity.cash >= -1e-8).all())

    def test_selectivity_decisions_reconcile_all_valid_signals(self):
        generator = lambda ticker, history: test_signal(ticker, str(history.index[-1].date()))
        aggregate = fixture_validation(symbols=('A.IS', 'B.IS'), generator=generator).scenarios['baseline']['aggregate']
        self.assertEqual(aggregate.selectivity['ticker_days_evaluated'], 6)
        self.assertEqual(aggregate.selectivity['valid_signals'], 6)
        self.assertEqual(len(aggregate.entry_decisions), 6)
        self.assertEqual(aggregate.selectivity['executed_entries'], 2)
        self.assertEqual(aggregate.selectivity['skipped_by_reason']['already_open'], 2)
        self.assertEqual(aggregate.selectivity['skipped_by_reason']['no_next_candle'], 2)

    def test_future_rows_of_one_ticker_cannot_change_another_past_signal(self):
        frame = historical_frame(260)
        frame.loc[frame.index[239], ['Open', 'High', 'Low', 'Close']] += 2
        frame.loc[frame.index[239], 'Volume'] = 100000
        start, cutoff, future_end = (str(frame.index[n].date()) for n in (220, 239, 259))
        before = run_backtest({'A.IS': frame.iloc[:240], 'B.IS': frame.iloc[:240]}, start, cutoff,
                              allocation_policy='score_confidence')
        after = run_backtest({'A.IS': frame, 'B.IS': frame.iloc[:240]}, start, future_end,
                             allocation_policy='score_confidence')
        past = [s for s in before.signals if s['ticker'] == 'B.IS']
        extended = [s for s in after.signals if s['ticker'] == 'B.IS' and s['signal_date'] <= cutoff]
        self.assertTrue(past)
        self.assertEqual(past, extended)


class ValidationTests(OfflineTestCase):
    def test_multi_ticker_independent_and_aggregate_pnl(self):
        result = fixture_validation()
        self.assertEqual(len(result.per_ticker), 6)
        baseline = result.scenarios['baseline']
        aggregate = baseline['aggregate']
        self.assertEqual(aggregate.metrics['total_trades'], 3)
        self.assertEqual(aggregate.config.initial_capital, 100000)
        self.assertEqual(aggregate.config.max_positions, 5)
        self.assertAlmostEqual(aggregate.metrics['net_pnl_tl'],
                               sum(r.metrics['net_pnl_tl'] for r in baseline['independent'].values()))
        self.assertAlmostEqual(sum(r['shared_net_pnl_tl'] for r in result.per_ticker if r['scenario'] == 'baseline'),
                               aggregate.metrics['net_pnl_tl'])

    def test_zero_trade_ticker_remains_in_both_scenarios(self):
        generator = lambda ticker, history: None if ticker == 'B.IS' else first_signal(ticker, history)
        result = fixture_validation(generator=generator)
        for scenario in result.scenarios:
            row = next(r for r in result.per_ticker if r['scenario'] == scenario and r['ticker'] == 'B.IS')
            self.assertEqual((row['status'], row['trade_count'], row['net_pnl_tl'], row['shared_trade_count']), ('ok', 0, 0, 0))
            self.assertTrue(any('B.IS: zero independent trades' in w for w in result.scenarios[scenario]['warnings']))

    def test_fetch_once_and_continue_after_explicit_failed_ticker(self):
        provider = Mock()
        def fetch(ticker, start, end):
            if ticker == 'B.IS':
                raise ValueError('B.IS: Yahoo data unavailable')
            return replay_frame()
        provider.fetch.side_effect = fetch
        result = run_validation(provider=provider, tickers=('A.IS', 'B.IS', 'C.IS'),
                                start='2023-01-02', end='2023-01-04', signal_generator=first_signal)
        self.assertEqual(provider.fetch.call_count, 3)
        self.assertIn('B.IS', result.failures)
        self.assertEqual(len(result.per_ticker), 6)
        for name, scenario in result.scenarios.items():
            self.assertEqual(scenario['aggregate'].tickers, ['A.IS', 'C.IS'])
            row = next(r for r in result.per_ticker if r['scenario'] == name and r['ticker'] == 'B.IS')
            self.assertEqual((row['status'], row['shared_status'], row['trade_count']), ('failed', 'excluded', None))
        self.assertTrue(any('Incomplete basket' in w for w in result.warnings))

    def test_invalid_row_threshold_failure_keeps_known_diagnostics(self):
        provider = Mock()
        def fetch(ticker, start, end):
            if ticker == 'B.IS':
                bad = historical_frame(100)
                bad.loc[bad.index[:6], 'Volume'] = float('nan')
                return clean_history(bad, ticker)
            return replay_frame()
        provider.fetch.side_effect = fetch
        result = run_validation(provider=provider, tickers=('A.IS', 'B.IS'),
                                start='2023-01-02', end='2023-01-04', signal_generator=first_signal)
        audit = result.data_validation['B.IS']
        self.assertEqual((audit['rows_downloaded'], audit['rows_removed'], audit['usable_rows']), (100, 6, 94))
        self.assertEqual(len(audit['removed_rows']), 6)

    def test_failed_requested_period_validation_is_reported(self):
        good = historical_frame(100)
        bad = good.copy()
        bad.loc[bad.index[90], 'Volume'] = float('nan')
        bad = clean_history(bad, 'B.IS')
        result = run_validation(frames={'A.IS': good, 'B.IS': bad}, tickers=('A.IS', 'B.IS'),
                                start=str(good.index[90].date()), end=str(good.index[-1].date()),
                                signal_generator=lambda ticker, history: None)
        self.assertIn('B.IS', result.failures)
        self.assertEqual(result.scenarios['baseline']['aggregate'].tickers, ['A.IS'])
        self.assertIn('requested period', result.failures['B.IS'][0]['error'])

    def test_all_tickers_failed_does_not_fabricate_aggregate(self):
        provider = Mock()
        provider.fetch.side_effect = ValueError('Unavailable data')
        result = run_validation(provider=provider, tickers=('A.IS', 'B.IS'))
        self.assertTrue(all(s['aggregate'] is None for s in result.scenarios.values()))
        self.assertEqual(len(result.per_ticker), 4)
        output = save_validation_report(result, run_id='all_failed', charts=False)
        self.assertTrue(pd.read_csv(output / 'trades.csv').empty)
        self.assertTrue(pd.read_csv(output / 'equity_curve.csv').empty)
        self.assertEqual(len(pd.read_csv(output / 'per_ticker.csv')), 4)

    def test_shared_failure_is_reported_without_retrospective_ticker_removal(self):
        original = run_backtest
        calls = []
        def replay(frames, *args, **kwargs):
            if len(frames) > 1:
                calls.append(sorted(frames))
                raise ValueError('Cannot simulate an unknown candle while holding')
            return original(frames, *args, **kwargs)
        with patch('backtest.validation.run_backtest', side_effect=replay):
            result = fixture_validation()
        self.assertEqual(calls, [['A.IS', 'B.IS', 'C.IS']] * 2)
        self.assertEqual(result.failures, {})
        self.assertTrue(all(s['aggregate'] is None for s in result.scenarios.values()))
        self.assertEqual(result.per_ticker[0]['shared_status'], 'aggregate_failed')

    def test_one_scenario_safety_failure_excludes_ticker_from_both_shared_runs(self):
        original = run_backtest
        def replay(frames, start, end, config, *args, **kwargs):
            if list(frames) == ['B.IS'] and config.commission_pct > 0:
                raise ValueError('B.IS: cannot safely simulate a removed candle while holding')
            return original(frames, start, end, config, *args, **kwargs)
        with patch('backtest.validation.run_backtest', side_effect=replay):
            result = fixture_validation(symbols=('A.IS', 'B.IS'))
        self.assertTrue(all(s['aggregate'].tickers == ['A.IS'] for s in result.scenarios.values()))
        baseline_b = next(r for r in result.per_ticker if r['scenario'] == 'baseline' and r['ticker'] == 'B.IS')
        self.assertEqual((baseline_b['status'], baseline_b['shared_status']), ('ok', 'excluded'))
        self.assertIn('realism_independent_replay', baseline_b['failure'])

    def test_concentration_warning_identifies_dominant_ticker(self):
        generator = lambda ticker, history: first_signal(ticker, history) if ticker == 'A.IS' else None
        result = fixture_validation(generator=generator)
        self.assertTrue(any('exceed 50%' in w and 'A.IS' in w for w in result.scenarios['baseline']['warnings']))

    def test_cost_scenario_charges_both_sides_and_exposes_fills(self):
        result = fixture_validation(symbols=('A.IS',))
        baseline = result.scenarios['baseline']['aggregate'].trades[0]
        realism = result.scenarios['realism']['aggregate'].trades[0]
        self.assertEqual(baseline['entry_price'], 110)
        self.assertAlmostEqual(realism['entry_price'], 110 * 1.001)
        self.assertAlmostEqual(realism['exit_price'], 115 * .999)
        self.assertAlmostEqual(realism['entry_commission_tl'], realism['entry_price'] * realism['quantity'] * .001)
        self.assertAlmostEqual(realism['exit_commission_tl'], realism['exit_price'] * realism['quantity'] * .001)
        self.assertLess(realism['net_pnl_tl'], baseline['net_pnl_tl'])

    def test_realism_costs_are_configurable_and_baseline_remains_zero(self):
        result = run_validation(frames={'A.IS': replay_frame()}, tickers=('A.IS',),
                                start='2023-01-02', end='2023-01-04', realism_commission_pct=.2,
                                realism_slippage_pct=.3, signal_generator=first_signal)
        self.assertEqual(result.scenarios['baseline']['config'].commission_pct, 0)
        self.assertEqual(result.scenarios['realism']['config'].commission_pct, .2)
        self.assertEqual(result.scenarios['realism']['config'].slippage_pct, .3)

    def test_small_sample_warnings_do_not_alter_result(self):
        result = fixture_validation()
        scenario = result.scenarios['baseline']
        warnings = '\n'.join(scenario['warnings'])
        for text in ('fewer than 30', 'fewer than 3', 'no losing', 'profit factor is undefined', 'Sharpe', 'CAGR'):
            self.assertIn(text, warnings)
        self.assertEqual(scenario['aggregate'].metrics['total_trades'], 3)

    def test_validation_rejects_assumption_changes_and_invalid_inputs(self):
        for config in (BacktestConfig(execution_model='signal_close'), BacktestConfig(intrabar_policy='target_first')):
            with self.assertRaisesRegex(ValueError, 'preserves next_open and stop_first'):
                fixture_validation(config=config)
        with self.assertRaises(ValueError):
            run_validation(frames={}, provider=Mock())
        with self.assertRaises(ValueError):
            run_validation(frames={}, tickers=('A.IS', 'A.IS'))


class ConcentrationTests(OfflineTestCase):
    def test_percentage_contributions_and_strongest_weakest(self):
        result = fixture_validation()
        aggregate = result.scenarios['baseline']['aggregate']
        pnl = {'A.IS': 500, 'B.IS': -100, 'C.IS': 100}
        for trade in aggregate.trades:
            trade['net_pnl_tl'] = pnl[trade['ticker']]
        aggregate.metrics['net_pnl_tl'] = 500
        summary = concentration_analysis(aggregate)
        self.assertEqual(summary['largest_positive_contributor']['ticker'], 'A.IS')
        self.assertEqual(summary['largest_negative_contributor']['ticker'], 'B.IS')
        self.assertTrue(summary['one_ticker_above_50_pct_net_pnl'])
        self.assertEqual([r['pnl_share_pct'] for r in summary['per_ticker']], [100, -20, 20])
        self.assertAlmostEqual(sum(r['trade_share_pct'] for r in summary['per_ticker']), 100)

    def test_zero_total_pnl_percentage_is_undefined(self):
        aggregate = fixture_validation(symbols=('A.IS', 'B.IS')).scenarios['baseline']['aggregate']
        aggregate.trades[0]['net_pnl_tl'] = 100
        aggregate.trades[1]['net_pnl_tl'] = -100
        aggregate.metrics['net_pnl_tl'] = 0
        summary = concentration_analysis(aggregate)
        self.assertTrue(all(r['pnl_share_pct'] is None for r in summary['per_ticker']))
        self.assertFalse(summary['one_ticker_above_50_pct_net_pnl'])

    def test_stale_open_position_contribution_includes_entry_costs(self):
        generator = lambda ticker, history: None if ticker == 'B.IS' else first_signal(ticker, history)
        frames = {'A.IS': replay_frame().iloc[:2], 'B.IS': replay_frame()}
        aggregate = run_backtest(frames, '2023-01-02', '2023-01-04',
                                 BacktestConfig(commission_pct=.1, slippage_pct=.1), generator,
                                 allocation_policy='score_confidence')
        summary = concentration_analysis(aggregate)
        self.assertEqual(aggregate.metrics['total_trades'], 0)
        self.assertEqual(summary['total_executed_trades'], 1)
        self.assertAlmostEqual(summary['total_net_pnl_tl'], aggregate.metrics['net_pnl_tl'])
        self.assertEqual(summary['largest_negative_contributor']['ticker'], 'A.IS')


class ValidationReportTests(OfflineTestCase):
    def test_required_outputs_and_one_row_per_ticker_per_scenario(self):
        result = fixture_validation()
        output = save_validation_report(result, run_id='validation', charts=False)
        for filename in ('summary.md', 'per_ticker.csv', 'trades.csv', 'equity_curve.csv', 'drawdown.csv',
                         'validation.json', 'entry_decisions.csv', 'independent_trades.csv', 'data_validation.json'):
            self.assertTrue((output / filename).is_file())
        self.assertEqual(len(pd.read_csv(output / 'per_ticker.csv')), 6)
        self.assertEqual(set(pd.read_csv(output / 'trades.csv').scenario), {'baseline', 'realism'})
        payload = json.loads((output / 'validation.json').read_text('utf-8'))
        self.assertEqual(len(payload['input_data_sha256']), 3)
        self.assertEqual(payload['ranking_rule'].split(',')[0], 'Descending signal confidence')
        summary = (output / 'summary.md').read_text('utf-8')
        for phrase in ('independent', 'Shared aggregate', '0.001', 'Signal selectivity', 'confidence',
                       'Look-ahead bias audit', 'No claim of statistical significance'):
            self.assertIn(phrase, summary)

    def test_no_overwrite_and_no_directory_traversal(self):
        result = fixture_validation()
        save_validation_report(result, run_id='same', charts=False)
        with self.assertRaises(FileExistsError):
            save_validation_report(result, run_id='same', charts=False)
        with self.assertRaises(ValueError):
            save_validation_report(result, run_id='../unsafe', charts=False)

    def test_optional_plots_render_without_network(self):
        if importlib.util.find_spec('matplotlib') is None:
            self.skipTest('Optional matplotlib is not installed')
        output = save_validation_report(fixture_validation(), run_id='charts', charts=True)
        for name in ('aggregate_equity.png', 'drawdown.png', 'per_ticker_net_pnl.png', 'per_ticker_trade_count.png'):
            self.assertEqual((output / name).read_bytes()[:8], b'\x89PNG\r\n\x1a\n')

    def test_missing_plot_dependency_is_reported(self):
        with patch.dict('sys.modules', {'matplotlib': None}):
            output = save_validation_report(fixture_validation(), run_id='no_matplotlib', charts=True)
        self.assertIn('Charts skipped', (output / 'summary.md').read_text('utf-8'))

    def test_cli_fixed_basket_defaults_and_help(self):
        args = parser().parse_args([])
        self.assertEqual(str(args.start), '2025-01-01')
        self.assertEqual(args.max_concurrent_positions, 5)
        self.assertEqual((args.realism_commission_pct, args.realism_slippage_pct), (.1, .1))
        self.assertIn('TCELL.IS', parser().format_help())
        self.assertEqual(len(VALIDATION_BASKET), 10)

    def test_offline_fixed_basket_cli_end_to_end(self):
        frame = historical_frame(90)
        frame.loc[frame.index[60], ['Open', 'High', 'Low', 'Close']] += 2
        frame.loc[frame.index[60], 'Volume'] = 100000
        for ticker in VALIDATION_BASKET:
            frame.to_csv(f'{ticker}.csv', index_label='Date')
        with redirect_stdout(StringIO()) as output:
            status = main(['--csv-dir', '.', '--start', str(frame.index[59].date()),
                           '--end', str(frame.index[-1].date()), '--no-charts'])
        self.assertEqual(status, 0)
        self.assertIn('baseline:', output.getvalue())
        self.assertIn('realism:', output.getvalue())
        paths = list(Path('backtest_results').glob('*/validation.json'))
        payload = json.loads(paths[0].read_text('utf-8'))
        self.assertEqual(len(payload['per_ticker']), 20)
        self.assertEqual(payload['failures'], {})
        self.assertGreater(payload['scenarios']['baseline']['aggregate']['metrics']['total_trades'], 0)

    def test_all_missing_csv_cli_saves_failures_and_returns_error(self):
        with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            status = main(['--csv-dir', '.', '--no-charts'])
        self.assertEqual(status, 1)
        path = next(Path('backtest_results').glob('*/validation.json'))
        self.assertEqual(len(json.loads(path.read_text('utf-8'))['failures']), 10)
