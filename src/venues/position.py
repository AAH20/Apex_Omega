"""Venue Position Manager — APEX-OS v1.0 Predictive Cross-Venue Market Making Kernel.

Multi-venue position tracking with real-time P&L. Tracks positions across
multiple venues, calculates realized/unrealized P&L, and provides mark-to-market
valuation.

This module provides:
    - Position: Immutable position state at a venue.
    - Fill: Immutable fill representation.
    - PositionSide: Enum for LONG/SHORT/FLAT classification.
    - VenuePositionManager: Thread-safe multi-venue position tracker with P&L.
    - create_manager: Convenience factory function.

Architecture:
    The VenuePositionManager is the single entry point for position tracking.
    It maintains per-venue and per-instrument position state, updates on fills,
    and provides aggregated position/exposure/P&L metrics.

    All public methods are thread-safe (protected by an internal lock).

Usage:
    mgr = VenuePositionManager(instruments=["BTC-USD"], venues=["binance"])
    mgr.apply_fill(Fill(instrument="BTC-USD", venue="binance", quantity=1.0, price=50000.0))
    mgr.update_market_price("BTC-USD", 51000.0)
    pnl = mgr.get_total_pnl("BTC-USD")
"""

from __future__ import annotations

import logging
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class PositionSide(Enum):
    """Classification of position direction."""

    LONG = auto()
    SHORT = auto()
    FLAT = auto()


# ---------------------------------------------------------------------------
# Data Structures
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Position:
    """Represents a position at a specific venue for an instrument.

    Attributes:
        instrument: The instrument identifier (e.g., "BTC-USD").
        venue: The venue identifier (e.g., "binance").
        quantity: Net position quantity (positive = long, negative = short).
        avg_price: Volume-weighted average entry price.
        timestamp: Unix timestamp of last update.
    """

    instrument: str
    venue: str
    quantity: float
    avg_price: float
    timestamp: float = field(default_factory=time.time)

    @property
    def notional(self) -> float:
        """Absolute notional value of the position."""
        return abs(self.quantity * self.avg_price)

    @property
    def signed_notional(self) -> float:
        """Signed notional value (positive for long, negative for short)."""
        return self.quantity * self.avg_price

    @property
    def side(self) -> PositionSide:
        """Position side classification."""
        if self.quantity > 0:
            return PositionSide.LONG
        elif self.quantity < 0:
            return PositionSide.SHORT
        return PositionSide.FLAT


@dataclass(frozen=True)
class Fill:
    """Represents an executed fill.

    Attributes:
        instrument: The instrument identifier.
        venue: The venue identifier.
        quantity: Fill quantity (positive = buy, negative = sell).
        price: Fill execution price.
        timestamp: Unix timestamp of the fill.
    """

    instrument: str
    venue: str
    quantity: float
    price: float
    timestamp: float = field(default_factory=time.time)

    @property
    def notional(self) -> float:
        """Absolute notional value of the fill."""
        return abs(self.quantity * self.price)


# ---------------------------------------------------------------------------
# Venue Position Manager
# ---------------------------------------------------------------------------


