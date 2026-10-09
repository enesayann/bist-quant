"""Isolated 1h historical data/session replay. No strategy or order execution."""


class IntradayError(ValueError):
    def __init__(self, message, diagnostics=None):
        super().__init__(message)
        self.diagnostics = diagnostics or {}


class GapError(IntradayError):
    """A requested completed session segment is missing required candles."""


class CacheError(IntradayError):
    """Cache integrity, version or source/basis conflict."""


class CacheMiss(CacheError):
    """The immutable local snapshots do not cover the requested segment."""
