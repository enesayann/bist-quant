"""Factual basket exports and charts; independent and shared results are labeled."""
from dataclasses import asdict
from datetime import datetime
import json
from pathlib import Path
from uuid import uuid4

import pandas as pd

from bot.config import TR_TZ
from .report import AUDIT, TRADE_COLUMNS, write_csv
from .validation import PER_TICKER_COLUMNS, RANKING_RULE


def serialize_replay(result):
    if result is None:
        return None
    return {'config': asdict(result.config), 'tickers': result.tickers, 'metrics': result.metrics,
            'allocation_policy': result.allocation_policy, 'selectivity': result.selectivity,
            'trades': result.trades, 'signals': result.signals, 'entry_decisions': result.entry_decisions,
            'open_positions': result.open_positions, 'data_validation': result.data_validation,
            'warnings': result.warnings}


def display(value, decimals=2):
    if value is None:
        return 'N/A'
    if isinstance(value, float):
        if value == 0:
            value = 0.0
        return f'{value:,.{decimals}f}'
    return str(value).replace('|', '\\|').replace('\n', ' ')


def plot_validation(result, directory):
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
    except ImportError:
        return ['Charts skipped: optional matplotlib is not installed.']
    colors = {'baseline': '#2465a8', 'realism': '#dc8124'}
    available = [(name, scenario) for name, scenario in result.scenarios.items() if scenario['aggregate'] is not None]
    if not available:
        return ['Aggregate charts skipped: both shared replays are unavailable.']
    for column, title, filename in [('equity', 'Shared portfolio equity (TL)', 'aggregate_equity.png'),
                                    ('drawdown_pct', 'Shared portfolio drawdown (%)', 'drawdown.png')]:
        figure, axis = plt.subplots(figsize=(10, 4))
        for name, scenario in available:
            equity = scenario['aggregate'].equity
            axis.plot(pd.to_datetime(equity.date), equity[column], label=name, color=colors[name])
        axis.set_title(title)
        axis.legend()
        axis.grid(alpha=.25)
        figure.autofmt_xdate()
        figure.tight_layout()
        figure.savefig(directory / filename, dpi=140)
        plt.close(figure)
    for column, title, filename in [('shared_net_pnl_tl', 'Shared per-ticker net P&L contribution (TL)', 'per_ticker_net_pnl.png'),
                                    ('shared_trade_count', 'Shared per-ticker executed entry count', 'per_ticker_trade_count.png')]:
        figure, axis = plt.subplots(figsize=(12, 4.5))
        width = .36
        for number, (name, scenario) in enumerate(available):
            rows = {r['ticker']: r for r in result.per_ticker if r['scenario'] == name}
            positions = [i + (number - (len(available) - 1) / 2) * width for i in range(len(result.tickers))]
            values = [rows[ticker][column] if rows[ticker][column] is not None else float('nan') for ticker in result.tickers]
            axis.bar(positions, values, width=width, label=name, color=colors[name])
        axis.set_xticks(range(len(result.tickers)), [t.replace('.IS', '') for t in result.tickers], rotation=30)
        axis.set_title(title)
        axis.axhline(0, color='#666666', linewidth=.8)
        axis.grid(axis='y', alpha=.25)
        axis.legend()
        figure.tight_layout()
        figure.savefig(directory / filename, dpi=140)
        plt.close(figure)
    return []


