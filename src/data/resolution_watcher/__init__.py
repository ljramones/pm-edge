"""Resolution watcher for forward-indexed prediction market data."""

from .schema import ResolvedMarketOutcome
from .settings import ResolutionWatcherSettings

__all__ = [
    "ResolutionWatcherSettings",
    "ResolvedMarketOutcome",
]
