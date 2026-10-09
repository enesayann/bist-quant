"""Fixed-basket observation using the existing backtest engine, never optimization."""
from copy import deepcopy
from dataclasses import dataclass, replace
from datetime import timedelta
from hashlib import sha256
import math

import pandas as pd
import requests

from .data import normalize_ticker
from .engine import run_backtest
from .execution import BacktestConfig
from .signals import signal_from_history


VALIDATION_BASKET = ('ASELS.IS', 'THYAO.IS', 'TUPRS.IS', 'BIMAS.IS', 'EREGL.IS',
                     'KCHOL.IS', 'GARAN.IS', 'SISE.IS', 'FROTO.IS', 'TCELL.IS')
RANKING_RULE = ('Descending signal confidence, then technical_score, then final_score; '
                'ascending ticker symbol breaks ties. Only completed signal-candle values are used. '
                'Cash is reserved before any intraday exits; rejected orders expire.')
METRIC_COLUMNS = ['winning_trades', 'losing_trades', 'win_rate_pct', 'net_pnl_tl',
                  'total_return_pct', 'maximum_drawdown_pct', 'profit_factor', 'profit_factor_status',
                  'expectancy_tl', 'expectancy_pct', 'average_trade_return_pct', 'median_trade_return_pct',
                  'best_trade_pct', 'worst_trade_pct', 'average_holding_days']
PER_TICKER_COLUMNS = ['scenario', 'ticker', 'status', 'failure', 'shared_status',
                      'rows_downloaded', 'rows_removed', 'usable_rows', 'requested_usable_rows',
                      'removed_row_reasons', 'trade_count'] + METRIC_COLUMNS + [
                      'shared_trade_count', 'shared_closed_trades', 'shared_net_pnl_tl',
                      'shared_return_contribution_pct', 'pnl_share_pct', 'trade_share_pct']


@dataclass
class ValidationResult:
    start: str
    end: str
    tickers: list
    scenarios: dict
    failures: dict
    data_validation: dict
    per_ticker: list
    warnings: list
    input_data_hashes: dict
    data_source: str = 'in_memory'


def concentration_analysis(result):
    """Shared marked net P&L contribution, including unclosed entry costs.

    Signed shares can be negative or >100% when losses offset gains. A zero
    net denominator yields None; positive-contribution share is also reported.
    """
    pnl = dict.fromkeys(result.tickers, 0.0)
    counts = dict.fromkeys(result.tickers, 0)
    closed = dict.fromkeys(result.tickers, 0)
    for trade in result.trades:
        pnl[trade['ticker']] += trade['net_pnl_tl']
        closed[trade['ticker']] += 1
    for position in result.open_positions:
        pnl[position['ticker']] += ((position['last_close'] - position['entry_price']) * position['quantity']
                                     - position['entry_commission_tl'])
    for decision in result.entry_decisions:
        if decision['status'] == 'executed':
            counts[decision['ticker']] += 1
    total = sum(pnl.values())
    if not math.isclose(total, result.metrics['net_pnl_tl'], rel_tol=1e-9, abs_tol=1e-7):
        raise ValueError('Shared per-ticker P&L does not reconcile with final portfolio equity')
    total_trades = sum(counts.values())
    positive_total = sum(max(value, 0) for value in pnl.values())
    rows = [{'ticker': ticker, 'net_pnl_tl': value, 'executed_trades': counts[ticker],
             'closed_trades': closed[ticker],
             'pnl_share_pct': value / total * 100 if abs(total) > 1e-8 else None,
             'positive_pnl_share_pct': max(value, 0) / positive_total * 100 if positive_total else None,
             'trade_share_pct': counts[ticker] / total_trades * 100 if total_trades else None}
            for ticker, value in sorted(pnl.items())]
    positive = [row for row in rows if row['net_pnl_tl'] > 0]
    negative = [row for row in rows if row['net_pnl_tl'] < 0]
    largest_positive = min(positive, key=lambda row: (-row['net_pnl_tl'], row['ticker'])) if positive else None
    largest_negative = min(negative, key=lambda row: (row['net_pnl_tl'], row['ticker'])) if negative else None
    dominant = [row['ticker'] for row in rows if row['pnl_share_pct'] is not None and row['pnl_share_pct'] > 50]
    return {'total_net_pnl_tl': total, 'total_executed_trades': total_trades, 'per_ticker': rows,
            'largest_positive_contributor': largest_positive, 'largest_negative_contributor': largest_negative,
            'tickers_above_50_pct_net_pnl': dominant,
            'one_ticker_above_50_pct_net_pnl': bool(dominant),
            'share_definition': 'Signed ticker net P&L / shared total net P&L; undefined when total is zero.'}


