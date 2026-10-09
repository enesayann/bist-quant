"""Annual report reuse and combined independent-year tables/visuals."""
from datetime import datetime
import json
from pathlib import Path
from uuid import uuid4

import pandas as pd

from bot.config import TR_TZ
from .multi_year import SCENARIOS, YEAR_METRICS
from .report import AUDIT, TRADE_COLUMNS, write_csv
from .validation import RANKING_RULE
from .validation_report import display, save_validation_report


def plot_multi_year(result, directory):
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
    except ImportError:
        return ['Combined charts skipped: optional matplotlib is not installed.']
    colors = {'realism': '#dc8124', 'baseline': '#2465a8'}
    for key, title, filename in [('total_return_pct', 'Independent yearly return (%) — 100,000 TL reset each year', 'yearly_returns.png'),
                                ('maximum_drawdown_pct', 'Independent yearly maximum drawdown (%)', 'yearly_drawdown.png')]:
        figure, axis = plt.subplots(figsize=(10, 4))
        for number, scenario in enumerate(SCENARIOS):
            rows = {r['year']: r for r in result.comparison if r['scenario'] == scenario}
            values = [rows[year][key] if rows[year][key] is not None else float('nan') for year in result.years]
            axis.bar([i + (number - .5) * .36 for i in range(len(result.years))], values,
                     width=.36, label=scenario, color=colors[scenario])
        axis.set_xticks(range(len(result.years)), list(map(str, result.years)))
        axis.set_title(title)
        axis.axhline(0, color='#666666', linewidth=.8)
        axis.grid(axis='y', alpha=.25)
        axis.legend()
        figure.tight_layout()
        figure.savefig(directory / filename, dpi=140)
        plt.close(figure)
    figure, axis = plt.subplots(figsize=(12, 4.5))
    for number, scenario in enumerate(SCENARIOS):
        rows = {r['ticker']: r for r in result.per_ticker if r['scenario'] == scenario and r['portfolio_mode'] == 'shared'}
        values = [rows[ticker]['cumulative_net_pnl_tl'] if rows[ticker]['cumulative_net_pnl_tl'] is not None else float('nan')
                  for ticker in result.tickers]
        axis.bar([i + (number - .5) * .36 for i in range(len(result.tickers))], values,
                 width=.36, label=scenario, color=colors[scenario])
    axis.set_xticks(range(len(result.tickers)), [t.replace('.IS', '') for t in result.tickers], rotation=30)
    axis.set_title('Sum of independent annual shared-portfolio ticker P&L (TL)')
    axis.axhline(0, color='#666666', linewidth=.8)
    axis.grid(axis='y', alpha=.25)
    axis.legend()
    figure.tight_layout()
    figure.savefig(directory / 'per_ticker_cumulative_pnl.png', dpi=140)
    plt.close(figure)
    if result.chained_view:
        figure, axis = plt.subplots(figsize=(10, 4.5))
        for scenario in SCENARIOS:
            rows = [r for r in result.chained_view if r['scenario'] == scenario]
            values = [100000] + [r['illustrated_end_tl'] if r['illustrated_end_tl'] is not None else float('nan') for r in rows]
            axis.plot(range(len(values)), values, marker='o', label=scenario, color=colors[scenario])
        axis.set_xticks(range(len(result.years) + 1), ['Initial'] + [f'{year} end' for year in result.years])
        axis.set_title('Secondary return-linked capital illustration (TL)')
        axis.text(.01, .02, 'No re-sizing or chained trade replay; primary annual portfolios reset to 100,000 TL.',
                  transform=axis.transAxes, fontsize=9)
        axis.grid(alpha=.25)
        axis.legend()
        figure.tight_layout()
        figure.savefig(directory / 'chained_capital.png', dpi=140)
        plt.close(figure)
    return []


