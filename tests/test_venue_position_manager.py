"""Unit tests for Venue Position Manager.

Tests cover:
- Position tracking across multiple venues
- Fill application and position updates
- Net/gross position calculations
- Realized and unrealized P&L
- Mark-to-market pricing
- Average entry price calculation
- Position closing
- Thread safety
- Edge cases and boundary conditions
"""

import sys
import threading
import time
import unittest
from pathlib import Path

src_path = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(src_path))

from venues.position import (
    Fill,
    Position,
    PositionSide,
    VenuePositionManager,
    create_manager,
)


class TestPosition(unittest.TestCase):
    """Tests for Position dataclass."""

    def test_position_creation(self) -> None:
        pos = Position(
            instrument="BTC-USD",
            venue="binance",
            quantity=1.5,
            avg_price=50000.0,
        )
        self.assertEqual(pos.instrument, "BTC-USD")
        self.assertEqual(pos.venue, "binance")
        self.assertEqual(pos.quantity, 1.5)
        self.assertEqual(pos.avg_price, 50000.0)

    def test_position_notional(self) -> None:
        pos = Position(
            instrument="BTC-USD",
            venue="binance",
            quantity=2.0,
            avg_price=50000.0,
        )
        self.assertEqual(pos.notional, 100000.0)

    def test_position_signed_notional(self) -> None:
        pos = Position(
            instrument="BTC-USD",
            venue="binance",
            quantity=-2.0,
            avg_price=50000.0,
        )
        self.assertEqual(pos.signed_notional, -100000.0)

    def test_position_side_long(self) -> None:
        pos = Position(
            instrument="BTC-USD",
            venue="binance",
            quantity=1.0,
            avg_price=50000.0,
        )
        self.assertEqual(pos.side, PositionSide.LONG)

    def test_position_side_short(self) -> None:
        pos = Position(
            instrument="BTC-USD",
            venue="binance",
            quantity=-1.0,
            avg_price=50000.0,
        )
        self.assertEqual(pos.side, PositionSide.SHORT)

    def test_position_side_flat(self) -> None:
        pos = Position(
            instrument="BTC-USD",
            venue="binance",
            quantity=0.0,
            avg_price=50000.0,
        )
        self.assertEqual(pos.side, PositionSide.FLAT)


class TestFill(unittest.TestCase):
    """Tests for Fill dataclass."""

    def test_fill_creation(self) -> None:
        fill = Fill(
            instrument="BTC-USD",
            venue="binance",
            quantity=1.0,
            price=50000.0,
        )
        self.assertEqual(fill.instrument, "BTC-USD")
        self.assertEqual(fill.venue, "binance")
        self.assertEqual(fill.quantity, 1.0)
        self.assertEqual(fill.price, 50000.0)

    def test_fill_notional(self) -> None:
        fill = Fill(
            instrument="BTC-USD",
            venue="binance",
            quantity=2.0,
            price=50000.0,
        )
        self.assertEqual(fill.notional, 100000.0)


class TestVenuePositionManagerInitialization(unittest.TestCase):
    """Tests for VenuePositionManager initialization."""

    def test_default_initialization(self) -> None:
        mgr = VenuePositionManager()
        self.assertEqual(mgr.get_net_position(), 0.0)
        self.assertEqual(mgr.get_gross_position(), 0.0)

    def test_initialization_with_instruments(self) -> None:
        mgr = VenuePositionManager(instruments=["BTC-USD", "ETH-USD"])
        self.assertEqual(mgr.get_net_position("BTC-USD"), 0.0)
        self.assertEqual(mgr.get_net_position("ETH-USD"), 0.0)

    def test_initialization_with_venues(self) -> None:
        mgr = VenuePositionManager(venues=["binance", "coinbase"])
        self.assertEqual(mgr.get_venue_position("binance"), 0.0)
        self.assertEqual(mgr.get_venue_position("coinbase"), 0.0)

    def test_create_manager_helper(self) -> None:
        mgr = create_manager(instruments=["BTC-USD"], venues=["binance"])
        self.assertIsInstance(mgr, VenuePositionManager)