def validation_warnings(aggregate, independent, tickers, concentration):
    warnings = []
    if aggregate is None:
        warnings.append('Shared portfolio unavailable; no aggregate result was fabricated.')
    else:
        metrics = aggregate.metrics
        if metrics['total_trades'] < 30:
            warnings.append(f'Shared portfolio has fewer than 30 closed trades ({metrics["total_trades"]}).')
        if metrics['losing_trades'] == 0:
            warnings.append('Shared portfolio has no losing closed trades; this does not establish reliability.')
        if metrics['profit_factor'] is None:
            warnings.append(f'Shared profit factor is undefined ({metrics["profit_factor_status"]}).')
        if metrics['sharpe_ratio'] is None or metrics['total_trades'] < 30:
            warnings.append('Sample is too small for a reliable Sharpe interpretation; existing metric rules are unchanged.')
        if metrics['cagr_pct'] is None:
            warnings.append('CAGR sample conditions are not met (365 calendar days and 252 close observations required).')
        if aggregate.open_positions:
            warnings.append('Unclosed positions remain at stale marks; contribution includes marked P&L and entry fees.')
        if concentration['tickers_above_50_pct_net_pnl']:
            warnings.append('Ticker(s) exceed 50% of signed shared net P&L: '
                            + ', '.join(concentration['tickers_above_50_pct_net_pnl'])
                            + '. This is descriptive, not statistically significant.')
        if concentration['total_net_pnl_tl'] <= 0:
            warnings.append('Total net P&L is nonpositive; signed contribution percentages need their denominator context.')
    for ticker in tickers:
        result = independent.get(ticker)
        if result is None:
            continue
        metrics = result.metrics
        if metrics['total_trades'] == 0:
            warnings.append(f'{ticker}: zero independent trades; ticker remains in the report.')
        if metrics['total_trades'] < 3:
            warnings.append(f'{ticker}: fewer than 3 independent trades ({metrics["total_trades"]}).')
        if metrics['losing_trades'] == 0:
            warnings.append(f'{ticker}: no independent losing trades.')
        if metrics['profit_factor'] is None:
            warnings.append(f'{ticker}: independent profit factor undefined ({metrics["profit_factor_status"]}).')
        if aggregate is not None and ticker in aggregate.tickers:
            row = next(r for r in concentration['per_ticker'] if r['ticker'] == ticker)
            if row['executed_trades'] == 0:
                warnings.append(f'{ticker}: zero shared-portfolio entries.')
    return warnings


