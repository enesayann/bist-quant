"""CSV/JSON/Markdown and optional charts; no strategy calculations here."""
from dataclasses import asdict, fields
from datetime import datetime
import csv
import json
from pathlib import Path
from uuid import uuid4

import pandas as pd

from bot.config import TR_TZ
from .signals import Signal


AUDIT = """## Look-ahead bias audit

- EMA, Wilder RSI/ATR/ADX, MACD, Bollinger, OBV, MFI, CMF, StochRSI,
  approximate VWAP, Donchian and historical volatility use trailing windows,
  forward cumulative updates, or EWM. SuperTrend loops forward. Their causal
  series may be prepared once; decisions receive a prefix ending at date t.
- Ichimoku uses trailing 9/26/52 windows and positive shift(26), which moves
  past values forward. No negative shift or future Chikou comparison is used.
- Live HH/HL and support/resistance use centered 11-candle windows. Computing
  them once over full history and reading an earlier date would leak future
  candles. HH/HL is reused only on the current prefix: the last five candles
  cannot be confirmed pivots. Support/resistance uses a trailing confirmation
  equivalent over the same last 60 candles, with the same fallback extremes.
  Pivot values become available five candles later, never at the pivot date.
- Live trailing logic raises a stop from today's close/ATR before checking
  today's low. Backtest checks the already active stop first, then raises the
  close-based trailing stop for the next candle. TP1 also moves the stop to
  entry without a partial sale. Under stop_first, an intraday TP1 break-even
  update starts on the next candle. Under target_first it precedes an ambiguous
  same-candle low. An opening gap through TP1 has known precedence in both.
- Historical reference prices are daily Close, never regularMarketPrice.
  Historical news, cached news, and current fundamentals are never read.
- Existing live files and production strategy behavior were not modified.
"""

LIMITATIONS = """## Assumptions and known limitations

- Technical-only v1: news and historical fundamentals each earn zero points.
  The live score denominator remains 80; weights are not renormalized. Reports
  expose both live-formula final_score and technical_score; confidence and
  eligibility use technical_score, as live does. The whale volume exception
  (+2 confidence, bypassing the normal threshold) remains enabled. All
  news-dependent signal branches are disabled. Live signals are alerts;
  this backtest automatically buys eligible signals as a measurement rule.
- Daily OHLC cannot establish the order of stop and target touches.
  stop_first favors the active stop; target_first favors TP2, then TP1
  break-even, before a low. Opening stop/target gaps execute at the open.
  Stops may therefore lose more than the nominal risk. Targets execute at
  their level unless the opening gap is above TP2. No price-limit/queue model.
- Entry uses the next available ticker candle's Open. A missing Open skips
  the order; the engine never substitutes a later open. Orders blocked by cash
  or position limits expire. Without an exchange calendar, an entirely missing
  session cannot be distinguished from a holiday; audit data coverage first.
- ATR from the signal candle is fixed at entry; 1.5/2/3 ATR stop/TP1/TP2 levels
  are rebased to the slippage-adjusted fill, rather than the signal Close.
  Trailing uses new highest Close and that candle's ATR (1.5 multiplier),
  never the intraday High. Stop updates never move down. TP1 sells no shares.
- Risk quantity is floor(initial capital * risk fraction / stop distance),
  matching the fixed portfolio-size live model. Cash and entry commission
  cap the quantity; cash is reserved at entry. No leverage, shorts, pyramiding,
  interest, dividends, taxes or exchange-specific fees. Simultaneous orders
  allocate in alphabetical ticker order before intraday exit proceeds exist.
- Commission is a percentage of actual entry/exit notional. Slippage increases
  buy fills and reduces sell fills. Gross P&L includes slippage, excludes fees;
  net P&L includes both fees. Net trade returns divide by entry cash including
  entry commission. Break-even price can still incur a net loss from costs.
- Equity = cash + open shares marked at latest available Close. Missing ticker
  dates carry the last known Close. Drawdown includes the initial capital.
  End-of-range liquidation uses the final actual Close and exit costs. This is
  a reporting exit, not a strategy prediction. A ticker missing the final
  portfolio candle remains open, exported separately at a stale mark; no
  hypothetical earlier liquidation frees cash for other tickers.
  Short histories, sparse data,
  and reporting liquidations can materially change results.
- Indicator warmup uses up to two calendar years before requested start,
  then expanding history. EWM seeds depend on available warmup; the live bot's
  repeatedly downloaded rolling two-year window may differ. Minimum data,
  EMA200 and Ichimoku gates are preserved. CSV warmup is not fabricated.
- Yahoo quote OHLC is used like the live bot, without adjusted-close dividend
  substitution. Yahoo may revise/split-adjust past prices; no point-in-time
  corporate-action or symbol-history database exists. The current 153-ticker
  universe has survivorship bias and is not historical index membership.
- Sharpe uses net daily marked equity simple returns, zero risk-free rate,
  sample standard deviation and sqrt(252), including the first day's costs.
  It requires 60 observations and nonzero volatility. CAGR requires at least
  365 calendar days and 252 close observations. Insufficient/undefined ratios
  are null/N/A, including profit factor without losses. Sparse union-of-ticker
  dates can distort annualization. Metrics are descriptive, not optimization.
"""