class TestVenuePositionManagerFillApplication(unittest.TestCase):
    """Tests for fill application and position updates."""

    def test_apply_single_fill(self) -> None:
        mgr = VenuePositionManager()
        fill = Fill(instrument="BTC-USD", venue="binance", quantity=1.0, price=50000.0)
        mgr.apply_fill(fill)
        self.assertEqual(mgr.get_net_position("BTC-USD"), 1.0)

    def test_apply_multiple_fills_same_venue(self) -> None:
        mgr = VenuePositionManager()
        mgr.apply_fill(Fill(instrument="BTC-USD", venue="binance", quantity=1.0, price=50000.0))
        mgr.apply_fill(Fill(instrument="BTC-USD", venue="binance", quantity=0.5, price=51000.0))
        self.assertEqual(mgr.get_net_position("BTC-USD"), 1.5)

    def test_apply_fills_different_venues(self) -> None:
        mgr = VenuePositionManager()
        mgr.apply_fill(Fill(instrument="BTC-USD", venue="binance", quantity=1.0, price=50000.0))
        mgr.apply_fill(Fill(instrument="BTC-USD", venue="coinbase", quantity=0.5, price=50100.0))
        self.assertEqual(mgr.get_net_position("BTC-USD"), 1.5)
        self.assertEqual(mgr.get_venue_position("binance"), 1.0)
        self.assertEqual(mgr.get_venue_position("coinbase"), 0.5)

    def test_apply_sell_fill_reduces_position(self) -> None:
        mgr = VenuePositionManager()
        mgr.apply_fill(Fill(instrument="BTC-USD", venue="binance", quantity=2.0, price=50000.0))
        mgr.apply_fill(Fill(instrument="BTC-USD", venue="binance", quantity=-1.0, price=51000.0))
        self.assertEqual(mgr.get_net_position("BTC-USD"), 1.0)

    def test_apply_fill_closes_position(self) -> None:
        mgr = VenuePositionManager()
        mgr.apply_fill(Fill(instrument="BTC-USD", venue="binance", quantity=1.0, price=50000.0))
        mgr.apply_fill(Fill(instrument="BTC-USD", venue="binance", quantity=-1.0, price=51000.0))
        self.assertEqual(mgr.get_net_position("BTC-USD"), 0.0)

    def test_apply_fill_flips_position(self) -> None:
        mgr = VenuePositionManager()
        mgr.apply_fill(Fill(instrument="BTC-USD", venue="binance", quantity=1.0, price=50000.0))
        mgr.apply_fill(Fill(instrument="BTC-USD", venue="binance", quantity=-2.0, price=51000.0))
        self.assertEqual(mgr.get_net_position("BTC-USD"), -1.0)


class TestVenuePositionManagerAveragePrice(unittest.TestCase):
    """Tests for average entry price calculation."""

    def test_avg_price_single_fill(self) -> None:
        mgr = VenuePositionManager()
        mgr.apply_fill(Fill(instrument="BTC-USD", venue="binance", quantity=1.0, price=50000.0))
        pos = mgr.get_position("BTC-USD", "binance")
        self.assertIsNotNone(pos)
        self.assertAlmostEqual(pos.avg_price, 50000.0)

    def test_avg_price_weighted_multiple_fills(self) -> None:
        mgr = VenuePositionManager()
        mgr.apply_fill(Fill(instrument="BTC-USD", venue="binance", quantity=1.0, price=50000.0))
        mgr.apply_fill(Fill(instrument="BTC-USD", venue="binance", quantity=1.0, price=52000.0))
        pos = mgr.get_position("BTC-USD", "binance")
        self.assertIsNotNone(pos)
        self.assertAlmostEqual(pos.avg_price, 51000.0)

    def test_avg_price_unchanged_on_reduce(self) -> None:
        mgr = VenuePositionManager()
        mgr.apply_fill(Fill(instrument="BTC-USD", venue="binance", quantity=2.0, price=50000.0))
        mgr.apply_fill(Fill(instrument="BTC-USD", venue="binance", quantity=-1.0, price=51000.0))
        pos = mgr.get_position("BTC-USD", "binance")
        self.assertIsNotNone(pos)
        self.assertAlmostEqual(pos.avg_price, 50000.0)