def save_multi_year_report(result, output='backtest_results', run_id=None, charts=True):
    run_id = run_id or datetime.now(TR_TZ).strftime('%Y%m%d_%H%M%S') + '_multi_year_' + uuid4().hex[:8]
    if Path(run_id).name != run_id or run_id in ('.', '..') or '/' in run_id or '\\' in run_id:
        raise ValueError('run_id must be a single directory name')
    directory = Path(output) / run_id
    directory.mkdir(parents=True, exist_ok=False)
    annual_metadata, combined_trades, combined_equity, independent_trades, data_rows = {}, [], [], [], []
    for year in result.years:
        validation = result.annual[year]
        annual_dir = save_validation_report(validation, directory / 'years', str(year), charts=charts)
        annual_summary = annual_dir / 'summary.md'
        text = annual_summary.read_text('utf-8')
        preface = (f'Annual period: **{year}**. Primary scenario: **realism** (0.10% commission + 0.10% slippage per side). '
                   'Portfolio starts independently with **100,000 TL**; no prior-year capital or positions carry forward.\n\n')
        appendix = ['\n## Annual signal disposition totals\n',
                    '| Scenario | Valid signals | Executed entries | Skipped signals (all reasons) |',
                    '| --- | ---: | ---: | ---: |']
        for row in result.comparison:
            if row['year'] == year:
                appendix.append(f'| {row["scenario"]} | {display(row["valid_signals"])} | '
                                f'{display(row["executed_trades"])} | {display(row["skipped_signals"])} |')
        annual_summary.write_text(preface + text + '\n'.join(appendix) + '\n', encoding='utf-8')
        annual_metadata[str(year)] = {'start': validation.start, 'end': validation.end,
                                      'data_source': validation.data_source, 'failures': validation.failures,
                                      'input_data_sha256': validation.input_data_hashes,
                                      'data_validation': validation.data_validation,
                                      'annual_report': f'years/{year}/summary.md',
                                      'warnings': validation.warnings}
        for ticker in result.tickers:
            data = validation.data_validation.get(ticker, {})
            failures = validation.failures.get(ticker, [])
            data_rows.append({'year': year, 'ticker': ticker, 'status': 'failed' if failures else 'ok',
                              'failure': '; '.join(f['stage'] + ': ' + f['error'] for f in failures),
                              'rows_downloaded': data.get('rows_downloaded'), 'rows_removed': data.get('rows_removed'),
                              'usable_rows': data.get('usable_rows'), 'requested_rows_downloaded': data.get('requested_rows_downloaded'),
                              'requested_rows_removed': data.get('requested_rows_removed'), 'requested_usable_rows': data.get('requested_usable_rows'),
                              'removed_row_reasons': '; '.join(r['date'] + ': ' + r['reason'] for r in data.get('removed_rows', []))})
        for scenario in SCENARIOS:
            value = validation.scenarios[scenario]
            for replay in value['independent'].values():
                independent_trades.extend(dict(t, year=year, scenario=scenario) for t in replay.trades)
            aggregate = value['aggregate']
            if aggregate is not None:
                combined_trades.extend(dict(t, year=year, scenario=scenario) for t in aggregate.trades)
                combined_equity.extend(dict(row, year=year, scenario=scenario) for row in aggregate.equity.to_dict('records'))
    write_csv(directory / 'year_comparison.csv', result.comparison, list(result.comparison[0]))
    write_csv(directory / 'per_ticker_multi_year.csv', result.per_ticker, list(result.per_ticker[0]))
    write_csv(directory / 'combined_trades.csv', combined_trades, ['year', 'scenario'] + TRADE_COLUMNS)
    write_csv(directory / 'independent_combined_trades.csv', independent_trades, ['year', 'scenario'] + TRADE_COLUMNS)
    write_csv(directory / 'equity_curves.csv', combined_equity,
              ['year', 'scenario', 'date', 'phase', 'cash', 'market_value', 'equity', 'open_positions', 'drawdown_pct'])
    write_csv(directory / 'data_quality.csv', data_rows, list(data_rows[0]))
    cost_columns = ['year', 'matched_scenarios_available', 'matched_year_count', 'ending_capital_difference_tl',
                    'total_return_difference_pp', 'allocated_capital_return_difference_pp',
                    'baseline_gross_profit_tl', 'cost_drag_pct_of_gross_profit',
                    'realism_commissions_paid_tl', 'denominator']
    write_csv(directory / 'cost_drag.csv', result.cost_drag, cost_columns)
    if result.chained_view:
        write_csv(directory / 'chained_capital.csv', result.chained_view, list(result.chained_view[0]))
    chart_warnings = plot_multi_year(result, directory) if charts else []
    payload = {'years': result.years, 'requested_tickers': result.tickers, 'primary_scenario': 'realism',
               'method': 'Independent 100,000 TL annual portfolios; no inter-year capital/position carry.',
               'ranking_rule': RANKING_RULE, 'comparison': result.comparison, 'per_ticker': result.per_ticker,
               'stability': result.stability, 'cost_drag': result.cost_drag, 'chained_view': result.chained_view,
               'annual_metadata': annual_metadata, 'warnings': result.warnings + chart_warnings}
    (directory / 'multi_year.json').write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    lines = ['# Multi-Year Validation v1', '',
             f'Years: {", ".join(map(str, result.years))}. Fixed requested basket ({len(result.tickers)}): {", ".join(result.tickers)}.',
             '**Primary comparison: realism — 0.10% commission + 0.10% adverse slippage, each on entry and exit.**',
             'Each year starts independently with 100,000 TL; risk 1% of initial capital; maximum five positions. No capital or position carries to the next year.',
             'Technical-only, historical news/fundamentals neutral, next_open, stop_first, existing ATR stop/TP1/TP2/trailing and ingestion controls unchanged.',
             'Ranking: ' + RANKING_RULE, '',
             'Annual reports: ' + ', '.join(f'[{year}](years/{year}/summary.md)' for year in result.years) + '.', '']
    labels = [(key, key.replace('_', ' ')) for key in YEAR_METRICS] + [
        ('valid_signals', 'valid signals'), ('executed_trades', 'executed entries'), ('skipped_signals', 'skipped signals (all reasons)'),
        ('skipped_capital_or_concurrency', 'capital/concurrency skips'), ('status', 'coverage status'), ('participating_tickers', 'participating tickers')]
    for scenario in SCENARIOS:
        lines += [f'## Independent annual comparison — {scenario}', '',
                  '| Metric | ' + ' | '.join(map(str, result.years)) + ' |',
                  '| --- | ' + ' | '.join(['---:'] * len(result.years)) + ' |']
        rows = {r['year']: r for r in result.comparison if r['scenario'] == scenario}
        for key, label in labels:
            lines.append('| ' + label + ' | ' + ' | '.join(display(rows[year][key]) for year in result.years) + ' |')
        metrics = result.stability[scenario]
        lines += ['', f'## Descriptive stability — {scenario}', '',
                  'Summed annual P&L and pooled trade statistics describe independently funded trials; this is not one continuous three-year portfolio. Allocated capital is 100,000 TL per available year. Worst annual drawdown is not a continuous drawdown.',
                  '', '| Metric | Value |', '| --- | ---: |']
        stability_keys = ['coverage_complete', 'profitable_years', 'losing_years', 'flat_years', 'best_year', 'worst_year',
                          'average_yearly_return_pct', 'median_yearly_return_pct', 'yearly_return_sample_std_pp',
                          'yearly_return_range_pp', 'cumulative_net_pnl_tl', 'observed_net_pnl_tl', 'total_capital_allocated_tl',
                          'return_on_total_allocated_capital_pct', 'total_closed_trades', 'winning_trades', 'losing_trades',
                          'win_rate_pct', 'pooled_profit_factor', 'pooled_profit_factor_status', 'pooled_expectancy_tl',
                          'pooled_average_trade_return_pct', 'pooled_median_trade_return_pct', 'pooled_average_holding_days',
                          'worst_annual_drawdown_pct']
        for key in stability_keys:
            lines.append(f'| {key.replace("_", " ")} | {display(metrics[key])} |')
        lines += ['', f'## Per-ticker annual shared-portfolio results — {scenario}', '',
                  'Entries and net P&L contributions for the shared portfolio. Zero-trade years are explicit; failures are N/A, not zero. Independent single-ticker results are included separately in the CSV.', '',
                  '| Ticker | ' + ' | '.join(f'{year} entries / net TL' for year in result.years)
                  + ' | Total entries | Sum net TL | Positive years | Negative years | Zero-trade years |',
                  '| --- | ' + ' | '.join(['---:'] * (len(result.years) + 5)) + ' |']
        for row in result.per_ticker:
            if row['scenario'] != scenario or row['portfolio_mode'] != 'shared':
                continue
            values = [row['ticker']] + [display(row[f'{year}_trades']) + ' / ' + display(row[f'{year}_net_pnl_tl']) for year in result.years]
            values += [display(row['total_trades']), display(row['cumulative_net_pnl_tl']), display(row['profitable_years']),
                       display(row['losing_years']), row['zero_trade_years'] or 'None']
            lines.append('| ' + ' | '.join(values) + ' |')
        lines += ['', f'## Concentration — {scenario}', '',
                  'Signed ticker net P&L / observed total net P&L may be negative or exceed 100% when losses offset gains; zero total gives N/A.',
                  '', '| Ticker | Sum net TL | % total net P&L | % positive contribution | Complete coverage |',
                  '| --- | ---: | ---: | ---: | --- |']
        for row in metrics['per_ticker_concentration']:
            lines.append('| ' + ' | '.join(display(row[key]) for key in ('ticker', 'net_pnl_tl', 'pnl_share_pct',
                                                                          'positive_pnl_share_pct', 'coverage_complete')) + ' |')
        for key, label in [('strongest_positive_ticker', 'Largest positive contributor'), ('weakest_negative_ticker', 'Largest negative contributor')]:
            row = metrics[key]
            lines.append(label + ': ' + (f'{row["ticker"]}, {display(row["net_pnl_tl"])} TL.' if row else 'None.'))
        lines += ['', '| Year | Largest positive ticker contribution TL |', '| --- | ---: |']
        for year, row in metrics['largest_ticker_contribution_per_year'].items():
            lines.append(f'| {year} | ' + (f'{row["ticker"]}: {display(row["net_pnl_tl"])}' if row else 'N/A') + ' |')
        lines.append('Any ticker above 50% of total signed P&L: ' + (', '.join(metrics['tickers_above_50_pct_total_net_pnl']) or 'None') + '.')
        lines.append('')
    lines += ['## Cost drag: zero-cost reference minus realism', '',
              'Gross profit denominator = sum of positive gross P&L from baseline closed trades, not net P&L. Zero denominator gives N/A. Cost drag includes fees, slippage, and any existing fill/lot/target path effects; it is not merely the commission total.',
              'Combined ending-capital difference sums independently funded annual ending-equity differences. Combined return difference is the sum of annual percentage-point differences, not a compounded return.',
              'Combined return drag on total allocated capital (100,000 TL per matched year) is '
              + display(result.cost_drag[-1]['allocated_capital_return_difference_pp'])
              + ' percentage points. It is separate from the sum of yearly return differences.',
              '', '| Year | Ending-capital difference TL | Return difference pp | Baseline gross profit TL | Drag / gross profit % | Realism commissions TL |',
              '| --- | ---: | ---: | ---: | ---: | ---: |']
    for row in result.cost_drag:
        lines.append('| ' + ' | '.join(display(row[key]) for key in ('year', 'ending_capital_difference_tl', 'total_return_difference_pp',
                                                                    'baseline_gross_profit_tl', 'cost_drag_pct_of_gross_profit',
                                                                    'realism_commissions_paid_tl')) + ' |')
    if result.chained_view:
        lines += ['', '## Secondary chained-capital illustration only', '',
                  'Starting at 100,000 TL, multiply by each observed independent annual net-return factor. No trades are rerun or re-sized, so lot rounding, reserved cash and costs at a changed capital scale are not modeled. This is a visualization, not the primary analysis or an executed chained portfolio. A failed/partial year breaks the chain.',
                  '', '| Scenario | Year | Illustrated start TL | Illustrated end TL |', '| --- | --- | ---: | ---: |']
        for row in result.chained_view:
            lines.append('| ' + ' | '.join(display(row[key]) for key in ('scenario', 'year', 'illustrated_start_tl', 'illustrated_end_tl')) + ' |')
    lines += ['', '## Data quality by year/ticker', '',
              'Downloaded/removed/usable counts include that year\'s warmup; requested counts cover the annual trading period. Overlapping warmup windows are separate downloads, not unique market sessions.',
              'The existing 5% removal limit, hard corruption rejection, missing-session order expiry/open-position failure and explicit failed-ticker reporting are unchanged.',
              '', '| Year | Ticker | Status | Downloaded | Removed | Usable | Annual usable | Failure/removal reason |',
              '| --- | --- | --- | ---: | ---: | ---: | ---: | --- |']
    for row in data_rows:
        values = [row[key] for key in ('year', 'ticker', 'status', 'rows_downloaded', 'rows_removed', 'usable_rows', 'requested_usable_rows')]
        values.append(row['failure'] or row['removed_row_reasons'] or 'None')
        lines.append('| ' + ' | '.join(display(v) for v in values) + ' |')
    lines += ['', '## Warnings', ''] + ['- ' + warning for warning in result.warnings + chart_warnings]
    lines += ['', '## Methodology limits', '',
              'The primary shared portfolio resets cash/positions/risk sizing each year. Each annual indicator history begins with the existing 730-calendar-day warmup, ending at that year\'s boundary; no following year seeds an earlier decision.',
              'Per-year data qualifications and unsafe simulations follow the existing multi-ticker validation rules. Coverage differences are explicit; missing annual/ticker results are never silently substituted with zero.',
              'Year-to-year variability is the sample standard deviation of annual returns in percentage points (ddof=1), plus the observed range. With three years these are descriptive, not statistically significant.',
              'The fixed current basket, revised/split-adjusted Yahoo history, daily OHLC ordering, endpoint liquidation and warmup limitations remain. No profitability proof or parameter recommendation is made.', '', AUDIT]
    (directory / 'summary.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return directory
