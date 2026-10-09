"""Provider-neutral snapshot: one quote plus recent completed daily history.

The service exposes latest quote, ranged history and multi-symbol snapshots
from this bundle. A licensed provider implements this boundary, not Yahoo JSON.
"""
from datetime import datetime
from typing import Protocol
from .models import ProviderSnapshot


class MarketDataProvider(Protocol):
    name: str

    def fetch_snapshot(self, symbol: str, as_of: datetime) -> ProviderSnapshot: ...
