"""Fixed 2023/2024/2025 validation with preserved strategy and execution settings."""
import argparse
import sys

import requests

from .data import CSVProvider, YahooProvider
from .multi_year import SCENARIOS, run_multi_year
from .multi_year_report import save_multi_year_report


def parser():
    result = argparse.ArgumentParser(description='Multi-Year Validation v1: fixed 10 tickers, 2023/2024/2025, independent 100,000 TL annual portfolios.')
    result.add_argument('--csv-dir', help='Offline <ticker>.csv files; otherwise use Yahoo with existing validation')
    result.add_argument('--output-dir', default='backtest_results')
    result.add_argument('--no-charts', action='store_true')
    result.add_argument('--no-chained-view', action='store_true', help='Omit the optional return-linked illustration; primary annual results are unchanged')
    result.epilog = 'Primary realism: 0.10% commission + 0.10% slippage per side. Secondary baseline: zero costs. Fixed 1% risk, 5 positions, next_open, stop_first.'
    return result


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        provider = CSVProvider(args.csv_dir) if args.csv_dir else YahooProvider()
        result = run_multi_year(provider=provider, include_chained_view=not args.no_chained_view, progress=print)
        for annual in result.annual.values():
            annual.data_source = 'local_csv' if args.csv_dir else 'yahoo_quote_ohlcv'
        directory = save_multi_year_report(result, args.output_dir, charts=not args.no_charts)
    except (ValueError, OSError, requests.RequestException) as error:
        print(f'Multi-year validation failed: {error}', file=sys.stderr)
        return 1
    print(f'Combined report: {directory.resolve() / "summary.md"}')
    for row in result.comparison:
        if row['net_pnl_tl'] is None:
            print(f'{row["year"]} {row["scenario"]}: FAILED: {row["failure"]}')
        else:
            print(f'{row["year"]} {row["scenario"]}: {row["total_trades"]} trades; net P&L {row["net_pnl_tl"]:,.2f} TL; '
                  f'return {row["total_return_pct"]:.2f}%; maximum drawdown {row["maximum_drawdown_pct"]:.2f}%; {row["status"]}')
    for year, annual in result.annual.items():
        for ticker, failures in annual.failures.items():
            print(f'{year} ticker FAILED {ticker}: ' + '; '.join(f['error'] for f in failures), file=sys.stderr)
    return 0 if all(result.stability[scenario]['coverage_complete'] for scenario in SCENARIOS) else 1


if __name__ == '__main__':
    raise SystemExit(main())
