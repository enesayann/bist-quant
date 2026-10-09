"""Net trade statistics and marked-to-market portfolio risk measures."""
import math

import numpy as np
import pandas as pd


def calculate_metrics(trades, equity, initial_capital):
    pnl = [t['net_pnl_tl'] for t in trades]
    returns = [t['net_return_pct'] for t in trades]
    winners = [t for t in trades if t['net_pnl_tl'] > 0]
    losers = [t for t in trades if t['net_pnl_tl'] < 0]
    losses = -sum(t['net_pnl_tl'] for t in losers)
    gains = sum(t['net_pnl_tl'] for t in winners)
    streak = longest = 0
    for trade in sorted(trades, key=lambda t: (t['exit_date'], t['ticker'])):
        streak = streak + 1 if trade['net_pnl_tl'] < 0 else 0
        longest = max(longest, streak)
    ending = float(equity.equity.iloc[-1])
    series = equity.equity.astype(float)
    drawdown = (series / series.cummax() - 1) * 100
    daily = equity[equity.phase == 'close'] if 'phase' in equity else equity
    # Initial capital is the previous close for the first daily return.
    daily_returns = pd.Series([initial_capital] + daily.equity.tolist()).pct_change().dropna()
    sharpe = None
    if len(daily_returns) >= 60 and daily_returns.std(ddof=1) > 0:
        sharpe = float(daily_returns.mean() / daily_returns.std(ddof=1) * math.sqrt(252))
    elapsed = (pd.Timestamp(equity.date.iloc[-1]) - pd.Timestamp(equity.date.iloc[0])).days
    cagr = None
    if elapsed >= 365 and len(daily) >= 252 and ending > 0:
        cagr = ((ending / initial_capital) ** (365.25 / elapsed) - 1) * 100
    average = lambda values: float(np.mean(values)) if values else None
    return {
        'total_trades': len(trades), 'winning_trades': len(winners), 'losing_trades': len(losers),
        'break_even_trades': len(trades) - len(winners) - len(losers),
        'win_rate_pct': len(winners) / len(trades) * 100 if trades else None,
        'initial_capital_tl': initial_capital, 'ending_capital_tl': ending,
        'total_return_pct': (ending / initial_capital - 1) * 100,
        'net_pnl_tl': ending - initial_capital, 'closed_trade_net_pnl_tl': sum(pnl),
        'average_trade_return_pct': average(returns),
        'median_trade_return_pct': float(np.median(returns)) if returns else None,
        'average_winner_pct': average([t['net_return_pct'] for t in winners]),
        'average_loser_pct': average([t['net_return_pct'] for t in losers]),
        'profit_factor': gains / losses if losses else None,
        'profit_factor_status': 'finite' if losses else 'no_losses' if winners else 'no_closed_losses_or_wins',
        'expectancy_tl': average(pnl), 'expectancy_pct': average(returns),
        'maximum_drawdown_pct': float(-drawdown.min()),
        'best_trade_pct': max(returns) if returns else None,
        'worst_trade_pct': min(returns) if returns else None,
        'average_holding_days': average([t['holding_days'] for t in trades]),
        'longest_losing_streak': longest, 'cagr_pct': cagr, 'sharpe_ratio': sharpe,
        'daily_return_observations': len(daily_returns),
    }
