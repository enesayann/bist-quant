"""Execution ordering, capital conservation and daily replay (offline)."""
from dataclasses import replace

import numpy as np
import pandas as pd

from backtest.engine import run_backtest
from backtest.execution import (BacktestConfig, close_position, open_position,
                                position_quantity, process_candle)
from tests.helpers import OfflineTestCase
from tests.test_backtest_signals import test_signal


def bar(opening=100, high=110, low=90, close=105, atr=10):
    return {'Open': opening, 'High': high, 'Low': low, 'Close': close, 'ATR': atr}


def replay_frame(rows=None):
    rows = rows or [[100, 110, 90, 100, 1000], [110, 119, 106, 110, 1000],
                    [112, 119, 107, 115, 1000]]
    return pd.DataFrame(rows, columns=['Open', 'High', 'Low', 'Close', 'Volume'],
                        index=pd.bdate_range('2023-01-02', periods=len(rows)))


class ExecutionTests(OfflineTestCase):
    def setUp(self):
        super().setUp()
        self.config = BacktestConfig()
        self.position = open_position(test_signal('ASELS.IS', '2023-01-02'), '2023-01-03', 100, 100000, self.config)

    def test_stop_only(self):
        self.assertEqual(process_candle(self.position, bar(high=110, low=80), self.config), (85, 'STOP'))

    def test_tp1_break_even_no_partial_sale(self):
        self.assertIsNone(process_candle(self.position, bar(high=121, low=90, close=105), self.config))
        self.assertTrue(self.position.tp1_hit)
        self.assertEqual((self.position.stop, self.position.quantity), (100, 66))

    def test_tp2(self):
        self.assertEqual(process_candle(self.position, bar(high=131, low=90), self.config), (130, 'TP2'))
        self.assertTrue(self.position.tp1_hit)

    def test_tp1_then_break_even(self):
        process_candle(self.position, bar(high=121), self.config)
        self.assertEqual(process_candle(self.position, bar(opening=105, high=110, low=99), self.config), (100, 'BREAK_EVEN'))

    def test_trailing_only_takes_effect_on_next_candle(self):
        self.assertIsNone(process_candle(self.position, bar(high=112, low=90, close=110, atr=3), self.config))
        self.assertEqual(self.position.stop, 105.5)
        self.assertEqual(process_candle(self.position, bar(opening=108, high=110, low=105, close=108, atr=3), self.config),
                         (105.5, 'TRAILING_STOP'))

    def test_trailing_never_moves_down(self):
        process_candle(self.position, bar(high=112, low=106, close=110, atr=3), self.config)
        self.assertIsNone(process_candle(self.position, bar(opening=108, high=110, low=107, close=108, atr=10), self.config))
        self.assertEqual(self.position.stop, 105.5)

    def test_same_candle_stop_first(self):
        self.assertEqual(process_candle(self.position, bar(high=140, low=80), self.config), (85, 'STOP'))

    def test_same_candle_target_first(self):
        cfg = replace(self.config, intrabar_policy='target_first')
        self.assertEqual(process_candle(self.position, bar(high=140, low=80), cfg), (130, 'TP2'))

    def test_target_first_tp1_before_ambiguous_low(self):
        cfg = replace(self.config, intrabar_policy='target_first')
        self.assertEqual(process_candle(self.position, bar(high=121, low=80), cfg), (100, 'BREAK_EVEN'))

    def test_stop_first_tp1_and_old_stop_touch(self):
        self.assertEqual(process_candle(self.position, bar(high=121, low=80), self.config), (85, 'STOP'))

    def test_open_gap_stop_precedes_target_first(self):
        cfg = replace(self.config, intrabar_policy='target_first')
        self.assertEqual(process_candle(self.position, bar(opening=80, high=140, low=70), cfg), (80, 'STOP'))

    def test_open_gap_above_tp2_fills_open(self):
        self.assertEqual(process_candle(self.position, bar(opening=140, high=145, low=80), self.config), (140, 'TP2'))

    def test_open_gap_through_tp1_activates_break_even_immediately(self):
        self.assertEqual(process_candle(self.position, bar(opening=121, high=125, low=95), self.config), (100, 'BREAK_EVEN'))

    def test_commission_both_sides(self):
        cfg = replace(self.config, commission_pct=1)
        position = open_position(test_signal('ASELS.IS', '2023-01-02'), '2023-01-03', 100, 100000, cfg)
        trade, proceeds = close_position(position, '2023-01-04', 130, 'TP2', cfg)
        self.assertEqual(trade['gross_pnl_tl'], 30 * position.quantity)
        self.assertAlmostEqual(trade['net_pnl_tl'], (30 - 1 - 1.3) * position.quantity)
        self.assertAlmostEqual(proceeds, 128.7 * position.quantity)

    def test_adverse_slippage_entry_and_exit(self):
        cfg = replace(self.config, slippage_pct=1)
        position = open_position(test_signal('ASELS.IS', '2023-01-02'), '2023-01-03', 100, 100000, cfg)
        trade, _ = close_position(position, '2023-01-04', 130, 'TP2', cfg)
        self.assertEqual(position.entry_price, 101)
        self.assertEqual(trade['exit_price'], 128.7)
        self.assertAlmostEqual(trade['gross_pnl_tl'], 27.7 * position.quantity)

    def test_risk_sizing_and_cash_cap(self):
        self.assertEqual(position_quantity(100, 85, 100000, .01, 100000), 66)
        self.assertEqual(position_quantity(100, 85, 100000, .01, 1000), 10)
        self.assertEqual(position_quantity(100, 85, 100000, .01, 1000, 1), 9)

    def test_zero_or_reversed_stop_distance(self):
        self.assertEqual(position_quantity(100, 100, 100000, .01, 100000), 0)
        self.assertEqual(position_quantity(100, 101, 100000, .01, 100000), 0)

    def test_invalid_sizing(self):
        for stop in (np.nan, np.inf, 0, -1):
            with self.assertRaises(ValueError):
                position_quantity(100, stop, 100000, .01, 100000)

    def test_invalid_config(self):
        for kwargs in ({'risk_per_trade': 0}, {'risk_per_trade': 2}, {'initial_capital': -1},
                       {'commission_pct': -1}, {'slippage_pct': 100}, {'max_positions': 0},
                       {'initial_capital': np.nan}, {'intrabar_policy': 'unknown'},
                       {'execution_model': 'unknown'}, {'max_positions': 1.5}):
            with self.assertRaises(ValueError):
                BacktestConfig(**kwargs)


