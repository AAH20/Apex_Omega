"""Venue Execution Analyzer — execution quality, slippage, venue performance."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Dict, Optional
from statistics import mean, stdev
from collections import defaultdict


@dataclass(frozen=True)
class Fill:
    """A single execution fill with slippage and fee metrics."""

    venue: str
    symbol: str
    side: str  # "buy" or "sell"
    quantity: float
    price: float
    arrival_price: float
    fees: float = 0.0
    timestamp: Optional[float] = None

    @property
    def notional(self) -> float:
        return self.quantity * self.price

    @property
    def slippage_bps(self) -> float:
        """Slippage in basis points. Positive = adverse (paid more / received less)."""
        if self.arrival_price <= 0:
            raise ValueError("arrival_price must be positive")
        if self.side == "buy":
            return ((self.price - self.arrival_price) / self.arrival_price) * 10_000
        elif self.side == "sell":
            return ((self.arrival_price - self.price) / self.arrival_price) * 10_000
        else:
            raise ValueError(f"Unknown side: {self.side!r}")

    @property
    def fee_bps(self) -> float:
        """Fee in basis points of notional."""
        if self.notional <= 0:
            return 0.0
        return (self.fees / self.notional) * 10_000


@dataclass
class VenuePerformance:
    """Aggregated performance metrics for a single venue."""

    venue: str
    total_fills: int = 0
    total_notional: float = 0.0
    total_fees: float = 0.0
    slippage_bps_values: List[float] = field(default_factory=list)
    fill_count_by_symbol: Dict[str, int] = field(default_factory=lambda: defaultdict(int))

    @property
    def avg_slippage_bps(self) -> float:
        if not self.slippage_bps_values:
            return 0.0
        return mean(self.slippage_bps_values)

    @property
    def std_slippage_bps(self) -> float:
        if len(self.slippage_bps_values) < 2:
            return 0.0
        return stdev(self.slippage_bps_values)

    @property
    def total_fee_bps(self) -> float:
        if self.total_notional <= 0:
            return 0.0
        return (self.total_fees / self.total_notional) * 10_000

    @property
    def adverse_slippage_pct(self) -> float:
        """Percentage of fills with adverse (positive) slippage."""
        if not self.slippage_bps_values:
            return 0.0
        adverse = sum(1 for s in self.slippage_bps_values if s > 0)
        return (adverse / len(self.slippage_bps_values)) * 100


class ExecutionAnalyzer:
    """Analyzes execution quality, slippage, and venue performance."""

    def __init__(self) -> None:
        self._fills: List[Fill] = []

    def add_fill(self, fill: Fill) -> None:
        self._fills.append(fill)

    def add_fills(self, fills: List[Fill]) -> None:
        self._fills.extend(fills)

    @property
    def fills(self) -> List[Fill]:
        return list(self._fills)

    def venue_performance(self, venue: Optional[str] = None) -> Dict[str, VenuePerformance]:
        """Compute per-venue performance metrics."""
        grouped: Dict[str, List[Fill]] = defaultdict(list)
        for f in self._fills:
            if venue is None or f.venue == venue:
                grouped[f.venue].append(f)

        result: Dict[str, VenuePerformance] = {}
        for v, fills in grouped.items():
            vp = VenuePerformance(venue=v)
            for f in fills:
                vp.total_fills += 1
                vp.total_notional += f.notional
                vp.total_fees += f.fees
                vp.slippage_bps_values.append(f.slippage_bps)
                vp.fill_count_by_symbol[f.symbol] += 1
            result[v] = vp
        return result

    def overall_slippage_bps(self) -> float:
        """Average slippage across all fills."""
        if not self._fills:
            return 0.0
        return mean(f.slippage_bps for f in self._fills)

    def total_fees(self) -> float:
        return sum(f.fees for f in self._fills)

    def total_notional(self) -> float:
        return sum(f.notional for f in self._fills)

    def best_venue(self) -> Optional[str]:
        """Venue with lowest average slippage."""
        perf = self.venue_performance()
        if not perf:
            return None
        return min(perf, key=lambda v: perf[v].avg_slippage_bps)

    def worst_venue(self) -> Optional[str]:
        """Venue with highest average slippage."""
        perf = self.venue_performance()
        if not perf:
            return None
        return max(perf, key=lambda v: perf[v].avg_slippage_bps)

    def slippage_distribution(self) -> Dict[str, int]:
        """Bucket slippage into distribution categories."""
        buckets = {"favorable": 0, "neutral": 0, "adverse": 0, "severe": 0}
        for f in self._fills:
            s = f.slippage_bps
            if s < -1:
                buckets["favorable"] += 1
            elif s <= 1:
                buckets["neutral"] += 1
            elif s <= 50:
                buckets["adverse"] += 1
            else:
                buckets["severe"] += 1
        return buckets
