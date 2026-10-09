"""Independent annual validation and descriptive comparisons; no execution code."""
from dataclasses import dataclass
import math

import numpy as np

from .execution import BacktestConfig
from .signals import signal_from_history
from .validation import VALIDATION_BASKET, run_validation


VALIDATION_YEARS = (2023, 2024, 2025)
SCENARIOS = ('realism', 'baseline')  # Primary first throughout combined reports.
YEAR_METRICS = ('total_trades', 'winning_trades', 'losing_trades', 'win_rate_pct',
                'ending_capital_tl', 'net_pnl_tl', 'total_return_pct', 'maximum_drawdown_pct',
                'profit_factor', 'profit_factor_status', 'expectancy_tl', 'expectancy_pct',
                'average_trade_return_pct', 'median_trade_return_pct', 'longest_losing_streak',
                'average_holding_days', 'sharpe_ratio', 'cagr_pct')


@dataclass
class MultiYearResult:
    years: list
    tickers: list
    annual: dict
    comparison: list
    per_ticker: list
    stability: dict
    cost_drag: list
    chained_view: list
    warnings: list


def yearly_comparison(year, validation, scenario):
    data = validation.scenarios[scenario]
    aggregate = data['aggregate']
    complete = aggregate is not None and len(aggregate.tickers) == len(validation.tickers)
    row = {'year': year, 'scenario': scenario,
           'status': 'complete' if complete else 'partial_basket' if aggregate is not None else 'aggregate_failed',
           'initial_capital_tl': 100000.0, 'requested_tickers': len(validation.tickers),
           'participating_tickers': len(aggregate.tickers) if aggregate else None,
           'failure': data['aggregate_failure']}
    row.update({key: aggregate.metrics[key] if aggregate else None for key in YEAR_METRICS})
    counts = data['selectivity']
    row.update({'valid_signals': counts['valid_signals'] if counts else None,
                'executed_trades': counts['executed_entries'] if counts else None,
                'skipped_signals': sum(d['status'] == 'skipped' for d in aggregate.entry_decisions) if aggregate else None,
                'skipped_capital_or_concurrency': counts['skipped_capital_or_concurrency'] if counts else None})
    return row


def ticker_comparison(annual, years, tickers):
    """Keep absent/failed years as None, explicitly separate observed subtotals."""
    rows = []
    for scenario in SCENARIOS:
        for mode in ('shared', 'independent'):
            for ticker in tickers:
                row = {'scenario': scenario, 'portfolio_mode': mode, 'ticker': ticker}
                available, zero_years = [], []
                for year in years:
                    source = next(r for r in annual[year].per_ticker
                                  if r['scenario'] == scenario and r['ticker'] == ticker)
                    status = source['shared_status'] if mode == 'shared' else source['status']
                    trades = source['shared_trade_count'] if mode == 'shared' else source['trade_count']
                    pnl = source['shared_net_pnl_tl'] if mode == 'shared' else source['net_pnl_tl']
                    row[f'{year}_status'] = status
                    row[f'{year}_trades'] = trades
                    row[f'{year}_net_pnl_tl'] = pnl
                    if trades is not None and pnl is not None:
                        available.append((year, trades, pnl))
                        if trades == 0:
                            zero_years.append(year)
                complete = len(available) == len(years)
                observed_trades = sum(t for _, t, _ in available) if available else None
                observed_pnl = sum(p for _, _, p in available) if available else None
                row.update({'coverage_complete': complete, 'observed_years': len(available),
                            'total_trades': observed_trades if complete else None,
                            'cumulative_net_pnl_tl': observed_pnl if complete else None,
                            'observed_trades': observed_trades, 'observed_net_pnl_tl': observed_pnl,
                            'profitable_years': sum(p > 0 for _, _, p in available),
                            'losing_years': sum(p < 0 for _, _, p in available),
                            'flat_years': sum(p == 0 for _, _, p in available),
                            'zero_trade_years': ','.join(map(str, zero_years))})
                rows.append(row)
    return rows


