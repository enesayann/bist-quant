"""Synchronous portfolio replay: opens, intraday exits, then close signals."""
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Callable

import pandas as pd

from .data import MAX_REMOVED_FRACTION, validate_frame
from bot.market_data import MarketDataError
from bot.config import MIN_VERI_UZUNLUGU
from .execution import BacktestConfig, close_position, open_position, process_candle
from .metrics import calculate_metrics
from .signals import prepare_indicators, signal_from_history


@dataclass
class BacktestResult:
    config: BacktestConfig
    start: str
    end: str
    tickers: list
    trades: list
    signals: list
    equity: pd.DataFrame
    metrics: dict
    warnings: list
    open_positions: list
    data_source: str = 'in_memory'
    data_validation: list = field(default_factory=list)
    allocation_policy: str = 'alphabetical'
    entry_decisions: list = field(default_factory=list)
    selectivity: dict = field(default_factory=dict)


def run_backtest(frames, start, end, config=None, signal_generator: Callable = signal_from_history,
                 *, allocation_policy='alphabetical'):
    """Frames may include warmup before start; trading and signals may not.

    Injecting a signal generator supports isolated, offline execution tests.
    It is always given a prefix, never the full frame or future candles.
    """
    config = config or BacktestConfig()
    if allocation_policy not in ('alphabetical', 'score_confidence'):
        raise ValueError('Unknown entry allocation policy')
    if allocation_policy == 'score_confidence' and config.execution_model != 'next_open':
        raise ValueError('Score/confidence allocation requires next_open execution')
    start_at, end_at = pd.Timestamp(start), pd.Timestamp(end)
    if start_at > end_at or start_at.tz is not None or end_at.tz is not None:
        raise ValueError('Expected ordered, timezone-free start/end dates')
    if not frames:
        raise ValueError('At least one ticker is required')
    prepared = {ticker: prepare_indicators(validate_frame(frame).loc[:end_at])
                for ticker, frame in sorted(frames.items())}
    validation, missing_dates = [], {}
    for ticker, frame in sorted(frames.items()):
        audit = deepcopy(frame.attrs.get('validation', {
            'ticker': ticker, 'rows_downloaded': len(frame), 'rows_removed': 0,
            'usable_rows': len(frame), 'removed_rows': [], 'warnings': [],
            'max_removed_fraction': MAX_REMOVED_FRACTION}))
        downloaded = frame.attrs.get('downloaded_dates', [str(d.date()) for d in frame.index])
        audit['requested_rows_downloaded'] = sum(start_at <= pd.Timestamp(d) <= end_at for d in downloaded)
        audit['requested_rows_removed'] = sum(start_at <= pd.Timestamp(row['date']) <= end_at
                                               for row in audit['removed_rows'])
        audit['requested_usable_rows'] = len(prepared[ticker].loc[start_at:end_at])
        if (audit['requested_rows_downloaded'] and audit['requested_rows_removed'] /
                audit['requested_rows_downloaded'] > audit['max_removed_fraction']):
            error = MarketDataError(f'{ticker}: too much of requested period is invalid: '
                                    f'{audit["requested_rows_removed"]}/{audit["requested_rows_downloaded"]} rows removed; '
                                    f'maximum {audit["max_removed_fraction"]:.0%}')
            error.data_validation = audit
            raise error
        validation.append(audit)
        missing_dates[ticker] = sorted({pd.Timestamp(row['date']) for row in audit['removed_rows']
                                        if row['category'] != 'duplicate'
                                        and pd.Timestamp(row['date']) not in prepared[ticker].index})
    dates = sorted(set().union(*(set(df.loc[start_at:end_at].index) for df in prepared.values())))
    if not dates:
        raise ValueError('No candles in requested date range')
    cash = config.initial_capital
    positions, pending, last_close = {}, {}, {}
    trades, signals, warnings = [], [], []
    decisions = []
    evaluated_days = signal_ready_days = 0

    def decision(signal, day, status, reason, position=None):
        decisions.append({'ticker': signal.ticker, 'signal_date': signal.signal_date,
                          'attempt_date': day, 'status': status, 'reason': reason,
                          'confidence': signal.confidence, 'technical_score': signal.technical_score,
                          'final_score': signal.final_score,
                          'quantity': position.quantity if position else None,
                          'entry_price': position.entry_price if position else None})

    def ranking(ticker):
        signal = pending[ticker]
        return (-signal.confidence, -signal.technical_score, -signal.final_score, ticker)
    warnings.extend(warning for audit in validation for warning in audit['warnings'])
    # Include initial equity so first-entry fees/losses appear in drawdown.
    curve = [{'date': start_at.date().isoformat(), 'cash': cash, 'market_value': 0.0,
              'equity': cash, 'open_positions': 0, 'phase': 'initial'}]
    for ticker, df in prepared.items():
        if len(df.loc[:start_at]) < 200:
            warnings.append(f'{ticker}: fewer than 200 warmup candles at start; EMA200 is gated by live minimums.')
        if df.loc[start_at:end_at].empty:
            warnings.append(f'{ticker}: no candles inside the trading range.')
    for date in dates:
        day = date.date().isoformat()
        candles = {ticker: df.loc[date] for ticker, df in prepared.items() if date in df.index}
        # A known missing candle while holding can hide a stop/target touch.
        # Fail instead of implicitly pretending the position survived it.
        for ticker, position in positions.items():
            gaps = [d for d in missing_dates[ticker] if pd.Timestamp(position.entry_date) <= d <= date]
            if gaps:
                raise MarketDataError(f'{ticker}: cannot simulate an open position across removed candle(s): '
                                      + ', '.join(d.date().isoformat() for d in gaps))
        # Reserve cash for all opening fills before allowing intraday exits.
        # Validation can rank STORED completed-candle scores. No information
        # from the entry candle, another ticker's future, or portfolio P&L.
        candidates = [ticker for ticker in candles if ticker in pending]
        candidates.sort(key=ranking if allocation_policy == 'score_confidence' else None)
        for ticker in candidates:
            signal = pending.pop(ticker)
            gaps = [d for d in missing_dates[ticker] if pd.Timestamp(signal.signal_date) < d <= date]
            if gaps:
                warnings.append(f'{ticker} {day}: entry skipped; next source candle was removed on '
                                + ', '.join(d.date().isoformat() for d in gaps) + '; order not deferred.')
                decision(signal, day, 'skipped', 'removed_candle')
                continue
            opening = float(candles[ticker].Open)
            if pd.isna(opening):
                warnings.append(f'{ticker} {day}: entry skipped; next candle Open is missing.')
                decision(signal, day, 'skipped', 'missing_open')
                continue
            if len(positions) >= config.max_positions:
                warnings.append(f'{ticker} {day}: entry skipped; maximum positions reached.')
                decision(signal, day, 'skipped', 'concurrency')
                continue
            position = open_position(signal, day, opening, cash, config)
            if position is None:
                warnings.append(f'{ticker} {day}: entry skipped; invalid levels or insufficient cash/risk lot.')
                nominal = open_position(signal, day, opening, config.initial_capital, config)
                decision(signal, day, 'skipped', 'capital' if nominal is not None else 'invalid_levels_or_risk_lot')
                continue
            cash -= position.entry_price * position.quantity + position.entry_commission
            positions[ticker] = position
            decision(signal, day, 'executed', 'next_open', position)
        for ticker in sorted(candles):
            candle = candles[ticker]
            last_close[ticker] = float(candle.Close)
            if ticker not in positions:
                continue
            outcome = process_candle(positions[ticker], candle, config)
            if outcome:
                trade, proceeds = close_position(positions.pop(ticker), day, *outcome, config)
                trades.append(trade)
                cash += proceeds
        # Liquidate only at the portfolio boundary; missing future rows must
        # not cause an earlier exit freeing cash for other tickers.
        for ticker in sorted(list(positions)):
            if date == dates[-1]:
                # Includes positions filled on this final usable candle. Do
                # not liquidate early when a later requested candle was lost.
                gaps = [d for d in missing_dates[ticker]
                        if pd.Timestamp(positions[ticker].entry_date) <= d <= end_at]
                if gaps:
                    raise MarketDataError(f'{ticker}: cannot simulate an open position across removed candle(s): '
                                          + ', '.join(d.date().isoformat() for d in gaps))
            if date == dates[-1] and ticker in candles:
                trade, proceeds = close_position(positions.pop(ticker), day, last_close[ticker], 'END_OF_DATA', config)
                trades.append(trade)
                cash += proceeds
                warnings.append(f'{ticker} {day}: final-candle liquidation at Close.')
        for ticker in sorted(candles):
            df = prepared[ticker]
            history = df.loc[:date]
            evaluated_days += 1
            signal_ready_days += int(len(history) >= MIN_VERI_UZUNLUGU)
            signal = signal_generator(ticker, history)
            if signal is None:
                continue
            signals.append(signal.to_dict())
            if ticker in positions:
                decision(signal, day, 'skipped', 'already_open')
                continue
            if config.execution_model == 'next_open':
                pending[ticker] = signal
            elif date != dates[-1] and len(positions) < config.max_positions:
                # Explicit same-close mode: never simulate the already elapsed
                # candle's high/low after this closing fill.
                position = open_position(signal, day, float(candles[ticker].Close), cash, config)
                if position is not None:
                    positions[ticker] = position
                    cash -= position.entry_price * position.quantity + position.entry_commission
                    decision(signal, day, 'executed', 'signal_close', position)
                else:
                    nominal = open_position(signal, day, float(candles[ticker].Close), config.initial_capital, config)
                    decision(signal, day, 'skipped', 'capital' if nominal is not None else 'invalid_levels_or_risk_lot')
            else:
                decision(signal, day, 'skipped', 'no_next_candle' if date == dates[-1] else 'concurrency')
        market_value = sum(p.quantity * last_close[ticker] for ticker, p in positions.items())
        curve.append({'date': day, 'cash': cash, 'market_value': market_value,
                      'equity': cash + market_value, 'open_positions': len(positions), 'phase': 'close'})
    for ticker, signal in sorted(pending.items()):
        warnings.append(f'{ticker} {signal.signal_date}: entry skipped; no next candle in range.')
        decision(signal, None, 'skipped', 'no_next_candle')
    equity = pd.DataFrame(curve)
    equity['drawdown_pct'] = (equity.equity / equity.equity.cummax() - 1) * 100
    open_records = []
    for ticker, position in sorted(positions.items()):
        open_records.append({'ticker': ticker, 'entry_date': position.entry_date,
                             'entry_price': position.entry_price, 'quantity': position.quantity,
                             'entry_commission_tl': position.entry_commission,
                             'initial_stop': position.initial_stop, 'final_stop': position.stop,
                             'tp1': position.tp1, 'tp2': position.tp2, 'tp1_hit': position.tp1_hit,
                             'last_close': last_close[ticker],
                             'last_close_date': prepared[ticker].index[-1].date().isoformat()})
        warnings.append(f'{ticker}: remains open; no candle at portfolio end. Equity uses stale last Close; no exit fill fabricated.')
    counts = {reason: sum(d['reason'] == reason for d in decisions if d['status'] == 'skipped')
              for reason in ('capital', 'concurrency', 'already_open', 'removed_candle', 'missing_open',
                             'invalid_levels_or_risk_lot', 'no_next_candle')}
    selectivity = {'ticker_days_evaluated': evaluated_days, 'signal_ready_ticker_days': signal_ready_days,
                   'valid_signals': len(signals), 'executed_entries': sum(d['status'] == 'executed' for d in decisions),
                   'closed_trades': len(trades), 'skipped_capital_or_concurrency': counts['capital'] + counts['concurrency'],
                   'skipped_by_reason': counts}
    return BacktestResult(config, start_at.date().isoformat(), end_at.date().isoformat(),
                          sorted(prepared), trades, signals, equity,
                          calculate_metrics(trades, equity, config.initial_capital), warnings, open_records,
                          data_validation=validation, allocation_policy=allocation_policy,
                          entry_decisions=decisions, selectivity=selectivity)