TRADE_COLUMNS = [
    'ticker', 'signal_date', 'entry_date', 'entry_price', 'exit_date', 'exit_price',
    'exit_reason', 'initial_stop', 'final_stop', 'tp1', 'tp2', 'tp1_hit',
    'holding_days', 'holding_bars', 'quantity', 'gross_pnl_tl', 'net_pnl_tl',
    'gross_return_pct', 'net_return_pct', 'entry_commission_tl', 'exit_commission_tl',
    'score_at_entry', 'technical_score_at_entry', 'classification', 'confidence',
    'signal_type', 'atr_at_entry', 'intrabar_policy',
]


def write_csv(path, records, columns):
    with path.open('w', encoding='utf-8', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(records)


def plot_curves(equity, directory):
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
    except ImportError:
        return 'Charts skipped: matplotlib is optional and not installed.'
    dates = pd.to_datetime(equity.date)
    for column, title, name in [('equity', 'Portfolio equity (TL)', 'equity.png'),
                                ('drawdown_pct', 'Drawdown (%)', 'drawdown.png')]:
        figure, axis = plt.subplots(figsize=(10, 4))
        axis.plot(dates, equity[column])
        axis.set_title(title)
        axis.grid(alpha=.25)
        figure.autofmt_xdate()
        figure.tight_layout()
        figure.savefig(directory / name, dpi=140)
        plt.close(figure)
    return None


def save_report(result, output='backtest_results', run_id=None, charts=True):
    run_id = run_id or datetime.now(TR_TZ).strftime('%Y%m%d_%H%M%S') + '_' + uuid4().hex[:8]
    if Path(run_id).name != run_id or run_id in ('.', '..') or '/' in run_id or '\\' in run_id:
        raise ValueError('run_id must be a single directory name')
    directory = Path(output) / run_id
    directory.mkdir(parents=True, exist_ok=False)
    warnings = list(result.warnings)
    if charts:
        warning = plot_curves(result.equity, directory)
        if warning:
            warnings.append(warning)
    write_csv(directory / 'trades.csv', result.trades, TRADE_COLUMNS)
    write_csv(directory / 'signals.csv', result.signals, [f.name for f in fields(Signal)])
    result.equity.to_csv(directory / 'equity.csv', index=False)
    payload = {'start': result.start, 'end': result.end, 'tickers': result.tickers,
               'data_source': result.data_source, 'open_positions': result.open_positions,
               'data_validation': result.data_validation,
               'allocation_policy': result.allocation_policy, 'entry_decisions': result.entry_decisions,
               'selectivity': result.selectivity,
               'config': asdict(result.config), 'metrics': result.metrics,
               'warnings': warnings, 'trades': result.trades, 'signals': result.signals}
    (directory / 'trades.json').write_text(json.dumps(result.trades, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    (directory / 'signals.json').write_text(json.dumps(result.signals, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    (directory / 'open_positions.json').write_text(json.dumps(result.open_positions, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    (directory / 'data_validation.json').write_text(json.dumps(result.data_validation, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    (directory / 'results.json').write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    cfg = result.config
    lines = [
        '# Backtest v1 summary', '',
        f'Date range: {result.start} through {result.end} (inclusive).',
        f'Observed candles: {result.equity.date.iloc[1]} through {result.equity.date.iloc[-1]}.',
        f'Ticker count: {len(result.tickers)}. Tickers: {", ".join(result.tickers)}.',
        f'Data source: {result.data_source}. Unclosed positions: {len(result.open_positions)}.',
        f'Initial capital: {cfg.initial_capital:,.2f} TL.',
        f'Ending capital: {result.metrics["ending_capital_tl"]:,.2f} TL.',
        f'Risk per trade: {cfg.risk_per_trade * 100:g}% of initial capital. Maximum positions: {cfg.max_positions}.',
        f'Commission: {cfg.commission_pct:g}% per side. Slippage: {cfg.slippage_pct:g}% per side.',
        f'Execution model: {cfg.execution_model}. Intrabar policy: {cfg.intrabar_policy}.',
        'News handling: disabled, zero points; no historical or current cached news.',
        'Historical fundamentals: absent, zero points; original score weights retained.',
        '', '## Performance metrics', '', '| Metric | Value |', '| --- | ---: |',
    ]
    for key, value in result.metrics.items():
        display = 'N/A' if value is None else f'{value:.4f}' if isinstance(value, float) else str(value)
        lines.append(f'| {key} | {display} |')
    lines += ['', '## Historical data validation', '',
              'Downloaded counts include indicator warmup. Requested counts cover only the trading date range.',
              'Missing OHLC or Volume removes the whole candle; no price/volume fill or interpolation.',
              'Infinity, negative volume, nonpositive prices and inconsistent OHLC fail the run.',
              'Default removal limit: 5%, checked separately in downloaded history and the requested period; actual limits are in data_validation.json.',
              '', '| Ticker | Rows downloaded | Rows removed | Final usable rows | Requested downloaded | Requested removed | Requested usable |',
              '| --- | ---: | ---: | ---: | ---: | ---: | ---: |']
    for audit in result.data_validation:
        lines.append(f'| {audit["ticker"]} | {audit["rows_downloaded"]} | {audit["rows_removed"]} | '
                     f'{audit["usable_rows"]} | {audit["requested_rows_downloaded"]} | '
                     f'{audit["requested_rows_removed"]} | {audit["requested_usable_rows"]} |')
    lines += ['', '### Validation warnings', '']
    validation_warnings = [w for audit in result.data_validation for w in audit['warnings']]
    lines += ['- ' + w for w in validation_warnings] or ['None.']
    lines += ['', '## Warnings', ''] + (['- ' + w for w in warnings] or ['None.'])
    lines += ['', AUDIT, LIMITATIONS]
    (directory / 'summary.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return directory
