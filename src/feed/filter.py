"""Feed filter for market data — filter by symbol, price, and venue with configurable rules."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import List, Optional, Set


class MatchMode(Enum):
    """Mode for matching rules."""

    INCLUDE = "include"
    EXCLUDE = "exclude"


@dataclass(frozen=True)
class MarketData:
    """A single market data tick/quote."""

    symbol: str
    price: float
    venue: str
    timestamp: Optional[float] = None
    volume: Optional[float] = None


@dataclass
class SymbolRule:
    """Rule for filtering by symbol."""

    symbols: Set[str]
    mode: MatchMode = MatchMode.INCLUDE
    case_sensitive: bool = True

    def matches(self, symbol: str) -> bool:
        if self.case_sensitive:
            matched = symbol in self.symbols
        else:
            matched = symbol.lower() in {s.lower() for s in self.symbols}
        return matched if self.mode == MatchMode.INCLUDE else not matched


@dataclass
class PriceRule:
    """Rule for filtering by price."""

    min_price: Optional[float] = None
    max_price: Optional[float] = None

    def matches(self, price: float) -> bool:
        if self.min_price is not None and price < self.min_price:
            return False
        if self.max_price is not None and price > self.max_price:
            return False
        return True


@dataclass
class VenueRule:
    """Rule for filtering by venue."""

    venues: Set[str]
    mode: MatchMode = MatchMode.INCLUDE
    case_sensitive: bool = True

    def matches(self, venue: str) -> bool:
        if self.case_sensitive:
            matched = venue in self.venues
        else:
            matched = venue.lower() in {v.lower() for v in self.venues}
        return matched if self.mode == MatchMode.INCLUDE else not matched


@dataclass
class FilterConfig:
    """Configuration for feed filtering."""

    symbol_rule: Optional[SymbolRule] = None
    price_rule: Optional[PriceRule] = None
    venue_rule: Optional[VenueRule] = None


class FeedFilter:
    """Filters market data based on configurable rules."""

    def __init__(self, config: FilterConfig):
        self.config = config

    def matches(self, item: MarketData) -> bool:
        """Check if a single market data item matches all configured rules."""
        if self.config.symbol_rule is not None:
            if not self.config.symbol_rule.matches(item.symbol):
                return False
        if self.config.price_rule is not None:
            if not self.config.price_rule.matches(item.price):
                return False
        if self.config.venue_rule is not None:
            if not self.config.venue_rule.matches(item.venue):
                return False
        return True

    def filter(self, data: List[MarketData]) -> List[MarketData]:
        """Filter a list of market data items, returning only those that match."""
        return [item for item in data if self.matches(item)]
