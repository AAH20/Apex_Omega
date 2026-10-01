"""Smart Order Router — liquidity aggregation, venue selection, execution optimization.

Provides intelligent order routing across multiple trading venues with:
- Liquidity aggregation from multiple venues
- Venue selection by price, liquidity, latency, and fees
- Execution optimization via TWAP/VWAP slicing and multi-venue splitting
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class OrderSide(Enum):
    BUY = "buy"
    SELL = "sell"


@dataclass
class VenueLiquidity:
    """Liquidity information for a single venue."""

    name: str
    symbol: str
    bid: float
    ask: float
    bid_size: float = 0.0
    ask_size: float = 0.0
    latency_ms: float = 0.0
    fee_bps: float = 0.0
    depth_levels: int = 5

    @property
    def mid_price(self) -> float:
        return (self.bid + self.ask) / 2.0

    @property
    def spread(self) -> float:
        return self.ask - self.bid

    @property
    def spread_bps(self) -> float:
        if self.mid_price <= 0:
            return 0.0
        return (self.spread / self.mid_price) * 10_000

    def available_size(self, side: OrderSide) -> float:
        """Get available size for the given side."""
        return self.ask_size if side == OrderSide.BUY else self.bid_size


@dataclass
class LiquiditySnapshot:
    """Aggregated liquidity snapshot across venues for a symbol."""

    symbol: str
    venues: List[VenueLiquidity] = field(default_factory=list)

    @property
    def total_bid_size(self) -> float:
        return sum(v.bid_size for v in self.venues)

    @property
    def total_ask_size(self) -> float:
        return sum(v.ask_size for v in self.venues)

    @property
    def best_bid(self) -> float:
        if not self.venues:
            return 0.0
        return max(v.bid for v in self.venues)

    @property
    def best_bid_venue(self) -> str:
        if not self.venues:
            return ""
        return max(self.venues, key=lambda v: v.bid).name

    @property
    def best_ask(self) -> float:
        if not self.venues:
            return 0.0
        return min(v.ask for v in self.venues)

    @property
    def best_venue(self) -> str:
        if not self.venues:
            return ""
        return min(self.venues, key=lambda v: v.ask).name


@dataclass
class VenueScore:
    """Score for a venue in the selection process."""

    venue_name: str
    score: float
    reason: str


@dataclass
class ExecutionSlice:
    """A single slice of an execution plan."""

    venue_name: str
    quantity: float
    price: float
    start_time: float = 0.0
    end_time: float = 0.0


@dataclass
class ExecutionPlan:
    """Complete execution plan for an order."""

    order: Dict[str, Any]
    slices: List[ExecutionSlice] = field(default_factory=list)
    total_quantity: float = 0.0
    total_cost: float = 0.0
    strategy: str = "smart"

    def __post_init__(self):
        if not self.total_quantity:
            self.total_quantity = sum(s.quantity for s in self.slices)
        if not self.total_cost:
            self.total_cost = sum(s.price * s.quantity for s in self.slices)


class SmartOrderRouter:
    """Smart order router with liquidity aggregation and execution optimization.

    Routes orders to optimal venues based on price, liquidity, latency, and fees.
    Supports TWAP/VWAP slicing and multi-venue execution splitting.
    """

    def __init__(
        self,
        venues: Optional[List[VenueLiquidity]] = None,
        price_weight: float = 1.0,
        liquidity_weight: float = 1.0,
        latency_weight: float = 1.0,
        fee_weight: float = 1.0,
    ) -> None:
        self.venues: List[VenueLiquidity] = list(venues) if venues else []
        self.price_weight = price_weight
        self.liquidity_weight = liquidity_weight
        self.latency_weight = latency_weight
        self.fee_weight = fee_weight

    def add_venue(self, venue: VenueLiquidity) -> None:
        if any(v.name == venue.name for v in self.venues):
            raise ValueError(f"Venue '{venue.name}' already exists")
        self.venues.append(venue)

    def remove_venue(self, name: str) -> None:
        for i, v in enumerate(self.venues):
            if v.name == name:
                self.venues.pop(i)
                return
        raise ValueError(f"Venue '{name}' not found")

    # ------------------------------------------------------------------
    # Liquidity Aggregation
    # ------------------------------------------------------------------

    def aggregate_liquidity(self, symbol: str) -> Optional[LiquiditySnapshot]:
        """Aggregate liquidity for a symbol across all venues."""
        matching = [v for v in self.venues if v.symbol == symbol]
        if not matching:
            return None
        return LiquiditySnapshot(symbol=symbol, venues=matching)

    # ------------------------------------------------------------------
    # Venue Selection
    # ------------------------------------------------------------------

    def select_venue(
        self,
        order: Dict[str, Any],
        allowed_venues: Optional[List[str]] = None,
        min_liquidity: float = 0.0,
    ) -> VenueScore:
        """Select the best venue for an order.

        Args:
            order: Dict with 'symbol', 'side', 'quantity' keys.
            allowed_venues: Optional list of venue names to consider.
            min_liquidity: Minimum liquidity required at the venue.

        Returns:
            VenueScore with the selected venue and scoring details.

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
        symbol = order["symbol"]

        # Filter by symbol and liquidity
        eligible = []
        for venue in candidates:
            if venue.symbol != symbol:
                continue
            available = venue.available_size(side)
            if available >= quantity and available >= min_liquidity:
                eligible.append(venue)

        if not eligible:
            raise ValueError("Insufficient liquidity across all venues")

        # Find best price for normalization
        if side == OrderSide.BUY:
            best_price = min(v.ask for v in eligible)
        else:
            best_price = max(v.bid for v in eligible)

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

        return VenueScore(venue_name=best_name, score=best_score, reason=reason)

    # ------------------------------------------------------------------
    # Execution Optimization
    # ------------------------------------------------------------------

    def create_execution_plan(
        self,
        order: Dict[str, Any],
        allowed_venues: Optional[List[str]] = None,
        max_participation: float = 1.0,
    ) -> ExecutionPlan:
        """Create an execution plan for an order.

        Splits the order across venues based on available liquidity and
        optional maximum participation rate.

        Args:
            order: Dict with 'symbol', 'side', 'quantity' keys.
            allowed_venues: Optional list of venue names to consider.
            max_participation: Maximum fraction of venue liquidity to use (0-1].

        Returns:
            ExecutionPlan with slices for each venue.

        Raises:
            ValueError: If no venues available or insufficient total liquidity.
        """
        if not self.venues:
            raise ValueError("No venues available for routing")

        side = order["side"]
        quantity = order["quantity"]
        symbol = order["symbol"]

        # Filter by allowed venues
        candidates = self.venues
        if allowed_venues is not None:
            candidates = [v for v in self.venues if v.name in allowed_venues]
            if not candidates:
                raise ValueError("No venues match the allowed list")

        # Filter by symbol and sort by price (best first)
        eligible = [v for v in candidates if v.symbol == symbol]
        if side == OrderSide.BUY:
            eligible.sort(key=lambda v: v.ask)
        else:
            eligible.sort(key=lambda v: v.bid, reverse=True)

        # Check total available liquidity
        total_available = sum(v.available_size(side) for v in eligible)
        if total_available < quantity:
            raise ValueError("Insufficient liquidity across all venues")

        # Create slices
        slices: List[ExecutionSlice] = []
        remaining = quantity

        for venue in eligible:
            if remaining <= 0:
                break

            available = venue.available_size(side)
            # Apply max participation cap
            max_from_venue = available * max_participation
            take = min(remaining, max_from_venue)

            if take > 0:
                price = venue.ask if side == OrderSide.BUY else venue.bid
                slices.append(
                    ExecutionSlice(
                        venue_name=venue.name,
                        quantity=take,
                        price=price,
                    )
                )
                remaining -= take

        total_cost = sum(s.price * s.quantity for s in slices)
        return ExecutionPlan(
            order=order,
            slices=slices,
            total_quantity=quantity,
            total_cost=total_cost,
            strategy="smart",
        )

    def twap_slices(
        self,
        order: Dict[str, Any],
        num_slices: int,
        interval_seconds: float,
    ) -> List[ExecutionSlice]:
        """Create TWAP (Time-Weighted Average Price) slices.

        Distributes the order evenly across time slices.

        Args:
            order: Dict with 'symbol', 'side', 'quantity' keys.
            num_slices: Number of slices to create.
            interval_seconds: Time between slices in seconds.

        Returns:
            List of ExecutionSlice objects.

        Raises:
            ValueError: If num_slices is not positive.
        """
        if num_slices <= 0:
            raise ValueError("num_slices must be positive")

        side = order["side"]
        quantity = order["quantity"]
        symbol = order["symbol"]

        # Get best venue for this symbol
        eligible = [v for v in self.venues if v.symbol == symbol]
        if not eligible:
            raise ValueError("No venues available for routing")

        if side == OrderSide.BUY:
            best_venue = min(eligible, key=lambda v: v.ask)
        else:
            best_venue = max(eligible, key=lambda v: v.bid)

        price = best_venue.ask if side == OrderSide.BUY else best_venue.bid
        slice_qty = quantity / num_slices

        slices: List[ExecutionSlice] = []
        start_time = 0.0
        for _ in range(num_slices):
            slices.append(
                ExecutionSlice(
                    venue_name=best_venue.name,
                    quantity=slice_qty,
                    price=price,
                    start_time=start_time,
                    end_time=start_time + interval_seconds,
                )
            )
            start_time += interval_seconds

        return slices

    def vwap_slices(self, order: Dict[str, Any]) -> List[ExecutionSlice]:
        """Create VWAP (Volume-Weighted Average Price) slices.

        Distributes the order proportionally to available liquidity at each venue.

        Args:
            order: Dict with 'symbol', 'side', 'quantity' keys.

        Returns:
            List of ExecutionSlice objects.

        Raises:
            ValueError: If no venues available.
        """
        side = order["side"]
        quantity = order["quantity"]
        symbol = order["symbol"]

        eligible = [v for v in self.venues if v.symbol == symbol]
        if not eligible:
            raise ValueError("No venues available for routing")

        total_available = sum(v.available_size(side) for v in eligible)
        if total_available <= 0:
            raise ValueError("No liquidity available")

        slices: List[ExecutionSlice] = []
        for venue in eligible:
            available = venue.available_size(side)
            proportion = available / total_available
            slice_qty = quantity * proportion
            price = venue.ask if side == OrderSide.BUY else venue.bid
            slices.append(
                ExecutionSlice(
                    venue_name=venue.name,
                    quantity=slice_qty,
                    price=price,
                )
            )

        return slices

    def route_order(
        self,
        order: Dict[str, Any],
        allowed_venues: Optional[List[str]] = None,
        max_participation: float = 1.0,
    ) -> ExecutionPlan:
        """Route an order end-to-end, creating an execution plan.

        Args:
            order: Dict with 'symbol', 'side', 'quantity' keys.
            allowed_venues: Optional list of venue names to consider.
            max_participation: Maximum fraction of venue liquidity to use.

        Returns:
            ExecutionPlan with optimal slices.
        """
        return self.create_execution_plan(
            order, allowed_venues=allowed_venues, max_participation=max_participation
        )

    # ------------------------------------------------------------------
    # Internal Methods
    # ------------------------------------------------------------------

    def _compute_score(
        self, venue: VenueLiquidity, side: OrderSide, quantity: float, best_price: float
    ) -> float:
        """Compute a composite score for a venue. Higher is better."""
        if side == OrderSide.BUY:
            price = venue.ask
            liquidity = venue.ask_size
        else:
            price = venue.bid
            liquidity = venue.bid_size

        # Price component: best price gets 1.0, others get proportionally less
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

    def _build_reason(self, venue: VenueLiquidity, side: OrderSide) -> str:
        """Build a human-readable reason for the routing decision."""
        if side == OrderSide.BUY:
            return (
                f"Best ask price {venue.ask:.2f} with "
                f"liquidity {venue.ask_size:.0f}, "
                f"latency {venue.latency_ms:.1f}ms, "
                f"fee {venue.fee_bps:.1f}bps"
            )
        else:
            return (
                f"Best bid price {venue.bid:.2f} with "
                f"liquidity {venue.bid_size:.0f}, "
                f"latency {venue.latency_ms:.1f}ms, "
                f"fee {venue.fee_bps:.1f}bps"
            )
