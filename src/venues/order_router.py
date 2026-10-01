"""Venue Order Router — smart order routing by price, liquidity, latency."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class OrderSide(Enum):
    BUY = "buy"
    SELL = "sell"


@dataclass(frozen=True)
class VenueQuote:
    """Top-of-book quote for a venue."""

    bid: float
    ask: float
    bid_size: float = 0.0
    ask_size: float = 0.0

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2.0

    @property
    def spread(self) -> float:
        return self.ask - self.bid

    @property
    def spread_bps(self) -> float:
        if self.mid <= 0:
            return 0.0
        return (self.spread / self.mid) * 10_000


@dataclass
class Venue:
    """A trading venue with quote, latency, and fee information."""

    name: str
    quote: VenueQuote
    latency_ms: float = 0.0
    fee_bps: float = 0.0


@dataclass
class RoutingDecision:
    """Result of routing an order to a venue."""

    venue_name: str
    score: float
    reason: str
    order: Dict[str, Any] = field(default_factory=dict)
    all_scores: Dict[str, float] = field(default_factory=dict)


class VenueOrderRouter:
    """Routes orders to optimal venue based on price, liquidity, and latency.

    Scoring uses a weighted combination of:
    - Price (best bid/ask for the order side)
    - Liquidity (available size at the top of book)
    - Latency (lower is better)
    - Fees (lower is better)
    """

    def __init__(
        self,
        venues: Optional[List[Venue]] = None,
        price_weight: float = 1.0,
        liquidity_weight: float = 1.0,
        latency_weight: float = 1.0,
        fee_weight: float = 1.0,
    ) -> None:
        self.venues: List[Venue] = list(venues) if venues else []
        self.price_weight = price_weight
        self.liquidity_weight = liquidity_weight
        self.latency_weight = latency_weight
        self.fee_weight = fee_weight

    def add_venue(self, venue: Venue) -> None:
        if any(v.name == venue.name for v in self.venues):
            raise ValueError(f"Venue '{venue.name}' already exists")
        self.venues.append(venue)

    def remove_venue(self, name: str) -> None:
        for i, v in enumerate(self.venues):
            if v.name == name:
                self.venues.pop(i)
                return
        raise ValueError(f"Venue '{name}' not found")

    def route(
        self,
        order: Dict[str, Any],
        allowed_venues: Optional[List[str]] = None,
        min_liquidity: float = 0.0,
    ) -> RoutingDecision:
        """Route an order to the best venue.

        Args:
            order: Dict with 'symbol', 'side', 'quantity' keys.
            allowed_venues: Optional list of venue names to consider.
            min_liquidity: Minimum liquidity required at the venue.

        Returns:
            RoutingDecision with the selected venue and scoring details.

        Raises:
            ValueError: If no venues are available or have sufficient liquidity.
        """
        if not self.venues:
            raise ValueError("No venues available for routing")

        # Filter by allowed venues
        candidates = self.venues
        if allowed_venues is not None:
            candidates = [v for v in self.venues if v.name in allowed_venues]
            if not candidates:
                raise ValueError("No venues match the allowed list")

        side = order["side"]
        quantity = order["quantity"]

        # Filter by liquidity first
        eligible = []
        for venue in candidates:
            available = venue.quote.ask_size if side == OrderSide.BUY else venue.quote.bid_size
            if available >= quantity and available >= min_liquidity:
                eligible.append(venue)

        if not eligible:
            raise ValueError("Insufficient liquidity across all venues")

        # Find best price for normalization
        if side == OrderSide.BUY:
            best_price = min(v.quote.ask for v in eligible)
        else:
            best_price = max(v.quote.bid for v in eligible)

        # Score each venue
        scores: Dict[str, float] = {}
        for venue in eligible:
            score = self._compute_score(venue, side, quantity, best_price)
            scores[venue.name] = score

        # Select best venue (highest score)
        best_name = max(scores, key=lambda n: scores[n])
        best_score = scores[best_name]

        # Build reason
        best_venue = next(v for v in eligible if v.name == best_name)
        reason = self._build_reason(best_venue, side)

        return RoutingDecision(
            venue_name=best_name,
            score=best_score,
            reason=reason,
            order=order,
            all_scores=scores,
        )

    def _compute_score(
        self, venue: Venue, side: OrderSide, quantity: float, best_price: float
    ) -> float:
        """Compute a composite score for a venue. Higher is better."""
        if side == OrderSide.BUY:
            price = venue.quote.ask
            liquidity = venue.quote.ask_size
        else:
            price = venue.quote.bid
            liquidity = venue.quote.bid_size

        # Price component: best price gets 1.0, others get proportionally less
        # For buy: lower ask is better, so best_price / price
        # For sell: higher bid is better, so price / best_price
        if side == OrderSide.BUY:
            price_score = best_price / price if price > 0 else 0.0
        else:
            price_score = price / best_price if best_price > 0 else 0.0

        # Liquidity component: more liquidity = higher score, capped at 10x
        liquidity_score = min(liquidity / quantity, 10.0) if quantity > 0 else 0.0

        # Latency component: lower latency = higher score
        latency_score = 1.0 / (1.0 + venue.latency_ms)

        # Fee component: lower fee = higher score
        fee_score = 1.0 / (1.0 + venue.fee_bps / 10.0)

        # Weighted sum — price is the dominant factor
        total = (
            self.price_weight * price_score * 100.0
            + self.liquidity_weight * liquidity_score
            + self.latency_weight * latency_score
            + self.fee_weight * fee_score
        )
        return total

    def _build_reason(self, venue: Venue, side: OrderSide) -> str:
        """Build a human-readable reason for the routing decision."""
        if side == OrderSide.BUY:
            return (
                f"Best ask price {venue.quote.ask:.2f} with "
                f"liquidity {venue.quote.ask_size:.0f}, "
                f"latency {venue.latency_ms:.1f}ms, "
                f"fee {venue.fee_bps:.1f}bps"
            )
        else:
            return (
                f"Best bid price {venue.quote.bid:.2f} with "
                f"liquidity {venue.quote.bid_size:.0f}, "
                f"latency {venue.latency_ms:.1f}ms, "
                f"fee {venue.fee_bps:.1f}bps"
            )