class TestVenuePositionManagerGrossPosition(unittest.TestCase):
    """Tests for gross position calculation."""

    def test_gross_position_single_venue(self) -> None:
        mgr = VenuePositionManager()
        mgr.apply_fill(Fill(instrument="BTC-USD", venue="binance", quantity=1.0, price=50000.0))
        self.assertEqual(mgr.get_gross_position(), 1.0)

    def test_gross_position_multiple_venues(self) -> None:
        mgr = VenuePositionManager()
        mgr.apply_fill(Fill(instrument="BTC-USD", venue="binance", quantity=1.0, price=50000.0))
        mgr.apply_fill(Fill(instrument="BTC-USD", venue="coinbase", quantity=0.5, price=50100.0))
        self.assertEqual(mgr.get_gross_position(), 1.5)

    def test_gross_position_with_short(self) -> None:
        mgr = VenuePositionManager()
        mgr.apply_fill(Fill(instrument="BTC-USD", venue="binance", quantity=1.0, price=50000.0))
        mgr.apply_fill(Fill(instrument="BTC-USD", venue="coinbase", quantity=-0.5, price=50100.0))
        self.assertEqual(mgr.get_gross_position(), 1.5)

    def test_gross_position_per_instrument(self) -> None:
        mgr = VenuePositionManager()
        mgr.apply_fill(Fill(instrument="BTC-USD", venue="binance", quantity=1.0, price=50000.0))
        mgr.apply_fill(Fill(instrument="ETH-USD", venue="binance", quantity=10.0, price=3000.0))
        self.assertEqual(mgr.get_gross_position("BTC-USD"), 1.0)
        self.assertEqual(mgr.get_gross_position("ETH-USD"), 10.0)


class TestVenuePositionManagerExposure(unittest.TestCase):
    """Tests for exposure calculations."""

    def test_net_exposure(self) -> None:
        mgr = VenuePositionManager()
        mgr.apply_fill(Fill(instrument="BTC-USD", venue="binance", quantity=1.0, price=50000.0))
        self.assertEqual(mgr.get_net_exposure("BTC-USD"), 50000.0)

    def test_gross_exposure(self) -> None:
        mgr = VenuePositionManager()
        mgr.apply_fill(Fill(instrument="BTC-USD", venue="binance", quantity=1.0, price=50000.0))
        mgr.apply_fill(Fill(instrument="BTC-USD", venue="coinbase", quantity=-0.5, price=50100.0))
        self.assertEqual(mgr.get_gross_exposure("BTC-USD"), 75050.0)

    def test_venue_exposure(self) -> None:
        mgr = VenuePositionManager()
        mgr.apply_fill(Fill(instrument="BTC-USD", venue="binance", quantity=1.0, price=50000.0))
        mgr.apply_fill(Fill(instrument="ETH-USD", venue="binance", quantity=10.0, price=3000.0))
        self.assertEqual(mgr.get_venue_exposure("binance"), 80000.0)


