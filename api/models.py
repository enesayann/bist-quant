"""Explicit finite JSON contract. Missing measurements are null, never invented."""
import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from api.explanations.models import Explanation

from backtest.data import normalize_ticker


def normalize_symbol(value: str) -> str:
    symbol = normalize_ticker(value)
    if not symbol[0].isalpha():
        raise ValueError('Expected a BIST ticker such as ASELS or ASELS.IS')
    return symbol


class Model(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False, extra='forbid')


class AnalyzeRequest(Model):
    ticker: str = Field(min_length=1, max_length=32, strict=True)

    @field_validator('ticker')
    @classmethod
    def normalize(cls, value):
        return normalize_symbol(value)


class Freshness(Model):
    last_bar: str
    market_status: Literal['unknown'] = 'unknown'
    is_stale: bool
    expected_last_bar: str
    completed_bars_only: bool = True
    session_note: str = 'Exchange calendar unavailable; freshness uses weekdays, not BIST holidays.'


class Market(Model):
    price: float
    previous_close: float
    change: float
    change_pct: float
    price_basis: str = 'last_completed_daily_close'


class Scores(Model):
    overall: float
    technical: float
    trend: float
    momentum: float
    volume: float
    volatility: float
    fundamental: float | None = None
    news: float | None = None
    support_resistance_adjustment: float
    category_maxima: dict[str, float]
    scope: str = 'technical_only_zero_unavailable_contributions'


class Indicators(Model):
    rsi: float | None = None
    ema20: float | None = None
    ema50: float | None = None
    ema200: float | None = None
    atr: float | None = None
    adx: float | None = None
    macd: float | None = None
    macd_signal: float | None = None
    mfi: float | None = None
    cmf: float | None = None
    obv: float | None = None
    vwap: float | None = None
    historical_volatility_pct: float | None = None
    supertrend: float | None = None

    @field_validator('*', mode='before')
    @classmethod
    def finite_or_null(cls, value):
        if value is None:
            return None
        value = float(value)
        return value if math.isfinite(value) else None


class Strategy(Model):
    name: str = 'Daily Strategy v1'
    score: float
    technical_score: float
    state: Literal['setup', 'no_setup']
    signal: str | None = None
    classification: str | None = None
    scope: str = 'Existing completed-candle, neutral-news/fundamentals decision; not the live bot runtime.'


class Risk(Model):
    atr_pct: float | None
    volatility_state: str | None = None


class PricePoint(Model):
    date: str
    value: float


class DataQuality(Model):
    rows_downloaded: int
    rows_removed: int
    usable_rows: int
    warnings: list[str]


class CacheInfo(Model):
    hit: bool = False
    ttl_seconds: float
    age_seconds: float = 0


class AnalysisResponse(Model):
    ticker: str
    symbol: str
    analysis_type: Literal['daily_v1'] = 'daily_v1'
    mode: Literal['research'] = 'research'
    as_of: str
    source: str = 'Yahoo daily chart · existing engine'
    data_freshness: Freshness
    market: Market
    scores: Scores
    indicators: Indicators
    strategy: Strategy
    risk: Risk
    price_series: list[PricePoint]
    data_quality: DataQuality
    cache: CacheInfo
    warnings: list[str]
    disclaimer: str = 'Research / paper-trading analysis only.'
    explanation: Explanation | None = None

    @model_validator(mode='after')
    def add_explanation(self):
        if self.explanation is None:
            from api.explanations.service import generate_explanation
            self.explanation = generate_explanation(self)
        return self
