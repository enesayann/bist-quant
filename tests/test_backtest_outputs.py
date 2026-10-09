"""Validated data boundaries, metrics, CLI and artifact contracts (offline)."""
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
import importlib.util
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np
import pandas as pd

from backtest.cli import main, parser
from backtest.data import CSVProvider, YahooProvider, normalize_ticker, validate_frame
from backtest.engine import run_backtest
from backtest.execution import BacktestConfig
from backtest.metrics import calculate_metrics
from backtest.report import plot_curves, save_report
from tests.helpers import OfflineTestCase, response
from tests.test_backtest_execution import replay_frame
from tests.test_backtest_signals import historical_frame, test_signal


def metric_trades():
    return [{'ticker': 'A.IS', 'exit_date': f'2023-01-0{i + 2}', 'net_pnl_tl': pnl,
             'net_return_pct': pnl / 10, 'holding_days': i + 1}
            for i, pnl in enumerate([100, -50, -25, 0, 200])]


class DataTests(OfflineTestCase):
    def test_valid_frame_and_missing_open_retained(self):
        df = replay_frame()
        df.loc[df.index[1], 'Open'] = np.nan
        result = validate_frame(df)
        self.assertEqual(len(result), 3)
        self.assertTrue(pd.isna(result.Open.iloc[1]))

    def test_duplicate_unsorted_dates_rejected(self):
        for df in (replay_frame().iloc[::-1], pd.concat([replay_frame(), replay_frame()])):
            with self.assertRaises(ValueError):
                validate_frame(df)

    def test_bad_prices_volume_and_missing_data(self):
        for column, value in [('Open', 0), ('Open', np.inf), ('High', 10),
                              ('Close', np.nan), ('Low', -1), ('Volume', -1),
                              ('Close', np.inf)]:
            df = replay_frame().astype(float)
            df.loc[df.index[0], column] = value
            with self.assertRaises(ValueError):
                validate_frame(df)
        df = replay_frame().astype(object)
        df.iloc[0, 0] = True
        with self.assertRaises(ValueError):
            validate_frame(df)

    def test_schema_and_index_validation(self):
        for df in (replay_frame().drop(columns='Open'), replay_frame().reset_index(), replay_frame().iloc[:0]):
            with self.assertRaises(ValueError):
                validate_frame(df)

    def test_csv_provider_date_filtering(self):
        replay_frame().to_csv('ASELS.IS.csv', index_label='Date')
        result = CSVProvider('.').fetch('ASELS', '2023-01-03', '2023-01-04')
        self.assertEqual(list(result.index), list(replay_frame().index[1:]))

    def test_ticker_normalization_and_path_safety(self):
        self.assertEqual(normalize_ticker(' asels '), 'ASELS.IS')
        for ticker in ('../secret', 'A/B', 'ASELS.IS?x=y', ''):
            with self.assertRaises(ValueError):
                normalize_ticker(ticker)

    def payload(self):
        frame = replay_frame()
        return {'chart': {'error': None, 'result': [{
            'timestamp': [int(t.tz_localize('Europe/Istanbul').timestamp()) for t in frame.index],
            'meta': {'regularMarketPrice': 99999},
            'indicators': {'quote': [{c.lower(): frame[c].tolist() for c in frame.columns}]},
        }]}}

    def test_yahoo_uses_historical_open_dates_not_current_meta(self):
        session = Mock()
        session.get.return_value = response(self.payload())
        frame = YahooProvider(session).fetch('ASELS.IS', '2023-01-02', '2023-01-04')
        self.assertEqual(frame.Close.iloc[-1], 115)
        self.assertEqual(frame.Open.iloc[0], 100)
        self.assertEqual(frame.index[-1], pd.Timestamp('2023-01-04'))
        self.assertIn('period1=', session.get.call_args.args[0])
        self.assertNotIn('range=', session.get.call_args.args[0])

    def test_yahoo_malformed_arrays_and_timestamps(self):
        for mode in ('arrays', 'timestamps', 'missing', 'null_close'):
            payload = self.payload()
            data = payload['chart']['result'][0]
            if mode == 'arrays':
                data['indicators']['quote'][0]['open'].pop()
            elif mode == 'timestamps':
                data['timestamp'][0] = None
            elif mode == 'missing':
                data.pop('timestamp')
            else:
                data['indicators']['quote'][0]['close'][0] = None
            session = Mock()
            session.get.return_value = response(payload)
            with self.assertRaises(ValueError):
                YahooProvider(session).fetch('ASELS.IS', '2023-01-02', '2023-01-04')

    def test_yahoo_rejects_incomplete_current_day_before_request(self):
        session = Mock()
        with self.assertRaises(ValueError):
            YahooProvider(session).fetch('ASELS.IS', '2023-01-02', '2099-01-01')
        session.get.assert_not_called()


