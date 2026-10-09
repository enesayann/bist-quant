"""Central descriptive rules. No indicators, prices, scores or signals mutate.

These labels are not the bot's entry/exit conditions. Reused constants are read
only; extra RSI/ATR bands are explanation policy, not new strategy thresholds.
"""
import math
from bot import config
from .models import Component, Evidence

ADX_WEAK = 20.0
ADX_STRONG = float(config.ADX_ESIK)  # Strong only when > original 25.
RSI_LOW, RSI_NEUTRAL_LOW, RSI_POSITIVE, RSI_STRONG, RSI_HIGH = 30.0, 45.0, 55.0, 60.0, 70.0
MFI_LOW, MFI_HIGH = 20.0, 80.0
CMF_CONFIRMATION = float(config.CMF_ESIK)  # Positive engine region > .05.
ATR_MODERATE, ATR_ELEVATED, ATR_HIGH = 2.0, 4.0, 6.0
HIST_LOW = float(config.HIST_VOL_MIN_YUZDE)
HIST_MODERATE = 40.0
HIST_HIGH = float(config.HIST_VOL_MAKS_YUZDE)


def number(value, minimum=None, maximum=None):
    if value is None or isinstance(value, bool):
        return None
    try:
        value = float(value)
        if not math.isfinite(value) or minimum is not None and value < minimum or maximum is not None and value > maximum:
            return None
        return value
    except (TypeError, ValueError, OverflowError):
        return None


def positive(value):
    result = number(value, minimum=0)
    return result if result is not None and result > 0 else None


def fmt(value):
    return f'{value:.8g}'


def observation(evidence, rule_id, inputs, text, derived=False):
    evidence.append(Evidence(rule_id=rule_id, inputs=inputs, observation=text, derived=derived))


def component(state, headline, evidence, values):
    return Component(state=state, headline=headline, points=[item.observation for item in evidence],
                     evidence=evidence, missing_inputs=[key for key, value in values.items() if value is None])


def trend_rules(price, indicators):
    values = {'analysis_close': positive(price), 'ema20': positive(indicators.get('ema20')),
              'ema50': positive(indicators.get('ema50')), 'adx': number(indicators.get('adx'), minimum=0),
              'supertrend': number(indicators.get('supertrend'))}
    if values['supertrend'] not in (-1, 1):
        values['supertrend'] = None
    close, ema20, ema50, adx, supertrend = values.values()
    evidence = []
    for key, ema in [('ema20', ema20), ('ema50', ema50)]:
        if close is not None and ema is not None:
            relation = 'above' if close > ema else 'below' if close < ema else 'equal to'
            observation(evidence, f'trend.close_vs_{key}', {'analysis_close': close, key: ema},
                        f'Analysis close {fmt(close)} is {relation} {key.upper()} {fmt(ema)}.')
    if ema20 is not None and ema50 is not None:
        relation = 'above' if ema20 > ema50 else 'below' if ema20 < ema50 else 'equal to'
        observation(evidence, 'trend.ema_structure', {'ema20': ema20, 'ema50': ema50},
                    f'EMA20 {fmt(ema20)} is {relation} EMA50 {fmt(ema50)}.')
    if adx is not None:
        strength = 'strong' if adx > ADX_STRONG else 'moderate' if adx >= ADX_WEAK else 'weak'
        observation(evidence, 'trend.adx_strength', {'adx': adx}, f'ADX {fmt(adx)} describes {strength} trend strength, not its direction.')
    if supertrend is not None:
        direction = 'positive (+1)' if supertrend == 1 else 'negative (-1)'
        observation(evidence, 'trend.supertrend_direction', {'supertrend': supertrend}, f'SuperTrend direction is {direction} on the analysis candle.')
    state = 'unknown'
    if all(value is not None for value in (close, ema20, ema50)):
        state = 'bullish' if close > ema20 > ema50 else 'bearish' if close < ema20 < ema50 else 'neutral' if close == ema20 == ema50 else 'mixed'
    headlines = {'bullish': 'Bullish EMA structure', 'bearish': 'Bearish EMA structure', 'neutral': 'Aligned, flat EMA snapshot',
                 'mixed': 'Mixed EMA structure', 'unknown': 'Trend observations are partial or unavailable'}
    return component(state, headlines[state], evidence, values)


def rsi_state(value):
    if value >= RSI_HIGH:
        return 'overextended'
    if value < RSI_LOW:
        return 'weak'
    if value < RSI_NEUTRAL_LOW:
        return 'weak'
    if value < RSI_POSITIVE:
        return 'neutral'
    if value < RSI_STRONG:
        return 'positive'
    return 'strong'