class TestVenuePositionManagerUnrealizedPnl(unittest.TestCase):
    """Tests for unrealized P&L calculation."""

    def test_unrealized_pnl_long_profit(self) -> None:
        mgr = VenuePositionManager()
        mgr.apply_fill(Fill(instrument="BTC-USD", venue="binance", quantity=1.0, price=50000.0))
        mgr.update_market_price("BTC-USD", 51000.0)
        self.assertEqual(mgr.get_unrealized_pnl("BTC-USD"), 1000.0)

    def test_unrealized_pnl_long_loss(self) -> None:
        mgr = VenuePositionManager()
        mgr.apply_fill(Fill(instrument="BTC-USD", venue="binance", quantity=1.0, price=50000.0))
        mgr.update_market_price("BTC-USD", 49000.0)
        self.assertEqual(mgr.get_unrealized_pnl("BTC-USD"), -1000.0)

    def test_unrealized_pnl_short_profit(self) -> None:
        mgr = VenuePositionManager()
        mgr.apply_fill(Fill(instrument="BTC-USD", venue="binance", quantity=-1.0, price=50000.0))
        mgr.update_market_price("BTC-USD", 49000.0)
        self.assertEqual(mgr.get_unrealized_pnl("BTC-USD"), 1000.0)

    def test_unrealized_pnl_short_loss(self) -> None:
        mgr = VenuePositionManager()
        mgr.apply_fill(Fill(instrument="BTC-USD", venue="binance", quantity=-1.0, price=50000.0))
        mgr.update_market_price("BTC-USD", 51000.0)
        self.assertEqual(mgr.get_unrealized_pnl("BTC-USD"), -1000.0)

    def test_unrealized_pnl_flat_position(self) -> None:
        mgr = VenuePositionManager()
        mgr.update_market_price("BTC-USD", 50000.0)
        self.assertEqual(mgr.get_unrealized_pnl("BTC-USD"), 0.0)

    def test_unrealized_pnl_multiple_venues(self) -> None:
        mgr = VenuePositionManager()
        mgr.apply_fill(Fill(instrument="BTC-USD", venue="binance", quantity=1.0, price=50000.0))
        mgr.apply_fill(Fill(instrument="BTC-USD", venue="coinbase", quantity=1.0, price=50100.0))
        mgr.update_market_price("BTC-USD", 51000.0)
        self.assertEqual(mgr.get_unrealized_pnl("BTC-USD"), 1900.0)


class TestVenuePositionManagerRealizedPnl(unittest.TestCase):
    """Tests for realized P&L calculation."""

    def test_realized_pnl_on_partial_close(self) -> None:
        mgr = VenuePositionManager()
        mgr.apply_fill(Fill(instrument="BTC-USD", venue="binance", quantity=2.0, price=50000.0))
        mgr.apply_fill(Fill(instrument="BTC-USD", venue="binance", quantity=-1.0, price=51000.0))
        self.assertEqual(mgr.get_realized_pnl("BTC-USD"), 1000.0)

    def test_realized_pnl_on_full_close(self) -> None:
        mgr = VenuePositionManager()
        mgr.apply_fill(Fill(instrument="BTC-USD", venue="binance", quantity=1.0, price=50000.0))
        mgr.apply_fill(Fill(instrument="BTC-USD", venue="binance", quantity=-1.0, price=51000.0))
        self.assertEqual(mgr.get_realized_pnl("BTC-USD"), 1000.0)

    def test_realized_pnl_short_close(self) -> None:
        mgr = VenuePositionManager()
        mgr.apply_fill(Fill(instrument="BTC-USD", venue="binance", quantity=-1.0, price=50000.0))
        mgr.apply_fill(Fill(instrument="BTC-USD", venue="binance", quantity=1.0, price=49000.0))
        self.assertEqual(mgr.get_realized_pnl("BTC-USD"), 1000.0)

    def test_realized_pnl_multiple_closes(self) -> None:
        mgr = VenuePositionManager()
        mgr.apply_fill(Fill(instrument="BTC-USD", venue="binance", quantity=3.0, price=50000.0))
        mgr.apply_fill(Fill(instrument="BTC-USD", venue="binance", quantity=-1.0, price=51000.0))
        mgr.apply_fill(Fill(instrument="BTC-USD", venue="binance", quantity=-1.0, price=52000.0))
        self.assertEqual(mgr.get_realized_pnl("BTC-USD"), 3000.0)

    def test_realized_pnl_no_closes(self) -> None:
        mgr = VenuePositionManager()
        mgr.apply_fill(Fill(instrument="BTC-USD", venue="binance", quantity=1.0, price=50000.0))
        self.assertEqual(mgr.get_realized_pnl("BTC-USD"), 0.0)


