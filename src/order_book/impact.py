"""Market impact modeling, slippage estimation, and execution quality analysis."""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Dict, Optional
import math


# ── Data Structures ──────────────────────────────────────────────────────────

@dataclass(frozen=True)
class BookLevel:
    """A single price level in the order book."""
    price: float
    volume: int


@dataclass(frozen=True)
class ImpactEstimate:
    """Result of a market impact estimation."""
    temporary_impact_bps: float
    permanent_impact_bps: float
    total_impact_bps: float


@dataclass(frozen=True)
class SlippageEstimate:
    """Estimated slippage for a hypothetical order."""
    filled_volume: int
    requested_volume: int
    expected_vwap: float
    slippage_bps: float


@dataclass(frozen=True)
class ExecutionQuality:
    """Execution quality metrics for a completed order."""
    implementation_shortfall_bps: float
    fill_rate: float
    vwap: float


# ── VWAP Computation ─────────────────────────────────────────────────────────

def compute_vwap(levels: List[BookLevel]) -> float:
    """Compute volume-weighted average price across book levels."""
    total_volume = sum(lvl.volume for lvl in levels)
    if total_volume == 0:
        return 0.0
    total_value = sum(lvl.price * lvl.volume for lvl in levels)
    return total_value / total_volume


# ── Participation Rate ───────────────────────────────────────────────────────

def compute_participation_rate(quantity: float, daily_volume: float) -> float:
    """Compute participation rate as fraction of daily volume."""
    if daily_volume <= 0:
        return 0.0
    return quantity / daily_volume


# ── Square-Root Impact Model ─────────────────────────────────────────────────

class SquareRootImpactModel:
    """Square-root market impact model (Almgren et al. 2005).

    Temporary impact: eta * sigma * sqrt(Q / V)
    Permanent impact: gamma * sigma * sqrt(Q / V)
    """

    def __init__(self, eta: float = 0.5, gamma: float = 0.3):
        self.eta = eta
        self.gamma = gamma

    def estimate_temporary_impact(
        self, quantity: float, daily_volume: float, volatility: float
    ) -> float:
        """Estimate temporary impact in bps."""
        if quantity <= 0 or daily_volume <= 0 or volatility <= 0:
            return 0.0
        participation = quantity / daily_volume
        return self.eta * volatility * math.sqrt(participation) * 10_000

    def estimate_permanent_impact(
        self, quantity: float, daily_volume: float, volatility: float
    ) -> float:
        """Estimate permanent impact in bps."""
        if quantity <= 0 or daily_volume <= 0 or volatility <= 0:
            return 0.0
        participation = quantity / daily_volume
        return self.gamma * volatility * math.sqrt(participation) * 10_000

    def estimate_total_impact(
        self, quantity: float, daily_volume: float, volatility: float
    ) -> float:
        """Estimate total impact (temporary + permanent) in bps."""
        temp = self.estimate_temporary_impact(quantity, daily_volume, volatility)
        perm = self.estimate_permanent_impact(quantity, daily_volume, volatility)
        return temp + perm


# ── Almgren-Chriss Model ─────────────────────────────────────────────────────

class AlmgrenChrissModel:
    """Almgren-Chriss optimal execution model.

    Temporary impact: eta * sigma * sqrt(Q / V)
    Permanent impact: gamma * sigma * sqrt(Q / V)
    """

    def __init__(self, eta: float = 0.5, gamma: float = 0.3):
        self.eta = eta
        self.gamma = gamma

    def estimate_temporary_impact(
        self, quantity: float, daily_volume: float, volatility: float
    ) -> float:
        """Estimate temporary impact in bps."""
        if quantity <= 0 or daily_volume <= 0 or volatility <= 0:
            return 0.0
        participation = quantity / daily_volume
        return self.eta * volatility * math.sqrt(participation) * 10_000

    def estimate_permanent_impact(
        self, quantity: float, daily_volume: float, volatility: float
    ) -> float:
        """Estimate permanent impact in bps."""
        if quantity <= 0 or daily_volume <= 0 or volatility <= 0:
            return 0.0
        participation = quantity / daily_volume
        return self.gamma * volatility * math.sqrt(participation) * 10_000

    def estimate_total_impact(
        self, quantity: float, daily_volume: float, volatility: float
    ) -> float:
        """Estimate total impact (temporary + permanent) in bps."""
        temp = self.estimate_temporary_impact(quantity, daily_volume, volatility)
        perm = self.estimate_permanent_impact(quantity, daily_volume, volatility)
        return temp + perm


# ── Slippage Estimation from Book ────────────────────────────────────────────

def estimate_slippage_from_book(
    side: str,
    quantity: int,
    book_levels: List[BookLevel],
    arrival_price: float,
) -> SlippageEstimate:
    """Estimate slippage by walking the book and computing VWAP of fills."""
    if arrival_price <= 0:
        raise ValueError("arrival_price must be positive")
    if side not in ("buy", "sell"):
        raise ValueError(f"Unknown side: {side!r}")

    remaining = quantity
    total_value = 0.0
    filled = 0

    for level in book_levels:
        if remaining <= 0:
            break
        fill_qty = min(remaining, level.volume)
        total_value += level.price * fill_qty
        filled += fill_qty
        remaining -= fill_qty

    if filled == 0:
        return SlippageEstimate(
            filled_volume=0,
            requested_volume=quantity,
            expected_vwap=0.0,
            slippage_bps=0.0,
        )

    vwap = total_value / filled

    if side == "buy":
        slippage_bps = ((vwap - arrival_price) / arrival_price) * 10_000
    else:
        slippage_bps = ((arrival_price - vwap) / arrival_price) * 10_000

    return SlippageEstimate(
        filled_volume=filled,
        requested_volume=quantity,
        expected_vwap=vwap,
        slippage_bps=slippage_bps,
    )


# ── Execution Quality Analysis ───────────────────────────────────────────────

def analyze_execution_quality(
    fills: List[Dict],
    arrival_price: float,
    side: str,
    requested_quantity: Optional[float] = None,
) -> ExecutionQuality:
    """Analyze execution quality of completed fills."""
    if arrival_price <= 0:
        raise ValueError("arrival_price must be positive")
    if side not in ("buy", "sell"):
        raise ValueError(f"Unknown side: {side!r}")

    if not fills:
        return ExecutionQuality(
            implementation_shortfall_bps=0.0,
            fill_rate=0.0,
            vwap=0.0,
        )

    total_qty = sum(f["quantity"] for f in fills)
    total_value = sum(f["price"] * f["quantity"] for f in fills)
    vwap = total_value / total_qty if total_qty > 0 else 0.0

    if side == "buy":
        is_bps = ((vwap - arrival_price) / arrival_price) * 10_000
    else:
        is_bps = ((arrival_price - vwap) / arrival_price) * 10_000

    if requested_quantity is not None and requested_quantity > 0:
        fill_rate = total_qty / requested_quantity
    else:
        fill_rate = 1.0

    return ExecutionQuality(
        implementation_shortfall_bps=is_bps,
        fill_rate=fill_rate,
        vwap=vwap,
    )


# ── Arrival Price Slippage ───────────────────────────────────────────────────

def compute_arrival_price_slippage(
    side: str, execution_price: float, arrival_price: float
) -> float:
    """Compute slippage vs arrival price in bps."""
    if arrival_price <= 0:
        raise ValueError("arrival_price must be positive")
    if side == "buy":
        return ((execution_price - arrival_price) / arrival_price) * 10_000
    elif side == "sell":
        return ((arrival_price - execution_price) / arrival_price) * 10_000
    else:
        raise ValueError(f"Unknown side: {side!r}")