class ReplayTests(OfflineTestCase):
    def replay(self, frame=None, config=None, tickers=None, generator=None, end='2023-01-04'):
        frame = replay_frame() if frame is None else frame
        frames = tickers or {'ASELS.IS': frame}
        generator = generator or (lambda ticker, history: test_signal(ticker, history.index[-1].date())
                                   if len(history) == 1 else None)
        return run_backtest(frames, '2023-01-02', end, config, generator)

    def test_signal_enters_next_open_rebased_atr_levels(self):
        result = self.replay()
        trade = result.trades[0]
        self.assertEqual((trade['signal_date'], trade['entry_date'], trade['entry_price']),
                         ('2023-01-02', '2023-01-03', 110))
        self.assertEqual((trade['initial_stop'], trade['tp1'], trade['tp2']), (95, 130, 140))
        self.assertEqual(trade['exit_reason'], 'END_OF_DATA')

    def test_missing_next_candle_skips_entry(self):
        result = self.replay(replay_frame().iloc[:1])
        self.assertEqual(result.trades, [])
        self.assertTrue(any('no next candle' in warning for warning in result.warnings))

    def test_missing_open_does_not_fall_back_to_later_open(self):
        frame = replay_frame()
        frame.loc[frame.index[1], 'Open'] = np.nan
        result = self.replay(frame)
        self.assertEqual(result.trades, [])
        self.assertTrue(any('Open is missing' in warning for warning in result.warnings))

    def test_signal_close_does_not_replay_signal_candle_low(self):
        frame = replay_frame()
        frame.loc[frame.index[0], 'Low'] = 50
        result = self.replay(frame, BacktestConfig(execution_model='signal_close'))
        self.assertEqual(result.trades[0]['entry_date'], '2023-01-02')
        self.assertEqual(result.trades[0]['exit_reason'], 'END_OF_DATA')

    def test_new_open_can_hit_stop_on_entry_day(self):
        frame = replay_frame()
        frame.loc[frame.index[1], 'Low'] = 80
        trade = self.replay(frame).trades[0]
        self.assertEqual((trade['exit_reason'], trade['entry_date'], trade['exit_date']),
                         ('STOP', '2023-01-03', '2023-01-03'))

    def test_max_positions_sorted_allocation(self):
        frame = replay_frame()
        result = self.replay(config=BacktestConfig(max_positions=1), tickers={'Z.IS': frame, 'A.IS': frame})
        self.assertEqual([t['ticker'] for t in result.trades], ['A.IS'])
        self.assertTrue(any('maximum positions' in warning for warning in result.warnings))

    def test_cash_reservation_no_leverage(self):
        frame = replay_frame()
        cfg = BacktestConfig(initial_capital=1000, risk_per_trade=1, commission_pct=1)
        result = self.replay(config=cfg, tickers={'A.IS': frame, 'B.IS': frame})
        self.assertEqual(len(result.trades), 1)
        self.assertTrue((result.equity.cash >= -1e-8).all())
        self.assertAlmostEqual(result.metrics['net_pnl_tl'], sum(t['net_pnl_tl'] for t in result.trades))

    def test_no_pyramiding(self):
        result = self.replay(generator=lambda ticker, history: test_signal(ticker, history.index[-1].date()))
        self.assertEqual(len(result.trades), 1)
        self.assertEqual(len(result.signals), 3)

    def test_engine_passes_only_prefix_and_is_deterministic(self):
        seen = []
        def generator(ticker, history):
            seen.append((ticker, len(history), history.index[-1]))
            return test_signal(ticker, history.index[-1].date()) if len(history) == 1 else None
        first = self.replay(generator=generator)
        second = self.replay(generator=generator)
        self.assertEqual([s[1] for s in seen], [1, 2, 3, 1, 2, 3])
        self.assertEqual(first.trades, second.trades)
        pd.testing.assert_frame_equal(first.equity, second.equity)

    def test_stale_ticker_is_not_liquidated_early_to_free_cash(self):
        frame = replay_frame()
        result = self.replay(tickers={'A.IS': frame.iloc[:2], 'B.IS': frame})
        self.assertEqual([t['ticker'] for t in result.trades], ['B.IS'])
        self.assertEqual(result.open_positions[0]['ticker'], 'A.IS')
        self.assertEqual(result.equity.open_positions.iloc[-1], 1)
        self.assertTrue(any('remains open' in warning for warning in result.warnings))

    def test_no_trade_range_before_start(self):
        frame = replay_frame()
        calls = []
        def generator(ticker, history):
            calls.append(history.index[-1])
        run_backtest({'ASELS.IS': frame}, '2023-01-03', '2023-01-04', signal_generator=generator)
        self.assertEqual(calls, list(frame.index[1:]))

    def test_invalid_or_empty_date_range(self):
        with self.assertRaises(ValueError):
            run_backtest({}, '2023-01-01', '2023-02-01')
        with self.assertRaises(ValueError):
            self.replay(end='2022-01-01')
        with self.assertRaises(ValueError):
            run_backtest({'ASELS.IS': replay_frame()}, '2024-01-01', '2024-02-01')