def run_validation(*, frames=None, provider=None, start='2025-01-01', end='2025-12-31',
                   tickers=VALIDATION_BASKET, config=None, realism_commission_pct=.10,
                   realism_slippage_pct=.10, warmup_days=730, signal_generator=signal_from_history):
    """Fetch once; independent qualification then two shared replays.

    A ticker unsafe in either independent scenario is excluded from BOTH shared
    scenarios, with explicit failure evidence. A shared replay with unknown
    position outcomes aborts that aggregate; it is never retrospectively pruned.
    """
    if (frames is None) == (provider is None):
        raise ValueError('Provide exactly one of frames or provider')
    tickers = [normalize_ticker(ticker) for ticker in tickers]
    if not tickers or len(set(tickers)) != len(tickers):
        raise ValueError('Basket must contain distinct tickers')
    first, last = pd.Timestamp(start), pd.Timestamp(end)
    if first > last or first.tz is not None or last.tz is not None or warmup_days < 0:
        raise ValueError('Invalid validation range or warmup')
    config = config or BacktestConfig(max_positions=5)
    if config.execution_model != 'next_open' or config.intrabar_policy != 'stop_first':
        raise ValueError('Validation v1 preserves next_open and stop_first assumptions')
    configs = {'baseline': replace(config, commission_pct=0, slippage_pct=0),
               'realism': replace(config, commission_pct=realism_commission_pct, slippage_pct=realism_slippage_pct)}
    loaded, failures, audit = {}, {}, {}
    independent = {scenario: {} for scenario in configs}
    caught = (ValueError, OSError, requests.RequestException)

    def record_failure(ticker, stage, error, frame=None):
        failures.setdefault(ticker, []).append({'stage': stage, 'error': str(error)})
        details = getattr(error, 'data_validation', None)
        if details is None and frame is not None:
            details = frame.attrs.get('validation')
        if details is not None:
            audit[ticker] = deepcopy(details)

    for ticker in tickers:
        try:
            if frames is None:
                frame = provider.fetch(ticker, (first.date() - timedelta(days=warmup_days)).isoformat(), str(last.date()))
            else:
                if ticker not in frames:
                    raise ValueError(f'{ticker}: missing input data')
                frame = frames[ticker]
            if not isinstance(frame, pd.DataFrame):
                raise ValueError(f'{ticker}: input must be a historical DataFrame')
            loaded[ticker] = frame
        except caught as error:
            record_failure(ticker, 'fetch', error)
            continue
        for scenario, settings in configs.items():
            try:
                result = run_backtest({ticker: frame}, str(first.date()), str(last.date()), settings, signal_generator)
                independent[scenario][ticker] = result
                audit[ticker] = deepcopy(result.data_validation[0])
            except caught as error:
                record_failure(ticker, scenario + '_independent_replay', error, frame)
    common = {ticker: frame for ticker, frame in loaded.items() if ticker not in failures}
    scenarios, rows = {}, []
    global_warnings = [f'{ticker} failed: ' + '; '.join(f'{f["stage"]}: {f["error"]}' for f in details)
                       for ticker, details in failures.items()]
    if failures:
        global_warnings.append('Incomplete basket: failed tickers are excluded from both shared scenarios; '
                               'results cover the same safely qualified subset and not all requested tickers.')
    for scenario, settings in configs.items():
        aggregate, aggregate_failure = None, None
        try:
            if not common:
                raise ValueError('No safely qualified tickers; shared portfolio not run')
            aggregate = run_backtest(common, str(first.date()), str(last.date()), settings, signal_generator,
                                     allocation_policy='score_confidence')
        except caught as error:
            aggregate_failure = str(error)
        concentration = concentration_analysis(aggregate) if aggregate is not None else None
        notes = validation_warnings(aggregate, independent[scenario], tickers, concentration)
        if aggregate_failure:
            notes.append('Shared replay failed: ' + aggregate_failure + '; no partial equity or forced exit was invented.')
        selectivity = dict(aggregate.selectivity) if aggregate is not None else None
        if selectivity is not None:
            selectivity['average_trades_per_requested_ticker'] = selectivity['executed_entries'] / len(tickers)
            selectivity['average_trades_per_participating_ticker'] = selectivity['executed_entries'] / len(common)
            selectivity['requested_ticker_count'] = len(tickers)
            selectivity['participating_ticker_count'] = len(common)
            selectivity['signal_rate_pct'] = (selectivity['valid_signals'] / selectivity['ticker_days_evaluated'] * 100
                                              if selectivity['ticker_days_evaluated'] else None)
        scenarios[scenario] = {'config': settings, 'independent': independent[scenario],
                               'aggregate': aggregate, 'aggregate_failure': aggregate_failure,
                               'concentration': concentration, 'selectivity': selectivity, 'warnings': notes}
        contribution = {r['ticker']: r for r in concentration['per_ticker']} if concentration else {}
        for ticker in tickers:
            result = independent[scenario].get(ticker)
            data = audit.get(ticker, {})
            shared = contribution.get(ticker)
            row = {'scenario': scenario, 'ticker': ticker, 'status': 'ok' if result else 'failed',
                   'failure': '; '.join(f'{f["stage"]}: {f["error"]}' for f in failures.get(ticker, [])),
                   'shared_status': 'excluded' if ticker in failures else 'ok' if aggregate else 'aggregate_failed',
                   'rows_downloaded': data.get('rows_downloaded'), 'rows_removed': data.get('rows_removed'),
                   'usable_rows': data.get('usable_rows'), 'requested_usable_rows': data.get('requested_usable_rows'),
                   'removed_row_reasons': '; '.join(r['date'] + ': ' + r['reason'] for r in data.get('removed_rows', [])),
                   'trade_count': result.metrics['total_trades'] if result else None}
            row.update({key: result.metrics[key] if result else None for key in METRIC_COLUMNS})
            row.update({'shared_trade_count': shared['executed_trades'] if shared else None,
                        'shared_closed_trades': shared['closed_trades'] if shared else None,
                        'shared_net_pnl_tl': shared['net_pnl_tl'] if shared else None,
                        'shared_return_contribution_pct': shared['net_pnl_tl'] / settings.initial_capital * 100 if shared else None,
                        'pnl_share_pct': shared['pnl_share_pct'] if shared else None,
                        'trade_share_pct': shared['trade_share_pct'] if shared else None})
            rows.append(row)
    fingerprints = {ticker: sha256(frame.to_csv().encode('utf-8')).hexdigest() for ticker, frame in loaded.items()}
    return ValidationResult(str(first.date()), str(last.date()), tickers, scenarios, failures, audit, rows,
                            global_warnings, fingerprints)