def cost_drag_for_year(year, validation):
    baseline = validation.scenarios['baseline']['aggregate']
    realism = validation.scenarios['realism']['aggregate']
    complete = baseline is not None and realism is not None
    gross_profit = sum(max(t['gross_pnl_tl'], 0) for t in baseline.trades) if baseline else None
    capital_drag = baseline.metrics['ending_capital_tl'] - realism.metrics['ending_capital_tl'] if complete else None
    fees = None
    if realism is not None:
        fees = (sum(d['entry_price'] * d['quantity'] * realism.config.commission_pct / 100
                    for d in realism.entry_decisions if d['status'] == 'executed')
                + sum(t['exit_commission_tl'] for t in realism.trades))
    return {'year': year, 'matched_scenarios_available': complete,
            'ending_capital_difference_tl': capital_drag,
            'total_return_difference_pp': baseline.metrics['total_return_pct'] - realism.metrics['total_return_pct'] if complete else None,
            'allocated_capital_return_difference_pp': capital_drag / 100000 * 100 if complete else None,
            'baseline_gross_profit_tl': gross_profit,
            'cost_drag_pct_of_gross_profit': capital_drag / gross_profit * 100 if complete and gross_profit else None,
            'realism_commissions_paid_tl': fees,
            'denominator': 'Sum of positive gross P&L from baseline closed trades; not net profit.'}


def chained_capital_view(comparison, years):
    """Return-link annual outcomes for illustration only. No trades are re-sized."""
    rows = []
    for scenario in SCENARIOS:
        capital = 100000.0
        for year in years:
            source = next(r for r in comparison if r['year'] == year and r['scenario'] == scenario)
            start = capital
            capital = (start * (1 + source['total_return_pct'] / 100)
                       if start is not None and source['total_return_pct'] is not None and source['status'] == 'complete' else None)
            rows.append({'scenario': scenario, 'year': year, 'illustrated_start_tl': start,
                         'illustrated_end_tl': capital, 'independent_yearly_return_pct': source['total_return_pct'],
                         'year_status': source['status'], 'method': 'return_linked_illustration_no_replay'})
    return rows