class TestVenuePositionManagerTotalPnl(unittest.TestCase):
    """Tests for total P&L calculation."""

    def test_total_pnl_combines_realized_and_unrealized(self) -> None:
        mgr = VenuePositionManager()
        mgr.apply_fill(Fill(instrument="BTC-USD", venue="binance", quantity=2.0, price=50000.0))
        mgr.apply_fill(Fill(instrument="BTC-USD", venue="binance", quantity=-1.0, price=51000.0))
        mgr.update_market_price("BTC-USD", 52000.0)
        # Realized: 1000, Unrealized: 1 * (52000 - 50000) = 2000
        self.assertEqual(mgr.get_total_pnl("BTC-USD"), 3000.0)


class TestVenuePositionManagerMarketPrice(unittest.TestCase):
    """Tests for market price updates."""

    def test_update_market_price(self) -> None:
        mgr = VenuePositionManager()
        mgr.update_market_price("BTC-USD", 50000.0)
        self.assertEqual(mgr.get_market_price("BTC-USD"), 50000.0)

    def test_update_market_price_overwrites(self) -> None:
        mgr = VenuePositionManager()
        mgr.update_market_price("BTC-USD", 50000.0)
        mgr.update_market_price("BTC-USD", 51000.0)
        self.assertEqual(mgr.get_market_price("BTC-USD"), 51000.0)

    def test_get_market_price_unknown_instrument(self) -> None:
        mgr = VenuePositionManager()
        self.assertIsNone(mgr.get_market_price("UNKNOWN"))


class TestVenuePositionManagerReset(unittest.TestCase):
    """Tests for reset functionality."""

    def test_reset_clears_all_state(self) -> None:
        mgr = VenuePositionManager()
        mgr.apply_fill(Fill(instrument="BTC-USD", venue="binance", quantity=1.0, price=50000.0))
        mgr.update_market_price("BTC-USD", 51000.0)
        mgr.reset()
        self.assertEqual(mgr.get_net_position("BTC-USD"), 0.0)
        self.assertIsNone(mgr.get_market_price("BTC-USD"))

    def test_reset_clears_realized_pnl(self) -> None:
        mgr = VenuePositionManager()
        mgr.apply_fill(Fill(instrument="BTC-USD", venue="binance", quantity=1.0, price=50000.0))
        mgr.apply_fill(Fill(instrument="BTC-USD", venue="binance", quantity=-1.0, price=51000.0))
        mgr.reset()
        self.assertEqual(mgr.get_realized_pnl("BTC-USD"), 0.0)


class TestVenuePositionManagerThreadSafety(unittest.TestCase):
    """Tests for thread safety."""

    def test_concurrent_fills(self) -> None:
        mgr = VenuePositionManager()
        errors = []

        def apply_fills() -> None:
            try:
                for _ in range(100):
                    mgr.apply_fill(
                        Fill(instrument="BTC-USD", venue="binance", quantity=0.01, price=50000.0)
                    )
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=apply_fills) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(errors), 0)
        self.assertAlmostEqual(mgr.get_net_position("BTC-USD"), 10.0, places=5)

    def test_concurrent_price_updates(self) -> None:
        mgr = VenuePositionManager()
        mgr.apply_fill(Fill(instrument="BTC-USD", venue="binance", quantity=1.0, price=50000.0))
        errors = []

        def update_prices() -> None:
            try:
                for i in range(100):
                    mgr.update_market_price("BTC-USD", 50000.0 + i)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=update_prices) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(errors), 0)
        # Price should be one of the updated values
        self.assertGreaterEqual(mgr.get_market_price("BTC-USD"), 50000.0)