class VenuePositionManager:
    """Thread-safe multi-venue position tracker with real-time P&L.

    Maintains per-venue and per-instrument position state, updates on fills,
    and provides aggregated position/exposure/P&L metrics.

    All methods are thread-safe.

    Usage:
        mgr = VenuePositionManager(instruments=["BTC-USD"], venues=["binance"])
        mgr.apply_fill(Fill(instrument="BTC-USD", venue="binance", quantity=1.0, price=50000.0))
        mgr.update_market_price("BTC-USD", 51000.0)
        pnl = mgr.get_total_pnl("BTC-USD")
    """

    def __init__(
        self,
        instruments: Optional[List[str]] = None,
        venues: Optional[List[str]] = None,
    ) -> None:
        """Initialize the venue position manager.

        Args:
            instruments: Optional list of known instrument identifiers.
            venues: Optional list of known venue identifiers.
        """
        self._lock = threading.RLock()
        # (instrument, venue) -> Position
        self._positions: Dict[tuple[str, str], Position] = {}
        # instrument -> net quantity
        self._instrument_positions: Dict[str, float] = defaultdict(float)
        # venue -> net quantity
        self._venue_positions: Dict[str, float] = defaultdict(float)
        # instrument -> net exposure (signed notional)
        self._instrument_exposures: Dict[str, float] = defaultdict(float)
        # venue -> net exposure (signed notional)
        self._venue_exposures: Dict[str, float] = defaultdict(float)
        # instrument -> realized P&L
        self._realized_pnl: Dict[str, float] = defaultdict(float)
        # (instrument, venue) -> realized P&L
        self._realized_pnl_by_venue: Dict[tuple[str, str], float] = defaultdict(float)
        # instrument -> current market price
        self._market_prices: Dict[str, float] = {}
        # Known instruments and venues (for enumeration)
        self._known_instruments: set[str] = set(instruments) if instruments else set()
        self._known_venues: set[str] = set(venues) if venues else set()

    # -----------------------------------------------------------------------
    # Fill Application
    # -----------------------------------------------------------------------

    def apply_fill(self, fill: Fill) -> None:
        """Apply a fill to update position state.

        Args:
            fill: The executed fill to apply.
        """
        with self._lock:
            key = (fill.instrument, fill.venue)
            existing = self._positions.get(key)

            # Track known instruments and venues
            self._known_instruments.add(fill.instrument)
            self._known_venues.add(fill.venue)

            if existing is None:
                new_position = Position(
                    instrument=fill.instrument,
                    venue=fill.venue,
                    quantity=fill.quantity,
                    avg_price=fill.price,
                    timestamp=fill.timestamp,
                )
            else:
                new_qty = existing.quantity + fill.quantity

                # Check if this fill closes or reduces the position
                if (existing.quantity > 0 and fill.quantity < 0) or (
                    existing.quantity < 0 and fill.quantity > 0
                ):
                    # Closing/reducing — calculate realized P&L
                    closed_qty = min(abs(existing.quantity), abs(fill.quantity))
                    if existing.quantity > 0:
                        # Long position being closed
                        pnl = closed_qty * (fill.price - existing.avg_price)
                    else:
                        # Short position being closed
                        pnl = closed_qty * (existing.avg_price - fill.price)
                    self._realized_pnl[fill.instrument] += pnl
                    self._realized_pnl_by_venue[key] += pnl

                if new_qty == 0.0:
                    # Position closed — remove it
                    self._positions.pop(key, None)
                    self._instrument_positions[fill.instrument] += fill.quantity
                    self._venue_positions[fill.venue] += fill.quantity
                    self._instrument_exposures[fill.instrument] += fill.quantity * fill.price
                    self._venue_exposures[fill.venue] += fill.quantity * fill.price
                    return
                elif (existing.quantity > 0 and fill.quantity > 0) or (
                    existing.quantity < 0 and fill.quantity < 0
                ):
                    # Adding to position — weighted average price
                    total_cost = existing.quantity * existing.avg_price + fill.quantity * fill.price
                    new_avg_price = total_cost / new_qty
                else:
                    # Reducing position — keep avg price
                    new_avg_price = existing.avg_price

                new_position = Position(
                    instrument=fill.instrument,
                    venue=fill.venue,
                    quantity=new_qty,
                    avg_price=new_avg_price,
                    timestamp=fill.timestamp,
                )

            self._positions[key] = new_position
            self._instrument_positions[fill.instrument] += fill.quantity
            self._venue_positions[fill.venue] += fill.quantity
            self._instrument_exposures[fill.instrument] += fill.quantity * fill.price
            self._venue_exposures[fill.venue] += fill.quantity * fill.price

    # -----------------------------------------------------------------------
    # Position Queries
    # -----------------------------------------------------------------------

    def get_position(self, instrument: str, venue: str) -> Optional[Position]:
        """Get the current position for an instrument at a venue.

        Args:
            instrument: The instrument identifier.
            venue: The venue identifier.

        Returns:
            The Position if one exists, None otherwise.
        """
        with self._lock:
            return self._positions.get((instrument, venue))

    def get_net_position(self, instrument: Optional[str] = None) -> float:
        """Get the net position, optionally filtered by instrument.

        Args:
            instrument: If provided, return net position for this instrument only.

        Returns:
            Net position quantity.
        """
        with self._lock:
            if instrument is not None:
                return self._instrument_positions.get(instrument, 0.0)
            return sum(self._instrument_positions.values())

    def get_gross_position(self, instrument: Optional[str] = None) -> float:
        """Get the total gross position (sum of absolute venue positions).

        Args:
            instrument: If provided, return gross position for this instrument only.

        Returns:
            Gross position in units.
        """
        with self._lock:
            if instrument is not None:
                return sum(
                    abs(pos.quantity)
                    for (inst, _), pos in self._positions.items()
                    if inst == instrument
                )
            return sum(abs(pos.quantity) for pos in self._positions.values())

    def get_venue_position(self, venue: str) -> float:
        """Get the net position at a specific venue.

        Args:
            venue: The venue identifier.

        Returns:
            Net position quantity at the venue.
        """
        with self._lock:
            return self._venue_positions.get(venue, 0.0)

    def get_all_positions(self) -> List[Position]:
        """Get a list of all current positions.

        Returns:
            List of Position objects.
        """
        with self._lock:
            return list(self._positions.values())

    def get_instrument_positions(self) -> Dict[str, float]:
        """Get a copy of all instrument positions.

        Returns:
            Dictionary mapping instrument to net position.
        """
        with self._lock:
            return dict(self._instrument_positions)

    def get_venue_positions(self) -> Dict[str, float]:
        """Get a copy of all venue positions.

        Returns:
            Dictionary mapping venue to net position.
        """
        with self._lock:
            return dict(self._venue_positions)

    # -----------------------------------------------------------------------
    # Exposure Queries
    # -----------------------------------------------------------------------

    def get_net_exposure(self, instrument: Optional[str] = None) -> float:
        """Get the net exposure (signed notional), optionally filtered by instrument.

        Args:
            instrument: If provided, return net exposure for this instrument only.

        Returns:
            Net exposure in quote currency.
        """
        with self._lock:
            if instrument is not None:
                return self._instrument_exposures.get(instrument, 0.0)
            return sum(self._instrument_exposures.values())

    def get_gross_exposure(self, instrument: Optional[str] = None) -> float:
        """Get the total gross exposure (sum of absolute venue exposures).

        Args:
            instrument: If provided, return gross exposure for this instrument only.

        Returns:
            Gross exposure in quote currency.
        """
        with self._lock:
            if instrument is not None:
                return sum(
                    abs(pos.notional)
                    for (inst, _), pos in self._positions.items()
                    if inst == instrument
                )
            return sum(abs(pos.notional) for pos in self._positions.values())

    def get_venue_exposure(self, venue: str) -> float:
        """Get the net exposure at a specific venue.

        Args:
            venue: The venue identifier.

        Returns:
            Net exposure in quote currency at the venue.
        """
        with self._lock:
            return self._venue_exposures.get(venue, 0.0)

    # -----------------------------------------------------------------------
    # Market Price
    # -----------------------------------------------------------------------

    def update_market_price(self, instrument: str, price: float) -> None:
        """Update the current market price for an instrument.

        Args:
            instrument: The instrument identifier.
            price: The current market price.
        """
        with self._lock:
            self._market_prices[instrument] = price

    def get_market_price(self, instrument: str) -> Optional[float]:
        """Get the current market price for an instrument.

        Args:
            instrument: The instrument identifier.

        Returns:
            The current market price, or None if not set.
        """
        with self._lock:
            return self._market_prices.get(instrument)

    # -----------------------------------------------------------------------
    # P&L Calculations
    # -----------------------------------------------------------------------

    def get_unrealized_pnl(self, instrument: str) -> float:
        """Get the unrealized P&L for an instrument.

        Args:
            instrument: The instrument identifier.

        Returns:
            Unrealized P&L in quote currency.
        """
        with self._lock:
            market_price = self._market_prices.get(instrument)
            if market_price is None:
                return 0.0
            pnl = 0.0
            for (inst, _), pos in self._positions.items():
                if inst == instrument:
                    pnl += pos.quantity * (market_price - pos.avg_price)
            return pnl

    def get_realized_pnl(self, instrument: str) -> float:
        """Get the realized P&L for an instrument.

        Args:
            instrument: The instrument identifier.

        Returns:
            Realized P&L in quote currency.
        """
        with self._lock:
            return self._realized_pnl.get(instrument, 0.0)

    def get_total_pnl(self, instrument: str) -> float:
        """Get the total P&L (realized + unrealized) for an instrument.

        Args:
            instrument: The instrument identifier.

        Returns:
            Total P&L in quote currency.
        """
        with self._lock:
            return self.get_realized_pnl(instrument) + self.get_unrealized_pnl(instrument)

    def get_unrealized_pnl_by_venue(self, instrument: str) -> Dict[str, float]:
        """Get unrealized P&L broken down by venue.

        Args:
            instrument: The instrument identifier.

        Returns:
            Dictionary mapping venue to unrealized P&L.
        """
        with self._lock:
            market_price = self._market_prices.get(instrument)
            if market_price is None:
                return {}
            pnl_by_venue: Dict[str, float] = {}
            for (inst, venue), pos in self._positions.items():
                if inst == instrument:
                    pnl_by_venue[venue] = pos.quantity * (market_price - pos.avg_price)
            return pnl_by_venue

    def get_realized_pnl_by_venue(self, instrument: str) -> Dict[str, float]:
        """Get realized P&L broken down by venue.

        Args:
            instrument: The instrument identifier.

        Returns:
            Dictionary mapping venue to realized P&L.
        """
        with self._lock:
            pnl_by_venue: Dict[str, float] = {}
            for (inst, venue), pnl in self._realized_pnl_by_venue.items():
                if inst == instrument:
                    pnl_by_venue[venue] = pnl
            return pnl_by_venue

    # -----------------------------------------------------------------------
    # Reset
    # -----------------------------------------------------------------------

    def reset(self) -> None:
        """Reset all position state."""
        with self._lock:
            self._positions.clear()
            self._instrument_positions.clear()
            self._venue_positions.clear()
            self._instrument_exposures.clear()
            self._venue_exposures.clear()
            self._realized_pnl.clear()
            self._realized_pnl_by_venue.clear()
            self._market_prices.clear()


# ---------------------------------------------------------------------------
# Convenience Functions
# ---------------------------------------------------------------------------


def create_manager(
    instruments: Optional[List[str]] = None,
    venues: Optional[List[str]] = None,
) -> VenuePositionManager:
    """Create a VenuePositionManager with sensible defaults.

    Args:
        instruments: Optional list of known instrument identifiers.
        venues: Optional list of known venue identifiers.

    Returns:
        A new VenuePositionManager instance.
    """
    return VenuePositionManager(instruments=instruments, venues=venues)


# ---------------------------------------------------------------------------
# Module-level exports
# ---------------------------------------------------------------------------

__all__ = [
    "Fill",
    "Position",
    "PositionSide",
    "VenuePositionManager",
    "create_manager",
]