def descriptive_stability(annual, years, comparison, ticker_rows, scenario):
    available = [r for r in comparison if r['scenario'] == scenario and r['net_pnl_tl'] is not None]
    replays = [annual[r['year']].scenarios[scenario]['aggregate'] for r in available]
    trades = [t for replay in replays for t in replay.trades]
    pnl = [t['net_pnl_tl'] for t in trades]
    returns = [r['total_return_pct'] for r in available]
    trade_returns = [t['net_return_pct'] for t in trades]
    winners, losses = sum(p > 0 for p in pnl), sum(p < 0 for p in pnl)
    gross_wins, gross_losses = sum(max(p, 0) for p in pnl), -sum(min(p, 0) for p in pnl)
    complete = len(available) == len(years) and all(r['status'] == 'complete' for r in available)
    net_total = sum(r['net_pnl_tl'] for r in available) if available else None
    allocated = len(available) * 100000.0
    contributors = []
    source_rows = [r for r in ticker_rows if r['scenario'] == scenario and r['portfolio_mode'] == 'shared']
    positive_total = sum(max(r['observed_net_pnl_tl'] or 0, 0) for r in source_rows)
    for row in source_rows:
        value = row['observed_net_pnl_tl']
        contributors.append({'ticker': row['ticker'], 'net_pnl_tl': value,
                             'coverage_complete': row['coverage_complete'], 'observed_years': row['observed_years'],
                             'pnl_share_pct': value / net_total * 100 if value is not None and net_total is not None and abs(net_total) > 1e-8 else None,
                             'positive_pnl_share_pct': max(value, 0) / positive_total * 100 if value is not None and positive_total else None})
    if net_total is not None and not math.isclose(sum(r['net_pnl_tl'] or 0 for r in contributors), net_total,
                                                rel_tol=1e-9, abs_tol=1e-7):
        raise ValueError('Multi-year ticker contributions do not reconcile with observed yearly portfolio P&L')
    positive = [r for r in contributors if r['net_pnl_tl'] is not None and r['net_pnl_tl'] > 0]
    negative = [r for r in contributors if r['net_pnl_tl'] is not None and r['net_pnl_tl'] < 0]
    largest_positive = min(positive, key=lambda r: (-r['net_pnl_tl'], r['ticker'])) if positive else None
    largest_negative = min(negative, key=lambda r: (r['net_pnl_tl'], r['ticker'])) if negative else None
    largest_each_year = {str(year): annual[year].scenarios[scenario]['concentration']['largest_positive_contributor']
                         if annual[year].scenarios[scenario]['concentration'] else None for year in years}
    return {'scenario': scenario, 'coverage_complete': complete,
            'available_years': [r['year'] for r in available], 'requested_years': list(years),
            'profitable_years': sum(r['net_pnl_tl'] > 0 for r in available),
            'losing_years': sum(r['net_pnl_tl'] < 0 for r in available),
            'flat_years': sum(r['net_pnl_tl'] == 0 for r in available),
            'best_year': min(available, key=lambda r: (-r['total_return_pct'], r['year']))['year'] if available else None,
            'worst_year': min(available, key=lambda r: (r['total_return_pct'], r['year']))['year'] if available else None,
            'average_yearly_return_pct': float(np.mean(returns)) if returns else None,
            'median_yearly_return_pct': float(np.median(returns)) if returns else None,
            'yearly_return_sample_std_pp': float(np.std(returns, ddof=1)) if len(returns) > 1 else None,
            'yearly_return_range_pp': max(returns) - min(returns) if returns else None,
            'cumulative_net_pnl_tl': net_total if complete else None,
            'observed_net_pnl_tl': net_total, 'total_capital_allocated_tl': allocated,
            'return_on_total_allocated_capital_pct': net_total / allocated * 100 if net_total is not None and allocated else None,
            'total_closed_trades': len(trades), 'winning_trades': winners, 'losing_trades': losses,
            'win_rate_pct': winners / len(trades) * 100 if trades else None,
            'pooled_profit_factor': gross_wins / gross_losses if gross_losses else None,
            'pooled_profit_factor_status': 'finite' if gross_losses else 'no_losses' if winners else 'no_trades_or_wins',
            'pooled_expectancy_tl': float(np.mean(pnl)) if pnl else None,
            'pooled_average_trade_return_pct': float(np.mean(trade_returns)) if trade_returns else None,
            'pooled_median_trade_return_pct': float(np.median(trade_returns)) if trade_returns else None,
            'pooled_average_holding_days': float(np.mean([t['holding_days'] for t in trades])) if trades else None,
            'worst_annual_drawdown_pct': max(r['maximum_drawdown_pct'] for r in available) if available else None,
            'largest_ticker_contribution_per_year': largest_each_year, 'per_ticker_concentration': contributors,
            'strongest_positive_ticker': largest_positive, 'weakest_negative_ticker': largest_negative,
            'tickers_above_50_pct_total_net_pnl': [r['ticker'] for r in contributors if r['pnl_share_pct'] is not None and r['pnl_share_pct'] > 50]}


def stability_warnings(stability, comparison, ticker_rows):
    warnings = []
    for scenario, metrics in stability.items():
        prefix = scenario + ': '
        if not metrics['coverage_complete']:
            warnings.append(prefix + 'incomplete year/basket coverage; full cumulative P&L is N/A, observed subtotals are separate.')
        if metrics['total_closed_trades'] < 30:
            warnings.append(prefix + f'fewer than 30 closed trades across years ({metrics["total_closed_trades"]}).')
        if metrics['profitable_years'] == 1:
            warnings.append(prefix + 'only one observed year has positive net P&L.')
        if metrics['pooled_profit_factor'] is None:
            warnings.append(prefix + 'pooled profit factor undefined (' + metrics['pooled_profit_factor_status'] + ').')
        if metrics['tickers_above_50_pct_total_net_pnl']:
            warnings.append(prefix + 'ticker contribution exceeds 50% of total signed net P&L: '
                            + ', '.join(metrics['tickers_above_50_pct_total_net_pnl']) + '; not statistically significant.')
        if metrics['observed_net_pnl_tl'] is not None and metrics['observed_net_pnl_tl'] <= 0:
            warnings.append(prefix + 'total observed net P&L is nonpositive; signed contribution percentages need denominator context.')
        for row in comparison:
            if row['scenario'] == scenario and row['total_trades'] == 0:
                warnings.append(prefix + f'{row["year"]} has zero closed trades.')
            if row['scenario'] == scenario and row['profit_factor'] is None:
                warnings.append(prefix + f'{row["year"]} profit factor unavailable/undefined ({row["profit_factor_status"]}).')
        for row in ticker_rows:
            if row['scenario'] == scenario and row['portfolio_mode'] == 'shared':
                if row['observed_trades'] is not None and row['observed_trades'] < 3:
                    warnings.append(prefix + f'{row["ticker"]} has fewer than 3 observed total trades ({row["observed_trades"]}).')
                if row['zero_trade_years']:
                    warnings.append(prefix + f'{row["ticker"]} zero-trade years: {row["zero_trade_years"]}.')
    warnings.append('Three annual observations are descriptive only; no statistical significance or regime-performance proof is claimed.')
    return warnings


