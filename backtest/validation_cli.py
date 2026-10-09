"""Run the fixed validation basket once, producing both cost scenarios."""
import argparse
import sys

import requests

from .cli import date_argument
from .data import CSVProvider, YahooProvider
from .execution import BacktestConfig
from .validation import VALIDATION_BASKET, run_validation
from .validation_report import save_validation_report


def parser():
    defaults = BacktestConfig(max_positions=5)
    result = argparse.ArgumentParser(description='Multi-Ticker Validation v1: fixed 10-ticker basket, both cost scenarios.')
    result.add_argument('--start', type=date_argument, default=date_argument('2025-01-01'))
    result.add_argument('--end', type=date_argument, default=date_argument('2025-12-31'))
    result.add_argument('--initial-capital', type=float, default=defaults.initial_capital)
    result.add_argument('--risk-per-trade', type=float, default=defaults.risk_per_trade, help='Fraction: .01 = 1%%')
    result.add_argument('--max-concurrent-positions', type=int, default=5)
    result.add_argument('--realism-commission-pct', type=float, default=.10, help='Percentage points per side: .10 = 0.10%%')
    result.add_argument('--realism-slippage-pct', type=float, default=.10, help='Percentage points per side: .10 = 0.10%%')
    result.add_argument('--warmup-days', type=int, default=730)
    result.add_argument('--csv-dir', help='Offline <ticker>.csv files; otherwise download Yahoo data once per ticker')
    result.add_argument('--output-dir', default='backtest_results')
    result.add_argument('--no-charts', action='store_true')
    result.epilog = 'Fixed basket: ' + ', '.join(VALIDATION_BASKET) + '. Baseline always uses zero costs.'
    return result


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        config = BacktestConfig(initial_capital=args.initial_capital, risk_per_trade=args.risk_per_trade,
                                max_positions=args.max_concurrent_positions)
        provider = CSVProvider(args.csv_dir) if args.csv_dir else YahooProvider()
        result = run_validation(provider=provider, start=args.start.isoformat(), end=args.end.isoformat(), config=config,
                                realism_commission_pct=args.realism_commission_pct, realism_slippage_pct=args.realism_slippage_pct,
                                warmup_days=args.warmup_days)
        result.data_source = 'local_csv' if args.csv_dir else 'yahoo_quote_ohlcv'
        output = save_validation_report(result, args.output_dir, charts=not args.no_charts)
    except (ValueError, OSError, requests.RequestException) as error:
        print(f'Validation failed: {error}', file=sys.stderr)
        return 1
    print(f'Report: {output.resolve() / "summary.md"}')
    for name, scenario in result.scenarios.items():
        aggregate = scenario['aggregate']
        if aggregate is None:
            print(f'{name}: shared portfolio FAILED: {scenario["aggregate_failure"]}')
            continue
        metrics = aggregate.metrics
        print(f'{name}: {metrics["total_trades"]} trades; net P&L {metrics["net_pnl_tl"]:,.2f} TL; '
              f'return {metrics["total_return_pct"]:.2f}%; maximum drawdown {metrics["maximum_drawdown_pct"]:.2f}%')
    for ticker, failures in result.failures.items():
        print(f'Ticker FAILED {ticker}: ' + '; '.join(f['error'] for f in failures), file=sys.stderr)
    return 0 if all(s['aggregate'] is not None for s in result.scenarios.values()) else 1


if __name__ == '__main__':
    raise SystemExit(main())