def momentum_rules(indicators):
    values = {'rsi': number(indicators.get('rsi'), 0, 100), 'macd': number(indicators.get('macd')),
              'macd_signal': number(indicators.get('macd_signal')), 'mfi': number(indicators.get('mfi'), 0, 100)}
    rsi, macd, signal, mfi = values.values()
    evidence, state = [], 'unknown'
    if rsi is not None:
        state = rsi_state(rsi)
        region = 'low RSI region (<30)' if rsi < RSI_LOW else 'overextended RSI region (>=70)' if rsi >= RSI_HIGH else f'{state} descriptive RSI region'
        observation(evidence, 'momentum.rsi_region', {'rsi': rsi}, f'RSI {fmt(rsi)} is in the {region}; no reversal or continuation is predicted.')
    if macd is not None and signal is not None:
        relation = 'above' if macd > signal else 'below' if macd < signal else 'equal to'
        observation(evidence, 'momentum.macd_vs_signal', {'macd': macd, 'macd_signal': signal},
                    f'MACD {fmt(macd)} is {relation} its signal {fmt(signal)}. A recent crossover cannot be inferred from one snapshot.')
        direction = 'positive' if macd > signal else 'weak' if macd < signal else 'neutral'
        if rsi is None:
            state = direction
        elif state in ('positive', 'strong') and direction == 'weak' or state == 'weak' and direction == 'positive':
            state = 'mixed'
    if mfi is not None:
        region = 'low' if mfi <= MFI_LOW else 'high' if mfi >= MFI_HIGH else 'central 20–80'
        observation(evidence, 'momentum.mfi_region', {'mfi': mfi}, f'MFI {fmt(mfi)} is in its {region} descriptive region.')
    headlines = {'weak': 'Weak momentum observations', 'neutral': 'Neutral momentum observations',
                 'positive': 'Positive momentum observations', 'strong': 'Strong momentum observations',
                 'overextended': 'Overextended RSI snapshot', 'mixed': 'Mixed momentum observations',
                 'unknown': 'Momentum observations are partial or unavailable'}
    return component(state, headlines[state], evidence, values)


def volume_rules(price, indicators):
    values = {'cmf': number(indicators.get('cmf'), -1, 1), 'mfi': number(indicators.get('mfi'), 0, 100),
              'obv': number(indicators.get('obv')), 'vwap': positive(indicators.get('vwap')),
              'analysis_close': positive(price)}
    cmf, mfi, obv, vwap, close = values.values()
    evidence, state = [], 'unknown'
    if cmf is not None:
        state = 'positive' if cmf > CMF_CONFIRMATION else 'negative' if cmf < -CMF_CONFIRMATION else 'moderate'
        sign = 'positive' if cmf > 0 else 'negative' if cmf < 0 else 'zero'
        observation(evidence, 'volume.cmf_flow', {'cmf': cmf}, f'CMF {fmt(cmf)} is {sign}; volume-weighted flow is {state} by the descriptive CMF bands.')
    if close is not None and vwap is not None:
        relation = 'above' if close > vwap else 'below' if close < vwap else 'equal to'
        observation(evidence, 'volume.close_vs_vwap', {'analysis_close': close, 'vwap': vwap},
                    f'Analysis close {fmt(close)} is {relation} the engine daily VWAP approximation {fmt(vwap)}.')
    if mfi is not None:
        observation(evidence, 'volume.mfi_level', {'mfi': mfi}, f'MFI is {fmt(mfi)}; it is a money-flow oscillator, not a relative-volume ratio.')
    if obv is not None:
        observation(evidence, 'volume.obv_level', {'obv': obv}, f'OBV level is {fmt(obv)}. Its direction or trend cannot be inferred without prior OBV values.')
    headlines = {'positive': 'Positive CMF flow observations', 'negative': 'Negative CMF flow observations',
                 'moderate': 'Limited CMF flow magnitude', 'unknown': 'Volume-related observations are partial or unavailable'}
    result = component(state, headlines[state], evidence, values)
    # Absolute/relative volume is not in Analysis API v1; do not read live quote volume.
    result.missing_inputs.extend(['analysis_volume', 'relative_volume'])
    return result


def atr_state(value):
    return 'low' if value < ATR_MODERATE else 'moderate' if value < ATR_ELEVATED else 'elevated' if value < ATR_HIGH else 'high'


def hist_state(value):
    return 'low' if value < HIST_LOW else 'moderate' if value < HIST_MODERATE else 'elevated' if value <= HIST_HIGH else 'high'


def risk_rules(price, indicators, risk):
    close, atr = positive(price), number(indicators.get('atr'), minimum=0)
    atr_pct = number(risk.get('atr_pct'), minimum=0)
    derived = False
    if atr_pct is None and close is not None and atr is not None:
        atr_pct = number(atr/close*100, minimum=0)
        derived = atr_pct is not None
    hist = number(indicators.get('historical_volatility_pct'), minimum=0)
    evidence, states = [], []
    if atr_pct is not None:
        label = atr_state(atr_pct)
        states.append(label)
        inputs = {'atr_pct': atr_pct}
        if derived:
            inputs = {'atr': atr, 'analysis_close': close, 'derived.atr_pct': atr_pct}
        observation(evidence, 'risk.atr_percent', inputs, f'ATR is {fmt(atr_pct)}% of the analysis close: {label} recent range variability by descriptive bands.', derived)
    elif atr is not None:
        observation(evidence, 'risk.atr_level', {'atr': atr}, f'ATR is {fmt(atr)}; a percentage classification is unavailable without a usable close.')
    if hist is not None:
        label = hist_state(hist)
        states.append(label)
        observation(evidence, 'risk.historical_volatility', {'historical_volatility_pct': hist},
                    f'Historical volatility is {fmt(hist)}%: {label} by descriptive annualized-volatility bands.')
    order = ['low', 'moderate', 'elevated', 'high']
    state = max(states, key=order.index) if states else 'unknown'
    headline = f'{state.capitalize()} observed market volatility' if states else 'Volatility observations are partial or unavailable'
    return component(state, headline, evidence, {'atr': atr, 'atr_pct': atr_pct, 'historical_volatility_pct': hist})
