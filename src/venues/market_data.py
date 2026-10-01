"""Venue Market Data Aggregator — multi-venue data aggregation.

Aggregates market data quotes from multiple trading venues into a unified
format, supporting multiple aggregation strategies, quality filtering,
staleness detection, and arbitrage opportunity detection.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from enum import Enum, auto
from typing import Dict, List, Optional, Set


class AggregationStrategy(Enum):
    """Strategy for aggregating quotes across venues."""
    BEST = auto()   # Best bid/ask across all venues
    VWAP = auto()   # Volume-weighted average price


class DataQuality(Enum):
    """Quality indicator for market data (lower value = lower quality)."""
    STALE = auto()
    SIMULATED = auto()
    DELAYED = auto()
    REALTIME = auto()


@dataclass(frozen=True)
class VenueQuote:
    """A single market data quote from a venue."""
    venue: str
    symbol: str
    bid: float
    ask: float
    bid_size: float
    ask_size: float
    timestamp: float = 0.0
    quality: DataQuality = DataQuality.REALTIME

    def __post_init__(self) -> None:
        if self.bid < 0:
            raise ValueError(f"bid must be non-negative: {self.bid}")
        if self.ask < 0:
            raise ValueError(f"ask must be non-negative: {self.ask}")
        if self.bid_size < 0:
            raise ValueError(f"bid_size must be non-negative: {self.bid_size}")
        if self.ask_size < 0:
            raise ValueError(f"ask_size must be non-negative: {self.ask_size}")

    @property
    def spread(self) -> float:
        """Bid-ask spread."""
        if self.bid > 0 and self.ask > 0:
            return self.ask - self.bid
        return 0.0

    @property
    def mid_price(self) -> float:
        """Mid price."""
        if self.bid > 0 and self.ask > 0:
            return (self.bid + self.ask) / 2.0
        return 0.0


@dataclass(frozen=True)
class AggregatedQuote:
    """Aggregated market data across venues for a single symbol."""
    symbol: str
    best_bid: float
    best_ask: float
    best_bid_venue: str
    best_ask_venue: str
    vwap_bid: float
    vwap_ask: float
    total_bid_size: float
    total_ask_size: float
    venue_count: int
    timestamp: float = 0.0

    @property
    def spread(self) -> float:
        """Aggregated bid-ask spread."""
        if self.best_bid > 0 and self.best_ask > 0:
            return self.best_ask - self.best_bid
        return 0.0

    @property
    def mid_price(self) -> float:
        """Aggregated mid price."""
        if self.best_bid > 0 and self.best_ask > 0:
            return (self.best_bid + self.best_ask) / 2.0
        return 0.0


@dataclass(frozen=True)
class ArbitrageOpportunity:
    """Detected arbitrage opportunity across venues."""
    symbol: str
    buy_venue: str
    sell_venue: str
    buy_price: float
    sell_price: float
    spread: float
    profit_per_unit: float
    timestamp: float = 0.0


class VenueMarketDataAggregator:
    """Aggregates market data from multiple venues into unified format.

    Thread-safe aggregator that maintains per-symbol, per-venue quotes
    and produces aggregated views with configurable strategy, quality
    filtering, and staleness detection.
    """

    def __init__(
        self,
        strategy: AggregationStrategy = AggregationStrategy.BEST,
        max_staleness_ms: float = 5000.0,
        min_quality: DataQuality = DataQuality.STALE,
        max_venues: int = 50,
    ) -> None:
        self._strategy = strategy
        self._max_staleness_ms = max_staleness_ms
        self._min_quality = min_quality
        self._max_venues = max_venues
        self._lock = threading.RLock()
        # symbol -> venue -> VenueQuote
        self._quotes: Dict[str, Dict[str, VenueQuote]] = {}

    @property
    def strategy(self) -> AggregationStrategy:
        return self._strategy

    def add_venue_quote(self, quote: VenueQuote) -> None:
        """Add or update a venue quote for a symbol.

        Args:
            quote: The venue quote to add.

        Raises:
            ValueError: If quote validation fails.
        """
        with self._lock:
            symbol = quote.symbol
            if symbol not in self._quotes:
                self._quotes[symbol] = {}

            venue_quotes = self._quotes[symbol]

            # Enforce max venues limit (evict oldest if needed)
            if quote.venue not in venue_quotes and len(venue_quotes) >= self._max_venues:
                # Evict the venue with the oldest timestamp
                oldest_venue = min(venue_quotes, key=lambda v: venue_quotes[v].timestamp)
                del venue_quotes[oldest_venue]

            venue_quotes[quote.venue] = quote

    def remove_venue(self, venue: str) -> None:
        """Remove all quotes for a venue across all symbols.

        Args:
            venue: The venue to remove.
        """
        with self._lock:
            for symbol in list(self._quotes.keys()):
                if venue in self._quotes[symbol]:
                    del self._quotes[symbol][venue]
                if not self._quotes[symbol]:
                    del self._quotes[symbol]

    def clear(self) -> None:
        """Clear all aggregated data."""
        with self._lock:
            self._quotes.clear()

    def get_aggregated_quote(self, symbol: str) -> Optional[AggregatedQuote]:
        """Get the aggregated quote for a symbol.

        Args:
            symbol: The trading symbol.

        Returns:
            AggregatedQuote or None if no valid quotes exist.
        """
        with self._lock:
            venue_quotes = self._quotes.get(symbol, {})
            if not venue_quotes:
                return None

            now = time.time()
            valid_quotes = self._filter_valid_quotes(venue_quotes, now)
            if not valid_quotes:
                return None

            return self._aggregate(symbol, valid_quotes, now)

    def get_all_aggregated_quotes(self) -> Dict[str, AggregatedQuote]:
        """Get all aggregated quotes.

        Returns:
            Dict mapping symbol to AggregatedQuote.
        """
        with self._lock:
            now = time.time()
            result: Dict[str, AggregatedQuote] = {}
            for symbol, venue_quotes in self._quotes.items():
                valid = self._filter_valid_quotes(venue_quotes, now)
                if valid:
                    agg = self._aggregate(symbol, valid, now)
                    if agg is not None:
                        result[symbol] = agg
            return result

    def get_symbols(self) -> Set[str]:
        """Get all tracked symbols.

        Returns:
            Set of symbol strings.
        """
        with self._lock:
            return set(self._quotes.keys())

    def get_venue_count(self) -> int:
        """Get the number of unique venues.

        Returns:
            Count of unique venues.
        """
        with self._lock:
            venues: Set[str] = set()
            for venue_quotes in self._quotes.values():
                venues.update(venue_quotes.keys())
            return len(venues)

    def get_price_discrepancy(self, symbol: str) -> float:
        """Get the price discrepancy (max bid - min ask) for a symbol.

        Args:
            symbol: The trading symbol.

        Returns:
            Price discrepancy, or 0.0 if insufficient data.
        """
        with self._lock:
            venue_quotes = self._quotes.get(symbol, {})
            if not venue_quotes:
                return 0.0

            now = time.time()
            valid = self._filter_valid_quotes(venue_quotes, now)
            if len(valid) < 2:
                return 0.0

            bids = [q.bid for q in valid if q.bid > 0]
            asks = [q.ask for q in valid if q.ask > 0]
            if not bids or not asks:
                return 0.0

            return max(bids) - min(asks)

    def detect_arbitrage(
        self, symbol: str, min_spread: float = 0.0
    ) -> Optional[ArbitrageOpportunity]:
        """Detect arbitrage opportunity for a symbol.

        Args:
            symbol: The trading symbol.
            min_spread: Minimum spread to consider.

        Returns:
            ArbitrageOpportunity or None if no opportunity exists.
        """
        with self._lock:
            venue_quotes = self._quotes.get(symbol, {})
            if not venue_quotes:
                return None

            now = time.time()
            valid = self._filter_valid_quotes(venue_quotes, now)
            if len(valid) < 2:
                return None

            # Find best buy (lowest ask) and best sell (highest bid)
            buy_quote = min(valid, key=lambda q: q.ask if q.ask > 0 else float("inf"))
            sell_quote = max(valid, key=lambda q: q.bid)

            if buy_quote.ask <= 0 or sell_quote.bid <= 0:
                return None

            spread = sell_quote.bid - buy_quote.ask
            if spread < min_spread:
                return None

            return ArbitrageOpportunity(
                symbol=symbol,
                buy_venue=buy_quote.venue,
                sell_venue=sell_quote.venue,
                buy_price=buy_quote.ask,
                sell_price=sell_quote.bid,
                spread=spread,
                profit_per_unit=spread,
                timestamp=now,
            )

    # ------------------------------------------------------------------
    # Internal Methods
    # ------------------------------------------------------------------

    def _filter_valid_quotes(
        self, venue_quotes: Dict[str, VenueQuote], now: float
    ) -> List[VenueQuote]:
        """Filter quotes by staleness and quality."""
        valid: List[VenueQuote] = []
        for q in venue_quotes.values():
            # Staleness check
            age_ms = (now - q.timestamp) * 1000.0
            if age_ms > self._max_staleness_ms:
                continue
            # Quality check
            if q.quality.value < self._min_quality.value:
                continue
            valid.append(q)
        return valid

    def _aggregate(
        self, symbol: str, quotes: List[VenueQuote], now: float
    ) -> Optional[AggregatedQuote]:
        """Aggregate a list of venue quotes into a single AggregatedQuote."""
        if not quotes:
            return None

        # Best bid/ask
        best_bid_quote = max(quotes, key=lambda q: q.bid)
        best_ask_quote = min(quotes, key=lambda q: q.ask if q.ask > 0 else float("inf"))

        # VWAP
        total_bid_size = sum(q.bid_size for q in quotes)
        total_ask_size = sum(q.ask_size for q in quotes)

        if total_bid_size > 0:
            vwap_bid = sum(q.bid * q.bid_size for q in quotes) / total_bid_size
        else:
            vwap_bid = 0.0

        if total_ask_size > 0:
            vwap_ask = sum(q.ask * q.ask_size for q in quotes) / total_ask_size
        else:
            vwap_ask = 0.0

        return AggregatedQuote(
            symbol=symbol,
            best_bid=best_bid_quote.bid,
            best_ask=best_ask_quote.ask,
            best_bid_venue=best_bid_quote.venue,
            best_ask_venue=best_ask_quote.venue,
            vwap_bid=vwap_bid,
            vwap_ask=vwap_ask,
            total_bid_size=total_bid_size,
            total_ask_size=total_ask_size,
            venue_count=len(quotes),
            timestamp=now,
        )