def save_validation_report(result, output='backtest_results', run_id=None, charts=True):
    run_id = run_id or datetime.now(TR_TZ).strftime('%Y%m%d_%H%M%S') + '_validation_' + uuid4().hex[:8]
    if Path(run_id).name != run_id or run_id in ('.', '..') or '/' in run_id or '\\' in run_id:
        raise ValueError('run_id must be a single directory name')
    directory = Path(output) / run_id
    directory.mkdir(parents=True, exist_ok=False)
    chart_warnings = plot_validation(result, directory) if charts else []
    write_csv(directory / 'per_ticker.csv', result.per_ticker, PER_TICKER_COLUMNS)
    shared_trades, independent_trades, equity_rows, decisions = [], [], [], []
    for name, scenario in result.scenarios.items():
        for ticker, replay in scenario['independent'].items():
            independent_trades.extend(dict(trade, scenario=name) for trade in replay.trades)
        aggregate = scenario['aggregate']
        if aggregate is None:
            continue
        shared_trades.extend(dict(trade, scenario=name) for trade in aggregate.trades)
        equity_rows.extend(dict(row, scenario=name) for row in aggregate.equity.to_dict('records'))
        decisions.extend(dict(row, scenario=name) for row in aggregate.entry_decisions)
    write_csv(directory / 'trades.csv', shared_trades, ['scenario'] + TRADE_COLUMNS)
    write_csv(directory / 'independent_trades.csv', independent_trades, ['scenario'] + TRADE_COLUMNS)
    equity_columns = ['scenario', 'date', 'phase', 'cash', 'market_value', 'equity', 'open_positions', 'drawdown_pct']
    write_csv(directory / 'equity_curve.csv', equity_rows, equity_columns)
    write_csv(directory / 'drawdown.csv', [{key: row[key] for key in ('scenario', 'date', 'phase', 'drawdown_pct')}
                                         for row in equity_rows], ['scenario', 'date', 'phase', 'drawdown_pct'])
    decision_columns = ['scenario', 'ticker', 'signal_date', 'attempt_date', 'status', 'reason',
                        'confidence', 'technical_score', 'final_score', 'quantity', 'entry_price']
    write_csv(directory / 'entry_decisions.csv', decisions, decision_columns)
    payload = {'start': result.start, 'end': result.end, 'requested_tickers': result.tickers,
               'data_source': result.data_source, 'input_data_sha256': result.input_data_hashes,
               'ranking_rule': RANKING_RULE, 'failures': result.failures, 'data_validation': result.data_validation,
               'per_ticker': result.per_ticker, 'warnings': result.warnings + chart_warnings, 'scenarios': {}}
    for name, scenario in result.scenarios.items():
        payload['scenarios'][name] = {'config': asdict(scenario['config']),
                                    'aggregate': serialize_replay(scenario['aggregate']),
                                    'aggregate_failure': scenario['aggregate_failure'],
                                    'independent': {ticker: serialize_replay(replay) for ticker, replay in scenario['independent'].items()},
                                    'concentration': scenario['concentration'], 'selectivity': scenario['selectivity'],
                                    'warnings': scenario['warnings']}
    (directory / 'validation.json').write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    (directory / 'data_validation.json').write_text(json.dumps(result.data_validation, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    lines = ['# Multi-Ticker Validation v1', '', f'Dates: {result.start} through {result.end} (inclusive).',
             f'Requested basket ({len(result.tickers)}): {", ".join(result.tickers)}.',
             f'Data source: {result.data_source}. Data fetched once and shared by both scenarios; input SHA256s in validation.json.',
             'Technical-only: historical news = zero/neutral; historical fundamentals = zero/neutral. Existing score weights retained.',
             'No optimization, parameter search, significance claim or profitability conclusion.', '', '## Configuration', '',
             '| Scenario | Initial capital TL | Risk fraction | Max positions | Entry | Intrabar | Commission % per side | Slippage % per side |',
             '| --- | ---: | ---: | ---: | --- | --- | ---: | ---: |']
    for name, scenario in result.scenarios.items():
        cfg = scenario['config']
        lines.append(f'| {name} | {display(cfg.initial_capital)} | {cfg.risk_per_trade:g} | {cfg.max_positions} | '
                     f'{cfg.execution_model} | {cfg.intrabar_policy} | {cfg.commission_pct:g} | {cfg.slippage_pct:g} |')
    lines += ['', 'Ranking: ' + RANKING_RULE,
              'Commission 0.10 means 0.10% (0.001 of actual fill notional), charged on both sides. Slippage 0.10 means buys fill at reference * 1.001 and sells at reference * 0.999.',
              'Gross P&L includes slippage, excludes commissions; net P&L includes both entry/exit commissions. Logs expose fill prices and commission amounts.',
              'Each independent ticker starts with the full configured capital. Shared portfolio starts with that capital ONCE. Independent returns/P&L are not summed as a shared portfolio.',
              '', '## Shared aggregate metrics', '', '| Metric | Baseline | Realism |', '| --- | ---: | ---: |']
    labels = [('total_trades', 'Closed trades'), ('winning_trades', 'Wins'), ('losing_trades', 'Losses'),
              ('win_rate_pct', 'Win rate %'), ('ending_capital_tl', 'Ending equity TL'), ('net_pnl_tl', 'Net P&L TL'),
              ('total_return_pct', 'Total return %'), ('maximum_drawdown_pct', 'Maximum drawdown %'),
              ('profit_factor', 'Profit factor'), ('profit_factor_status', 'Profit factor status'),
              ('expectancy_tl', 'Expectancy TL'), ('expectancy_pct', 'Expectancy %'),
              ('average_trade_return_pct', 'Average net trade return %'), ('median_trade_return_pct', 'Median net trade return %'),
              ('longest_losing_streak', 'Longest losing streak'), ('average_holding_days', 'Average holding days'),
              ('sharpe_ratio', 'Sharpe ratio (descriptive)'), ('cagr_pct', 'CAGR %')]
    for key, label in labels:
        values = [display(scenario['aggregate'].metrics[key]) if scenario['aggregate'] else 'N/A'
                  for scenario in result.scenarios.values()]
        lines.append(f'| {label} | ' + ' | '.join(values) + ' |')
    for name, scenario in result.scenarios.items():
        lines += ['', f'## Per-ticker independent results — {name}', '',
                  'One row for every requested ticker; missing/failed metrics are N/A. Each successful independent replay has its own full starting capital.',
                  '', '| Ticker | Status | Trades | Wins | Losses | Win % | Net TL | Return % | Max DD % | PF | Expectancy TL | Avg return % | Best % | Worst % | Hold days |',
                  '| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |']
        scenario_rows = [row for row in result.per_ticker if row['scenario'] == name]
        for row in scenario_rows:
            keys = ['ticker', 'status', 'trade_count', 'winning_trades', 'losing_trades', 'win_rate_pct', 'net_pnl_tl',
                    'total_return_pct', 'maximum_drawdown_pct', 'profit_factor', 'expectancy_tl', 'average_trade_return_pct',
                    'best_trade_pct', 'worst_trade_pct', 'average_holding_days']
            lines.append('| ' + ' | '.join(display(row[key]) for key in keys) + ' |')
        lines += ['', f'## Shared contribution and concentration — {name}', '',
                  'Net P&L contributions include marked unclosed positions and entry fees. Signed percentages may be negative or exceed 100% when gains and losses offset; a zero denominator is N/A.',
                  '', '| Ticker | Shared status | Entries | Closed trades | Net contribution TL | % total net P&L | % total entries |',
                  '| --- | --- | ---: | ---: | ---: | ---: | ---: |']
        for row in scenario_rows:
            keys = ['ticker', 'shared_status', 'shared_trade_count', 'shared_closed_trades', 'shared_net_pnl_tl', 'pnl_share_pct', 'trade_share_pct']
            lines.append('| ' + ' | '.join(display(row[key]) for key in keys) + ' |')
        concentration = scenario['concentration']
        if concentration:
            for key, label in [('largest_positive_contributor', 'Largest positive contributor'),
                               ('largest_negative_contributor', 'Largest negative contributor')]:
                row = concentration[key]
                lines.append(f'{label}: ' + (f'{row["ticker"]}, {display(row["net_pnl_tl"])} TL.' if row else 'None.'))
            lines.append('Any ticker above 50% of total signed net P&L: '
                         + ('Yes: ' + ', '.join(concentration['tickers_above_50_pct_net_pnl']) if concentration['one_ticker_above_50_pct_net_pnl'] else 'No') + '.')
        lines += ['', f'## Signal selectivity — {name}', '',
                  'Ticker-days count usable in-range candles passed to the signal generator; signal-ready days additionally meet the existing 60-candle minimum. Signals include signals while already holding. Executed entries include unclosed positions; closed trade count is reported separately.',
                  'Capital/concurrency skips count attempted entries only. No-next-candle, data gaps and already-open skips are separate.', '']
        if scenario['selectivity'] is not None:
            for key, value in scenario['selectivity'].items():
                lines.append(f'- {key}: {json.dumps(value, ensure_ascii=False) if isinstance(value, dict) else display(value)}')
        else:
            lines.append('N/A: shared replay unavailable.')
        lines += ['', f'## Warnings — {name}', '']
        notes = list(scenario['warnings'])
        if scenario['aggregate'] is not None:
            notes += scenario['aggregate'].warnings
        for ticker, replay in scenario['independent'].items():
            notes += [f'Independent {ticker}: {warning}' for warning in replay.warnings]
        lines += ['- ' + warning for warning in dict.fromkeys(notes)] or ['None.']
    lines += ['', '## Data quality and failures', '',
              'Counts include warmup; requested usable rows cover only the trading range. Removed row dates, reasons, values and limits are preserved in data_validation.json. Unknown download counts on transport/schema failure remain N/A.',
              '', '| Ticker | Downloaded | Removed | Usable | Requested usable | Removal/failure evidence |',
              '| --- | ---: | ---: | ---: | ---: | --- |']
    for ticker in result.tickers:
        data = result.data_validation.get(ticker, {})
        evidence = [row['date'] + ': ' + row['reason'] for row in data.get('removed_rows', [])]
        evidence += [failure['stage'] + ': ' + failure['error'] for failure in result.failures.get(ticker, [])]
        values = [ticker, data.get('rows_downloaded'), data.get('rows_removed'), data.get('usable_rows'),
                  data.get('requested_usable_rows'), '; '.join(evidence) or 'None']
        lines.append('| ' + ' | '.join(display(v) for v in values) + ' |')
    lines += ['', '## Run warnings', ''] + (['- ' + warning for warning in result.warnings + chart_warnings] or ['None.'])
    lines += ['', '## Methodology and limitations', '',
              'This layer calls the same Backtest v1 engine for independent and shared replay; no second execution engine exists.',
              'A ticker failing fetch/validation or either independent scenario is explicitly excluded from both shared scenarios before shared replay. This is a data-safety rule, not performance selection. If a shared replay itself crosses an unknown candle while holding, that aggregate fails; no retrospective ticker pruning or fabricated liquidation.',
              'Fixed initial-capital risk sizing, cash cap including entry fees, one long position per ticker, no leverage/pyramiding/partial TP1 sale, next-open entry, stop-first ambiguity, ATR rebase at fill, and next-candle close-based trailing updates all remain unchanged.',
              'A removed session expires a pending entry; an open position crossing it fails. Stale endpoints remain marked rather than fabricated. Missing completely absent source dates still require a coverage/calendar audit.',
              'Yahoo quote OHLC is not a point-in-time corporate-action database; warmup seeds, current basket selection, splits/revisions, missing data and daily-candle ambiguity limit conclusions.',
              'Sharpe retains zero risk-free rate, net daily equity simple returns, sample standard deviation and sqrt(252); minimum 60 observations and nonzero volatility. CAGR retains the 365-day/252-observation gates. Warnings do not alter computed values.',
              'No claim of statistical significance, strategy profitability, or recommended parameter changes is made.', '', AUDIT]
    (directory / 'summary.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return directory
