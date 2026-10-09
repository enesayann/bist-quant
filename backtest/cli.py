"""Run historical technical measurement without starting the live bot."""
import argparse
from datetime import date, timedelta
import sys

import requests

from bot.config import hisseler
from .data import CSVProvider, YahooProvider, normalize_ticker
from .engine import run_backtest
from .execution import BacktestConfig
from .report import save_report


def date_argument(value):
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError('Use an ISO date: YYYY-MM-DD') from error


def parser():
    result = argparse.ArgumentParser(description='Backtest v1: technical-only daily BIST strategy (no live orders).')
    tickers = result.add_mutually_exclusive_group(required=True)
    tickers.add_argument('--ticker', action='append', help='One BIST ticker; repeat for multiple tickers')
    tickers.add_argument('--universe', choices=['current'], help='Use the existing current ticker universe (survivorship bias)')
    result.add_argument('--start', type=date_argument, required=True)
    result.add_argument('--end', type=date_argument, required=True, help='Inclusive; Yahoo requires a date before today')
    result.add_argument('--initial-capital', type=float, default=100000, help='Initial cash in TL (default: 100000)')
    result.add_argument('--risk-per-trade', type=float, default=.01, help='Fraction of initial capital: .01 = 1%%')
    result.add_argument('--max-concurrent-positions', type=int, default=10)
    result.add_argument('--commission-pct', type=float, default=0, help='Percentage points per side: .1 = 0.1%%')
    result.add_argument('--slippage-pct', type=float, default=0, help='Percentage points per side: .1 = 0.1%%')
    result.add_argument('--intrabar-policy', choices=['stop_first', 'target_first'], default='stop_first')
    result.add_argument('--execution-model', choices=['next_open', 'signal_close'], default='next_open')
    result.add_argument('--csv-dir', help='Offline Date/OHLCV files named <ticker>.csv; otherwise use Yahoo')
    result.add_argument('--warmup-days', type=int, default=730, help='Calendar days fetched before start (default: 730)')
    result.add_argument('--output-dir', default='backtest_results')
    result.add_argument('--no-charts', action='store_true', help='Skip optional matplotlib charts')
    return result


def main(argv=None):
    argument_parser = parser()
    args = argument_parser.parse_args(argv)
    try:
        if args.start > args.end or args.warmup_days < 0:
            raise ValueError('Start must not follow end; warmup days must be nonnegative')
        config = BacktestConfig(args.initial_capital, args.risk_per_trade, args.max_concurrent_positions,
                                args.commission_pct, args.slippage_pct, args.intrabar_policy, args.execution_model)
        tickers = sorted(set(hisseler if args.universe else [normalize_ticker(t) for t in args.ticker]))
        provider = CSVProvider(args.csv_dir) if args.csv_dir else YahooProvider()
        data_start = (args.start - timedelta(days=args.warmup_days)).isoformat()
        # Fail clearly on unavailable tickers; never silently cherry-pick the universe.
        frames = {ticker: provider.fetch(ticker, data_start, args.end.isoformat()) for ticker in tickers}
        result = run_backtest(frames, args.start.isoformat(), args.end.isoformat(), config)
        result.data_source = 'local_csv' if args.csv_dir else 'yahoo_quote_ohlcv'
        output = save_report(result, args.output_dir, charts=not args.no_charts)
    except (ValueError, OSError, requests.RequestException) as error:
        print(f'Backtest failed: {error}', file=sys.stderr)
        return 1
    print(f'Report: {output.resolve() / "summary.md"}')
    print(f'Trades: {result.metrics["total_trades"]}; net P&L: {result.metrics["net_pnl_tl"]:,.2f} TL; '
          f'return: {result.metrics["total_return_pct"]:.2f}%')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
