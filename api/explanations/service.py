"""Pure snapshot-to-explanation transformation: no I/O, clock or score calls."""
from collections.abc import Mapping
from .models import Explanation, Summary
from .rules import trend_rules, momentum_rules, volume_rules, risk_rules


def mapping(value):
    return value if isinstance(value, Mapping) else {}


def generate_explanation(analysis) -> Explanation:
    data = analysis.model_dump(exclude={'explanation'}) if hasattr(analysis, 'model_dump') else mapping(analysis)
    market, indicators = mapping(data.get('market')), mapping(data.get('indicators'))
    freshness, risk = mapping(data.get('data_freshness')), mapping(data.get('risk'))
    trend = trend_rules(market.get('price'), indicators)
    momentum = momentum_rules(indicators)
    volume = volume_rules(market.get('price'), indicators)
    volatility = risk_rules(market.get('price'), indicators, risk)
    warnings = []
    if freshness.get('is_stale') is True:
        warnings.append('Analysis is based on the latest completed available candle and may not represent the current session.')
    status = freshness.get('market_status')
    status = status if status in ('open', 'closed', 'holiday', 'pre_market_or_auction', 'unknown') else 'unknown'
    if status in ('closed', 'holiday'):
        warnings.append('The analysis snapshot reports the market as closed or on holiday; these observations describe completed available data.')
    elif status == 'unknown':
        warnings.append('Market/session status is unavailable in the analysis snapshot; no current-session claim is made.')
    if any(part.missing_inputs for part in (trend, momentum, volume, volatility)):
        warnings.append('Explanations are partial where inputs are unavailable. Absolute/relative volume and OBV trend are not supplied by this analysis snapshot.')
    warnings.append('Descriptive regions do not reproduce every scoring condition or explain every point. Scores and signals remain those of the existing engine.')
    trend_text = {'bullish': 'EMA structure is constructive', 'bearish': 'EMA structure is negative', 'neutral': 'EMAs and close are aligned in this snapshot', 'mixed': 'EMA structure is mixed', 'unknown': 'EMA direction is unavailable or partial'}[trend.state]
    momentum_text = {'weak': 'momentum observations are weak', 'neutral': 'momentum observations are neutral', 'positive': 'momentum observations are positive', 'strong': 'momentum observations are strong', 'overextended': 'RSI is in its overextended region', 'mixed': 'momentum observations are mixed', 'unknown': 'momentum context is unavailable or partial'}[momentum.state]
    volume_text = {'positive': 'CMF flow is positive', 'negative': 'CMF flow is negative', 'moderate': 'CMF flow magnitude is limited', 'unknown': 'CMF confirmation is unavailable'}[volume.state]
    risk_text = 'volatility context is unavailable' if volatility.state == 'unknown' else f'observed market volatility is {volatility.state}'
    return Explanation(analysis_as_of=data.get('as_of') if isinstance(data.get('as_of'), str) else None,
                       analysis_last_bar=freshness.get('last_bar') if isinstance(freshness.get('last_bar'), str) else None,
                       market_status=status, trend=trend, momentum=momentum, volume=volume, risk=volatility,
                       summary=Summary(headline='Quant snapshot summary', text=f'{trend_text}; {momentum_text}. {volume_text}, while {risk_text}. This describes the analysis candle, not a forecast or an action recommendation.'),
                       warnings=warnings)
