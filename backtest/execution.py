"""Pure long-only daily-candle execution with explicit costs and ordering."""
from dataclasses import dataclass
import math

from bot.config import MAKS_RISK_YUZDESI, PORTFOY_BUYUKLUGU_TL


@dataclass(frozen=True)
class BacktestConfig:
    initial_capital: float = PORTFOY_BUYUKLUGU_TL
    risk_per_trade: float = MAKS_RISK_YUZDESI  # fraction: .01 = 1%
    max_positions: int = 10
    commission_pct: float = 0.0  # percentage points: .1 = 0.1%
    slippage_pct: float = 0.0
    intrabar_policy: str = 'stop_first'
    execution_model: str = 'next_open'

    def __post_init__(self):
        values = (self.initial_capital, self.risk_per_trade, self.commission_pct, self.slippage_pct)
        if any(isinstance(v, bool) or not math.isfinite(v) for v in values):
            raise ValueError('Configuration values must be finite numbers')
        if self.initial_capital <= 0 or not 0 < self.risk_per_trade <= 1:
            raise ValueError('Capital must be positive; risk fraction must be in (0, 1]')
        if isinstance(self.max_positions, bool) or not isinstance(self.max_positions, int) or self.max_positions < 1:
            raise ValueError('Maximum positions must be a positive integer')
        if not 0 <= self.commission_pct < 100 or not 0 <= self.slippage_pct < 100:
            raise ValueError('Costs must be percentages in [0, 100)')
        if self.intrabar_policy not in ('stop_first', 'target_first'):
            raise ValueError('Unknown intrabar policy')
        if self.execution_model not in ('next_open', 'signal_close'):
            raise ValueError('Unknown execution model')


def position_quantity(entry, stop, capital, risk_fraction, cash, commission_pct=0):
    values = (entry, stop, capital, risk_fraction, cash, commission_pct)
    if any(not math.isfinite(v) for v in values):
        raise ValueError('Sizing requires finite inputs')
    if entry <= 0 or stop <= 0 or capital <= 0 or cash < 0 or not 0 < risk_fraction <= 1 or not 0 <= commission_pct < 100:
        raise ValueError('Invalid sizing inputs')
    distance = entry - stop
    if distance <= 0:
        return 0
    # Same risk/stop-distance formula as live; add a cash/fee cap for no leverage.
    return max(0, min(int(capital * risk_fraction / distance),
                      int(cash / (entry * (1 + commission_pct / 100)))))


@dataclass
class Position:
    signal: object
    entry_date: str
    entry_price: float
    quantity: int
    initial_stop: float
    stop: float
    tp1: float
    tp2: float
    entry_commission: float
    highest_close: float
    tp1_hit: bool = False
    bars_held: int = 0


def open_position(signal, date, reference_price, cash, config):
    if not math.isfinite(reference_price) or reference_price <= 0:
        return None
    entry = reference_price * (1 + config.slippage_pct / 100)
    atr = signal.atr_at_entry
    stop, tp1, tp2 = entry - 1.5 * atr, entry + 2 * atr, entry + 3 * atr
    if not math.isfinite(atr) or atr <= 0 or stop <= 0:
        return None
    quantity = position_quantity(entry, stop, config.initial_capital, config.risk_per_trade,
                                 cash, config.commission_pct)
    if quantity == 0:
        return None
    return Position(signal, date, entry, quantity, stop, stop, tp1, tp2,
                    entry * quantity * config.commission_pct / 100, entry)


def stop_reason(position):
    if position.stop == position.entry_price:
        return 'BREAK_EVEN'
    return 'TRAILING_STOP' if position.stop > position.initial_stop else 'STOP'


def process_candle(position, candle, config):
    """Return (reference exit, reason), or None; modify surviving position.

    Open gaps have known precedence. Compare the active stop with OHLC first.
    TP1 does not sell shares; BE and close-based trailing apply NEXT candle.
    """
    position.bars_held += 1
    opening, high, low, close = (float(candle[k]) for k in ('Open', 'High', 'Low', 'Close'))
    # Missing open skips entries, but an existing trade still uses high/low.
    if math.isfinite(opening):
        if opening <= position.stop:
            return opening, stop_reason(position)
        if opening >= position.tp2:
            position.tp1_hit = True
            return opening, 'TP2'
        if opening >= position.tp1:
            position.tp1_hit = True
            position.stop = max(position.stop, position.entry_price)
    stop_touched, tp2_touched = low <= position.stop, high >= position.tp2
    if config.intrabar_policy == 'stop_first' and stop_touched:
        return position.stop, stop_reason(position)
    if tp2_touched:
        position.tp1_hit = True
        return position.tp2, 'TP2'
    if config.intrabar_policy == 'target_first' and high >= position.tp1:
        position.tp1_hit = True
        position.stop = max(position.stop, position.entry_price)
        if low <= position.stop:
            return position.stop, stop_reason(position)
    elif stop_touched:
        return position.stop, stop_reason(position)
    if high >= position.tp1:
        position.tp1_hit = True
        position.stop = max(position.stop, position.entry_price)
    if close > position.highest_close:
        position.highest_close = close
        atr = float(candle['ATR'])
        if math.isfinite(atr) and atr > 0:
            position.stop = max(position.stop, close - 1.5 * atr)
    return None


def close_position(position, date, reference_price, reason, config):
    from datetime import date as calendar_date

    exit_price = reference_price * (1 - config.slippage_pct / 100)
    exit_commission = exit_price * position.quantity * config.commission_pct / 100
    gross = (exit_price - position.entry_price) * position.quantity
    net = gross - position.entry_commission - exit_commission
    basis = position.entry_price * position.quantity
    record = {
        'ticker': position.signal.ticker, 'signal_date': position.signal.signal_date,
        'entry_date': position.entry_date, 'entry_price': position.entry_price,
        'exit_date': date, 'exit_price': exit_price, 'exit_reason': reason,
        'initial_stop': position.initial_stop, 'final_stop': position.stop,
        'tp1': position.tp1, 'tp2': position.tp2, 'tp1_hit': position.tp1_hit,
        'holding_days': (calendar_date.fromisoformat(date) - calendar_date.fromisoformat(position.entry_date)).days,
        'holding_bars': position.bars_held, 'quantity': position.quantity,
        'gross_pnl_tl': gross, 'net_pnl_tl': net,
        'gross_return_pct': gross / basis * 100,
        'net_return_pct': net / (basis + position.entry_commission) * 100,
        'entry_commission_tl': position.entry_commission, 'exit_commission_tl': exit_commission,
        'score_at_entry': position.signal.final_score,
        'technical_score_at_entry': position.signal.technical_score,
        'classification': position.signal.classification,
        'confidence': position.signal.confidence, 'signal_type': position.signal.signal_type,
        'atr_at_entry': position.signal.atr_at_entry,
        'intrabar_policy': config.intrabar_policy,
    }
    return record, exit_price * position.quantity - exit_commission