class MetricsTests(OfflineTestCase):
    def equity(self):
        return pd.DataFrame({'date': pd.date_range('2023-01-01', periods=6).strftime('%Y-%m-%d'),
                             'equity': [1000, 1100, 1050, 1025, 1025, 1225],
                             'phase': ['initial'] + ['close'] * 5})

    def test_win_rate_profit_factor_expectancy_losing_streak(self):
        result = calculate_metrics(metric_trades(), self.equity(), 1000)
        self.assertEqual((result['winning_trades'], result['losing_trades'], result['break_even_trades']), (2, 2, 1))
        self.assertEqual(result['win_rate_pct'], 40)
        self.assertEqual(result['profit_factor'], 4)
        self.assertEqual(result['expectancy_tl'], 45)
        self.assertEqual(result['expectancy_pct'], 4.5)
        self.assertEqual(result['longest_losing_streak'], 2)

    def test_equity_drawdown_and_total_return(self):
        result = calculate_metrics(metric_trades(), self.equity(), 1000)
        self.assertAlmostEqual(result['maximum_drawdown_pct'], 75 / 1100 * 100)
        self.assertAlmostEqual(result['total_return_pct'], 22.5)
        self.assertEqual(result['net_pnl_tl'], 225)

    def test_drawdown_includes_first_loss_from_initial_capital(self):
        equity = pd.DataFrame({'date': ['2023-01-01', '2023-01-02'], 'equity': [1000, 900]})
        self.assertAlmostEqual(calculate_metrics([], equity, 1000)['maximum_drawdown_pct'], 10)

    def test_small_sample_undefined_ratios_are_none(self):
        result = calculate_metrics([], self.equity(), 1000)
        for key in ('win_rate_pct', 'profit_factor', 'expectancy_tl', 'best_trade_pct', 'sharpe_ratio', 'cagr_pct'):
            self.assertIsNone(result[key])
        result = calculate_metrics([metric_trades()[0]], self.equity(), 1000)
        self.assertIsNone(result['profit_factor'])
        self.assertEqual(result['profit_factor_status'], 'no_losses')

    def test_sharpe_and_cagr_sample_rules(self):
        dates = pd.bdate_range('2023-01-02', periods=270)
        values = 1000 * np.cumprod(1 + .001 + .002 * np.sin(np.arange(270)))
        equity = pd.DataFrame({'date': dates.strftime('%Y-%m-%d'), 'equity': values, 'phase': 'close'})
        result = calculate_metrics([], equity, 1000)
        returns = pd.Series([1000] + values.tolist()).pct_change().dropna()
        self.assertAlmostEqual(result['sharpe_ratio'], returns.mean() / returns.std() * np.sqrt(252))
        self.assertIsNotNone(result['cagr_pct'])
        self.assertIsNone(calculate_metrics([], equity.iloc[:59], 1000)['sharpe_ratio'])
        flat = equity.copy()
        flat['equity'] = 1000
        self.assertIsNone(calculate_metrics([], flat, 1000)['sharpe_ratio'])

    def test_trade_return_statistics(self):
        result = calculate_metrics(metric_trades(), self.equity(), 1000)
        self.assertEqual(result['average_trade_return_pct'], 4.5)
        self.assertEqual(result['median_trade_return_pct'], 0)
        self.assertEqual(result['average_winner_pct'], 15)
        self.assertEqual(result['average_loser_pct'], -3.75)
        self.assertEqual((result['best_trade_pct'], result['worst_trade_pct'], result['average_holding_days']), (20, -5, 3))


