"""Single-ticker data/session replay audit; no trading/backtest strategy."""
import argparse
import sys
from pathlib import Path

from . import IntradayError
from .cache import IntradayCache
from .provider import CacheProvider, CSVProvider, YahooProvider
from .replay import SessionReplay, save_replay_audit


def main(argv=None):
    parser = argparse.ArgumentParser(description='1h intraday data contract and completed-candle replay only.')
    parser.add_argument('--ticker', required=True)
    parser.add_argument('--start', required=True, help='Aware ISO timestamp; inclusive bar start')
    parser.add_argument('--end', required=True, help='Aware ISO timestamp; exclusive bar start, full bar must also end within bounds')
    parser.add_argument('--as-of', help='Aware decision cutoff; defaults to current Istanbul time')
    parser.add_argument('--gap-policy', choices=['strict', 'warn'], default='strict')
    parser.add_argument('--cache-dir', default='data/intraday_cache')
    source = parser.add_mutually_exclusive_group()
    source.add_argument('--offline', action='store_true', help='Use only previously fetched cache coverage')
    source.add_argument('--csv', help='Standalone timestamp/open/high/low/close/volume CSV')
    parser.add_argument('--source-timezone', help='Explicit timezone for naive CSV timestamps only')
    parser.add_argument('--output-dir', default='backtest_results/intraday_replay_audit')
    args = parser.parse_args(argv)
    cache = IntradayCache(args.cache_dir)
    provider = (CSVProvider(args.csv, source_timezone=args.source_timezone) if args.csv else
                CacheProvider(cache) if args.offline else YahooProvider(cache=cache, raw_output=Path(args.output_dir) / 'raw'))
    try:
        dataset = provider.fetch(args.ticker, args.start, args.end, as_of=args.as_of, gap_policy=args.gap_policy)
        replay = SessionReplay(dataset, gap_policy=args.gap_policy)
        steps = sum(1 for _ in replay)
        audit = dict(replay.diagnostics, replay_steps=steps)
        directory = save_replay_audit(audit, candles=dataset.candles, output=args.output_dir)
    except (IntradayError, OSError) as error:
        audit = dict(getattr(error, 'diagnostics', {}))
        audit.setdefault('ticker', args.ticker)
        audit.setdefault('requested_start', args.start)
        audit.setdefault('requested_end', args.end)
        directory = save_replay_audit(audit, output=args.output_dir, status='failed', error=error)
        print(f'Replay failed: {error}\nAudit: {directory.resolve() / "summary.md"}', file=sys.stderr)
        return 1
    print(f'Replayed {steps} completed candles. Audit: {directory.resolve() / "summary.md"}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