def run_multi_year(*, provider=None, frames_by_year=None, years=VALIDATION_YEARS,
                   tickers=VALIDATION_BASKET, signal_generator=signal_from_history,
                   include_chained_view=True, progress=None):
    if (provider is None) == (frames_by_year is None):
        raise ValueError('Provide exactly one of provider or frames_by_year')
    years = list(years)
    if not years or years != sorted(set(years)) or any(isinstance(y, bool) or not isinstance(y, int) for y in years):
        raise ValueError('Expected distinct integer years in chronological order')
    annual = {}
    for year in years:
        if progress:
            progress(f'{year}: starting independent 100,000 TL portfolio; fixed basket, both cost scenarios.')
        # A NEW immutable fixed configuration each year. No prior result is
        # ever used as a following year's capital, scores or indicator history.
        settings = BacktestConfig(initial_capital=100000.0, risk_per_trade=.01, max_positions=5,
                                  execution_model='next_open', intrabar_policy='stop_first')
        inputs = {'provider': provider} if provider is not None else {'frames': frames_by_year.get(year, {})}
        annual[year] = run_validation(**inputs, start=f'{year}-01-01', end=f'{year}-12-31',
                                      tickers=tickers, config=settings, realism_commission_pct=.10,
                                      realism_slippage_pct=.10, warmup_days=730, signal_generator=signal_generator)
        if progress:
            result = annual[year].scenarios['realism']['aggregate']
            progress(f'{year}: realism replay ' + (f'complete; {result.metrics["total_trades"]} closed trades.'
                                                  if result is not None else 'FAILED; see explicit failure report.'))
    tickers = annual[years[0]].tickers
    comparison = [yearly_comparison(year, annual[year], scenario) for scenario in SCENARIOS for year in years]
    per_ticker = ticker_comparison(annual, years, tickers)
    stability = {scenario: descriptive_stability(annual, years, comparison, per_ticker, scenario) for scenario in SCENARIOS}
    cost_drag = [cost_drag_for_year(year, annual[year]) for year in years]
    matched = [r for r in cost_drag if r['matched_scenarios_available']]
    denominator = sum(r['baseline_gross_profit_tl'] for r in matched)
    drag = sum(r['ending_capital_difference_tl'] for r in matched)
    cost_drag.append({'year': 'combined', 'matched_scenarios_available': len(matched) == len(years),
                      'matched_year_count': len(matched),
                      'ending_capital_difference_tl': drag if matched else None,
                      'total_return_difference_pp': sum(r['total_return_difference_pp'] for r in matched) if matched else None,
                      'allocated_capital_return_difference_pp': drag / (len(matched) * 100000) * 100 if matched else None,
                      'baseline_gross_profit_tl': denominator if matched else None,
                      'cost_drag_pct_of_gross_profit': drag / denominator * 100 if denominator else None,
                      'realism_commissions_paid_tl': sum(r['realism_commissions_paid_tl'] for r in matched) if matched else None,
                      'denominator': 'Sum of positive gross P&L from matched baseline closed trades; combined ending difference sums independently funded annual outcomes.'})
    warnings = stability_warnings(stability, comparison, per_ticker)
    warnings += [f'{year}: {warning}' for year in years for warning in annual[year].warnings]
    return MultiYearResult(years, tickers, annual, comparison, per_ticker, stability, cost_drag,
                           chained_capital_view(comparison, years) if include_chained_view else [], warnings)