class TestVenuePositionManagerEdgeCases(unittest.TestCase):
    """Tests for edge cases and boundary conditions."""

    def test_zero_quantity_fill(self) -> None:
        mgr = VenuePositionManager()
        mgr.apply_fill(Fill(instrument="BTC-USD", venue="binance", quantity=0.0, price=50000.0))
        self.assertEqual(mgr.get_net_position("BTC-USD"), 0.0)

    def test_very_small_quantity(self) -> None:
        mgr = VenuePositionManager()
        mgr.apply_fill(Fill(instrument="BTC-USD", venue="binance", quantity=1e-8, price=50000.0))
        self.assertAlmostEqual(mgr.get_net_position("BTC-USD"), 1e-8)

    def test_very_large_quantity(self) -> None:
        mgr = VenuePositionManager()
        mgr.apply_fill(Fill(instrument="BTC-USD", venue="binance", quantity=1e9, price=50000.0))
        self.assertEqual(mgr.get_net_position("BTC-USD"), 1e9)

    def test_negative_price_update(self) -> None:
        mgr = VenuePositionManager()
        mgr.apply_fill(Fill(instrument="BTC-USD", venue="binance", quantity=1.0, price=50000.0))
        # Negative price should be rejected or handled gracefully
        mgr.update_market_price("BTC-USD", -100.0)
        # Price should remain unchanged or be handled
        self.assertIsNotNone(mgr.get_market_price("BTC-USD"))

    def test_get_all_positions_empty(self) -> None:
        mgr = VenuePositionManager()
        self.assertEqual(mgr.get_all_positions(), [])

    def test_get_all_positions_with_data(self) -> None:
        mgr = VenuePositionManager()
        mgr.apply_fill(Fill(instrument="BTC-USD", venue="binance", quantity=1.0, price=50000.0))
        mgr.apply_fill(Fill(instrument="ETH-USD", venue="coinbase", quantity=10.0, price=3000.0))
        positions = mgr.get_all_positions()
        self.assertEqual(len(positions), 2)

    def test_get_instrument_positions(self) -> None:
        mgr = VenuePositionManager()
        mgr.apply_fill(Fill(instrument="BTC-USD", venue="binance", quantity=1.0, price=50000.0))
        mgr.apply_fill(Fill(instrument="ETH-USD", venue="binance", quantity=10.0, price=3000.0))
        positions = mgr.get_instrument_positions()
        self.assertEqual(positions["BTC-USD"], 1.0)
        self.assertEqual(positions["ETH-USD"], 10.0)

    def test_get_venue_positions(self) -> None:
        mgr = VenuePositionManager()
        mgr.apply_fill(Fill(instrument="BTC-USD", venue="binance", quantity=1.0, price=50000.0))
        mgr.apply_fill(Fill(instrument="BTC-USD", venue="coinbase", quantity=0.5, price=50100.0))
        positions = mgr.get_venue_positions()
        self.assertEqual(positions["binance"], 1.0)
        self.assertEqual(positions["coinbase"], 0.5)


class TestVenuePositionManagerPnlByVenue(unittest.TestCase):
    """Tests for P&L breakdown by venue."""

    def test_unrealized_pnl_by_venue(self) -> None:
        mgr = VenuePositionManager()
        mgr.apply_fill(Fill(instrument="BTC-USD", venue="binance", quantity=1.0, price=50000.0))
        mgr.apply_fill(Fill(instrument="BTC-USD", venue="coinbase", quantity=1.0, price=50100.0))
        mgr.update_market_price("BTC-USD", 51000.0)
        pnl_by_venue = mgr.get_unrealized_pnl_by_venue("BTC-USD")
        self.assertAlmostEqual(pnl_by_venue["binance"], 1000.0)
        self.assertAlmostEqual(pnl_by_venue["coinbase"], 900.0)

    def test_realized_pnl_by_venue(self) -> None:
        mgr = VenuePositionManager()
        mgr.apply_fill(Fill(instrument="BTC-USD", venue="binance", quantity=1.0, price=50000.0))
        mgr.apply_fill(Fill(instrument="BTC-USD", venue="binance", quantity=-1.0, price=51000.0))
        mgr.apply_fill(Fill(instrument="BTC-USD", venue="coinbase", quantity=1.0, price=50000.0))
        mgr.apply_fill(Fill(instrument="BTC-USD", venue="coinbase", quantity=-1.0, price=50500.0))
        pnl_by_venue = mgr.get_realized_pnl_by_venue("BTC-USD")
        self.assertAlmostEqual(pnl_by_venue["binance"], 1000.0)
        self.assertAlmostEqual(pnl_by_venue["coinbase"], 500.0)


if __name__ == "__main__":
    unittest.main()
