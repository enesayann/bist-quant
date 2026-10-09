from typing import Literal
from pydantic import Field
from api.models import Model

MarketStatus = Literal['open', 'closed', 'pre_market_or_auction', 'holiday', 'unknown']
FreshnessStatus = Literal['fresh', 'delayed', 'stale', 'market_closed', 'unknown']


class PublicError(Model):
    code: str
    message: str


class CacheInfo(Model):
    hit: bool = False
    ttl_seconds: int
    age_seconds: float = 0


class SessionInfo(Model):
    status: MarketStatus
    as_of: str
    timezone: str = 'Europe/Istanbul'
    calendar_version: str
    half_day: bool = False
    expected_completed_session: str | None = None
    note: str = 'Scheduled session only; instrument halts and exceptional closures are not observed.'


class Quote(Model):
    symbol: str
    ticker: str
    price: float | None = None
    previous_close: float | None = None
    change: float | None = None
    change_pct: float | None = None
    day_open: float | None = None
    day_high: float | None = None
    day_low: float | None = None
    volume: float | None = None
    currency: str | None = None
    quote_time: str | None = None
    last_bar_time: str | None = None
    provider: str
    provider_delay_status: Literal['unknown', 'delayed', 'real_time_guaranteed'] = 'unknown'
    market_status: MarketStatus = 'unknown'
    freshness_status: FreshnessStatus = 'unknown'
    price_basis: str
    fetched_at: str
    warnings: list[str] = Field(default_factory=list)
    error: PublicError | None = None
    cache: CacheInfo = Field(default_factory=lambda: CacheInfo(ttl_seconds=45))


class HistoryPoint(Model):
    timestamp: str
    date: str
    close: float
    volume: float | None = None


class Quality(Model):
    downloaded_rows: int = 0
    removed_rows: int = 0
    usable_rows: int = 0
    incomplete_rows: int = 0
    future_rows: int = 0
    warnings: list[str] = Field(default_factory=list)


class ProviderSnapshot(Model):
    quote: Quote
    points: list[HistoryPoint]
    quality: Quality
    history_error: PublicError | None = None


class History(Model):
    ticker: str
    symbol: str
    interval: Literal['1d'] = '1d'
    range: Literal['1mo', '3mo', '6mo', '1y']
    provider: str
    fetched_at: str
    completed_only: bool = True
    last_bar_time: str | None = None
    freshness_status: FreshnessStatus
    market_status: MarketStatus
    points: list[HistoryPoint]
    quality: Quality
    cache: CacheInfo


class Scanner(Model):
    fetched_at: str
    session: SessionInfo
    provider: str
    rows: list[Quote]
    partial_failure: bool
    cache: CacheInfo
    strategy_analysis: bool = False