class ReportCLITests(OfflineTestCase):
    def result(self, generator=None):
        return run_backtest({'ASELS.IS': replay_frame()}, '2023-01-02', '2023-01-04',
                            signal_generator=generator or (lambda ticker, df: test_signal(ticker, df.index[-1].date())
                                                           if len(df) == 1 else None))

    def test_structured_outputs_summary_and_costs(self):
        result = self.result()
        output = save_report(result, run_id='test', charts=False)
        for name in ('trades.csv', 'trades.json', 'signals.csv', 'signals.json', 'equity.csv',
                     'results.json', 'summary.md', 'open_positions.json'):
            self.assertTrue((output / name).is_file())
        trades = json.loads((output / 'trades.json').read_text('utf-8'))
        self.assertEqual(trades, result.trades)
        self.assertEqual(len(pd.read_csv(output / 'trades.csv')), 1)
        summary = (output / 'summary.md').read_text('utf-8')
        for phrase in ('Commission: 0%', 'Slippage: 0%', 'next_open', 'stop_first',
                       'Look-ahead bias audit', 'News handling', 'Sharpe'):
            self.assertIn(phrase, summary)

    def test_empty_trade_outputs_have_headers_and_valid_json(self):
        output = save_report(self.result(lambda ticker, df: None), run_id='empty', charts=False)
        self.assertTrue(pd.read_csv(output / 'trades.csv').empty)
        self.assertEqual(json.loads((output / 'trades.json').read_text()), [])
        json.loads((output / 'results.json').read_text())

    def test_run_directory_no_overwrite_or_traversal(self):
        result = self.result()
        save_report(result, run_id='safe', charts=False)
        with self.assertRaises(FileExistsError):
            save_report(result, run_id='safe', charts=False)
        for name in ('..', '../other', 'C:/other'):
            with self.assertRaises(ValueError):
                save_report(result, run_id=name, charts=False)

    def test_optional_plot_dependency_missing_is_reported(self):
        with patch.dict('sys.modules', {'matplotlib': None}):
            output = save_report(self.result(), run_id='no_plot_library', charts=True)
        self.assertIn('Charts skipped', (output / 'summary.md').read_text('utf-8'))

    def test_optional_charts_render_offline(self):
        if importlib.util.find_spec('matplotlib') is None:
            self.skipTest('Optional matplotlib is not installed')
        output = save_report(self.result(), run_id='charts', charts=True)
        for name in ('equity.png', 'drawdown.png'):
            content = (output / name).read_bytes()
            self.assertEqual(content[:8], b'\x89PNG\r\n\x1a\n')
            self.assertGreater(len(content), 1000)

    def test_cli_help_and_multiple_tickers(self):
        help_text = parser().format_help()
        self.assertIn('--intrabar-policy', help_text)
        args = parser().parse_args(['--ticker', 'ASELS', '--ticker', 'THYAO', '--start', '2023-01-01', '--end', '2023-02-01'])
        self.assertEqual(args.ticker, ['ASELS', 'THYAO'])

    def test_offline_csv_cli_end_to_end(self):
        frame = historical_frame(90)
        frame.iloc[60, frame.columns.get_loc('Volume')] = 100000
        frame.loc[frame.index[60], ['Open', 'High', 'Low', 'Close']] += 2
        frame.to_csv('ASELS.IS.csv', index_label='Date')
        with redirect_stdout(StringIO()) as output:
            status = main(['--ticker', 'ASELS', '--start', frame.index[59].date().isoformat(),
                           '--end', frame.index[-1].date().isoformat(), '--csv-dir', '.', '--no-charts'])
        self.assertEqual(status, 0)
        self.assertIn('Report:', output.getvalue())
        summaries = list(Path('backtest_results').glob('*/summary.md'))
        self.assertEqual(len(summaries), 1)
        payload = json.loads((summaries[0].parent / 'results.json').read_text('utf-8'))
        self.assertEqual(payload['data_source'], 'local_csv')
        self.assertGreater(len(payload['trades']), 0)

    def test_cli_invalid_config_and_unavailable_data(self):
        with redirect_stderr(StringIO()):
            self.assertEqual(main(['--ticker', 'ASELS', '--start', '2023-01-01', '--end', '2023-02-01',
                                   '--risk-per-trade', '0', '--csv-dir', '.']), 1)
            self.assertEqual(main(['--ticker', 'ASELS', '--start', '2023-01-01', '--end', '2023-02-01',
                                   '--csv-dir', '.']), 1)
