"""
End-to-End Trading Pipeline Integration Tests.

Tests the complete trading flow: order entry → risk check → routing →
execution → settlement → position tracking → P&L.

Covers integration across:
    - Order book matching engine
    - Pre-trade risk engine
    - Position limit enforcer
    - Venue order router
    - Execution analyzer
    - Venue position manager
    - Session manager (failover)
    - Market data aggregator
    - Feed normalizer
    - Kill switch
"""

from __future__ import annotations

import sys
import time
import unittest
from pathlib import Path
from typing import List

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from order_book.matching import OrderBook, Order, Side, Trade
from risk.pre_trade import PreTradeRiskEngine, RiskRules, OrderSide as RiskOrderSide
from risk.position_limit import (
    PositionLimitEnforcer,
    PositionLimit,
    EnforcementAction,
)
from risk.kill_switch import KillSwitch, KillSwitchStatus, Venue as KillSwitchVenue
from venues.order_router import VenueOrderRouter, Venue, VenueQuote, OrderSide as RouterOrderSide
from venues.execution_analyzer import ExecutionAnalyzer, Fill
from venues.position import VenuePositionManager, Fill as PositionFill
from venues.session_manager import SessionManager
from venues.market_data import (
    VenueMarketDataAggregator,
    VenueQuote as MarketDataQuote,
    AggregationStrategy,
    DataQuality,
)
from feed.normalizer import FeedNormalizer, NormalizedTick


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_order(
    order_id: str,
    side: Side,
    price: float,
    quantity: int | float,
    timestamp: int = 0,
) -> Order:
    """Create a matching-engine order."""
    return Order(
        order_id=order_id,
        side=side,
        price=price,
        quantity=int(quantity),
        timestamp=timestamp,
    )


def _make_risk_order_side(side: Side) -> RiskOrderSide:
    """Convert matching-engine side to risk-engine side."""
    return RiskOrderSide.BUY if side == Side.BUY else RiskOrderSide.SELL


def _make_router_order_side(side: Side) -> RouterOrderSide:
    """Convert matching-engine side to router side."""
    return RouterOrderSide.BUY if side == Side.BUY else RouterOrderSide.SELL


def _make_position_fill(
    instrument: str,
    venue: str,
    quantity: float,
    price: float,
) -> PositionFill:
    """Create a position fill."""
    return PositionFill(
        instrument=instrument,
        venue=venue,
        quantity=quantity,
        price=price,
    )


def _make_execution_fill(
    venue: str,
    symbol: str,
    side: str,
    quantity: float,
    price: float,
    arrival_price: float,
    fees: float = 0.0,
) -> Fill:
    """Create an execution fill for analysis."""
    return Fill(
        venue=venue,
        symbol=symbol,
        side=side,
        quantity=quantity,
        price=price,
        arrival_price=arrival_price,
        fees=fees,
    )


# ---------------------------------------------------------------------------
# Test 1: Full Order Lifecycle — Order → Match → Fill → Position → P&L
# ---------------------------------------------------------------------------


class TestFullOrderLifecycle(unittest.TestCase):
    """Test complete order lifecycle from entry to P&L."""

    def test_order_to_fill_to_position_to_pnl(self) -> None:
        """Test order matching generates fills that update positions and P&L."""
        book = OrderBook()
        position_mgr = VenuePositionManager(
            instruments=["BTC-USD"],
            venues=["binance"],
        )

        # Add resting sell order
        sell_order = _make_order("sell-1", Side.SELL, 50_000.0, 1.0, timestamp=1)
        trades = book.add_order(sell_order)
        self.assertEqual(len(trades), 0)  # No match yet

        # Add buy order that matches
        buy_order = _make_order("buy-1", Side.BUY, 50_000.0, 1.0, timestamp=2)
        trades = book.add_order(buy_order)
        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0].taker_order_id, "buy-1")
        self.assertEqual(trades[0].maker_order_id, "sell-1")
        self.assertEqual(trades[0].price, 50_000.0)
        self.assertEqual(trades[0].quantity, 1)

        # Apply fill to position manager
        for trade in trades:
            fill = _make_position_fill("BTC-USD", "binance", trade.quantity, trade.price)
            position_mgr.apply_fill(fill)

        # Verify position
        pos = position_mgr.get_position("BTC-USD", "binance")
        self.assertIsNotNone(pos)
        self.assertEqual(pos.quantity, 1.0)
        self.assertEqual(pos.avg_price, 50_000.0)

        # Update market price and check P&L
        position_mgr.update_market_price("BTC-USD", 51_000.0)
        unrealized = position_mgr.get_unrealized_pnl("BTC-USD")
        self.assertEqual(unrealized, 1_000.0)  # 1 BTC * (51000 - 50000)

        # Close position
        close_fill = _make_position_fill("BTC-USD", "binance", -1.0, 51_000.0)
        position_mgr.apply_fill(close_fill)

        realized = position_mgr.get_realized_pnl("BTC-USD")
        self.assertEqual(realized, 1_000.0)

        # Position should be flat
        pos = position_mgr.get_position("BTC-USD", "binance")
        self.assertIsNone(pos)


# ---------------------------------------------------------------------------
# Test 2: Order Routing Pipeline — Market Data → Route → Execute → Settle
# ---------------------------------------------------------------------------


class TestOrderRoutingPipeline(unittest.TestCase):
    """Test order routing from market data to settlement."""

    def test_route_order_to_best_venue_and_settle(self) -> None:
        """Test routing an order to the best venue and settling the fill."""
        # Set up market data aggregator
        aggregator = VenueMarketDataAggregator(strategy=AggregationStrategy.BEST)

        # Add quotes from multiple venues
        aggregator.add_venue_quote(
            MarketDataQuote(
                venue="binance",
                symbol="BTC-USD",
                bid=49_900.0,
                ask=50_100.0,
                bid_size=5.0,
                ask_size=5.0,
                timestamp=time.time(),
            )
        )
        aggregator.add_venue_quote(
            MarketDataQuote(
                venue="coinbase",
                symbol="BTC-USD",
                bid=49_950.0,
                ask=50_050.0,
                bid_size=3.0,
                ask_size=3.0,
                timestamp=time.time(),
            )
        )

        # Get aggregated quote
        agg = aggregator.get_aggregated_quote("BTC-USD")
        self.assertIsNotNone(agg)
        self.assertEqual(agg.best_bid, 49_950.0)
        self.assertEqual(agg.best_ask, 50_050.0)

        # Set up order router with venues
        router = VenueOrderRouter()
        router.add_venue(
            Venue(
                name="binance",
                quote=VenueQuote(bid=49_900.0, ask=50_100.0, bid_size=5.0, ask_size=5.0),
                latency_ms=10.0,
                fee_bps=5.0,
            )
        )
        router.add_venue(
            Venue(
                name="coinbase",
                quote=VenueQuote(bid=49_950.0, ask=50_050.0, bid_size=3.0, ask_size=3.0),
                latency_ms=15.0,
                fee_bps=3.0,
            )
        )

        # Route a buy order
        order = {"symbol": "BTC-USD", "side": RouterOrderSide.BUY, "quantity": 2.0}
        decision = router.route(order)

        # Binance wins due to lower latency and higher liquidity despite slightly worse price
        self.assertEqual(decision.venue_name, "binance")
        self.assertGreater(decision.score, 0.0)

        # Settle the fill
        position_mgr = VenuePositionManager(
            instruments=["BTC-USD"],
            venues=["coinbase"],
        )
        fill = _make_position_fill("BTC-USD", "coinbase", 2.0, 50_050.0)
        position_mgr.apply_fill(fill)

        pos = position_mgr.get_position("BTC-USD", "coinbase")
        self.assertIsNotNone(pos)
        self.assertEqual(pos.quantity, 2.0)
        self.assertEqual(pos.avg_price, 50_050.0)


# ---------------------------------------------------------------------------
# Test 3: Risk Check Pipeline — Pre-Trade Risk → Position Limit → Approval
# ---------------------------------------------------------------------------


class TestRiskCheckPipeline(unittest.TestCase):
    """Test pre-trade risk and position limit enforcement."""

    def test_order_passes_risk_and_position_checks(self) -> None:
        """Test a valid order passes all risk checks."""
        risk_engine = PreTradeRiskEngine(
            rules=RiskRules(
                max_order_value=1_000_000.0,
                max_position_size=100.0,
                max_order_quantity=50.0,
            )
        )
        limit_enforcer = PositionLimitEnforcer(
            default_limits=PositionLimit(
                max_position=100.0,
                max_exposure=10_000_000.0,
            )
        )

        # Check pre-trade risk
        result = risk_engine.check_order(
            symbol="BTC-USD",
            side=RiskOrderSide.BUY,
            quantity=10.0,
            price=50_000.0,
        )
        self.assertTrue(result.passed, f"Risk check failed: {result.violations}")

        # Check position limit
        decision = limit_enforcer.check_order(
            symbol="BTC-USD",
            venue="binance",
            account="acct-1",
            quantity=10.0,
            price=50_000.0,
        )
        self.assertEqual(decision.action, EnforcementAction.PASS)

    def test_order_rejected_by_risk_engine(self) -> None:
        """Test an order that exceeds risk limits is rejected."""
        risk_engine = PreTradeRiskEngine(
            rules=RiskRules(
                max_order_value=100_000.0,
                max_order_quantity=5.0,
            )
        )

        result = risk_engine.check_order(
            symbol="BTC-USD",
            side=RiskOrderSide.BUY,
            quantity=10.0,
            price=50_000.0,
        )
        self.assertFalse(result.passed)
        self.assertTrue(any("ORDER_VALUE_EXCEEDS_MAX" in v for v in result.violations))
        self.assertTrue(any("QUANTITY_EXCEEDS_MAX" in v for v in result.violations))

    def test_order_blocked_by_position_limit(self) -> None:
        """Test an order that exceeds position limit is blocked."""
        limit_enforcer = PositionLimitEnforcer(
            default_limits=PositionLimit(
                max_position=50.0,
                max_exposure=2_000_000.0,
            )
        )

        # First order: 30 units at 50k = 1.5M exposure — should pass
        decision1 = limit_enforcer.check_order(
            symbol="BTC-USD",
            venue="binance",
            account="acct-1",
            quantity=30.0,
            price=50_000.0,
        )
        self.assertEqual(decision1.action, EnforcementAction.PASS)

        # Update position tracker
        limit_enforcer.update_position("BTC-USD", "binance", "acct-1", 30.0, 50_000.0)

        # Second order: another 30 units — projected 60 > 50 max — should block
        decision2 = limit_enforcer.check_order(
            symbol="BTC-USD",
            venue="binance",
            account="acct-1",
            quantity=30.0,
            price=50_000.0,
        )
        self.assertEqual(decision2.action, EnforcementAction.BLOCK)


# ---------------------------------------------------------------------------
# Test 4: Kill Switch Pipeline — Risk Breach → Kill Switch → Order Rejection
# ---------------------------------------------------------------------------


class TestKillSwitchPipeline(unittest.TestCase):
    """Test kill switch integration with trading pipeline."""

    def test_kill_switch_blocks_new_orders(self) -> None:
        """Test that active kill switch prevents new orders."""
        risk_engine = PreTradeRiskEngine()

        # Normal order passes
        result = risk_engine.check_order(
            symbol="BTC-USD",
            side=RiskOrderSide.BUY,
            quantity=1.0,
            price=50_000.0,
        )
        self.assertTrue(result.passed)

        # Trigger kill switch
        risk_engine.trigger_kill_switch()

        # Now order should be rejected
        result = risk_engine.check_order(
            symbol="BTC-USD",
            side=RiskOrderSide.BUY,
            quantity=1.0,
            price=50_000.0,
        )
        self.assertFalse(result.passed)
        self.assertIn("KILL_SWITCH_ACTIVE", result.violations)

    def test_kill_switch_cancels_venue_orders(self) -> None:
        """Test kill switch cancels orders at registered venues."""

        class MockVenue(KillSwitchVenue):
            def __init__(self, name: str):
                self.name = name
                self._orders = [f"{name}-order-{i}" for i in range(3)]

            def cancel_all_orders(self) -> list[str]:
                cancelled = list(self._orders)
                self._orders.clear()
                return cancelled

            def get_open_orders(self) -> list[dict]:
                return [{"id": oid} for oid in self._orders]

        venue_a = MockVenue("binance")
        venue_b = MockVenue("coinbase")

        kill_switch = KillSwitch()
        kill_switch.register_venue(venue_a)
        kill_switch.register_venue(venue_b)

        # Trigger kill switch
        result = kill_switch.trigger(triggered_by="risk_breach")
        self.assertEqual(result["cancelled_count"], 6)
        self.assertEqual(kill_switch.status, KillSwitchStatus.ACTIVE)

        # Verify orders were cancelled
        self.assertEqual(len(venue_a.get_open_orders()), 0)
        self.assertEqual(len(venue_b.get_open_orders()), 0)

        # New orders should be rejected
        self.assertTrue(kill_switch.should_reject_order())

        # Reset and verify
        kill_switch.reset()
        self.assertFalse(kill_switch.should_reject_order())


# ---------------------------------------------------------------------------
# Test 5: Multi-Venue Execution — Quotes → Route → Execute → Aggregate
# ---------------------------------------------------------------------------


class TestMultiVenueExecution(unittest.TestCase):
    """Test multi-venue execution and position aggregation."""

    def test_multi_venue_position_aggregation(self) -> None:
        """Test positions across multiple venues are aggregated correctly."""
        position_mgr = VenuePositionManager(
            instruments=["BTC-USD", "ETH-USD"],
            venues=["binance", "coinbase"],
        )

        # Execute at binance
        fill1 = _make_position_fill("BTC-USD", "binance", 1.0, 50_000.0)
        position_mgr.apply_fill(fill1)

        # Execute at coinbase
        fill2 = _make_position_fill("BTC-USD", "coinbase", 2.0, 50_100.0)
        position_mgr.apply_fill(fill2)

        # Different symbol
        fill3 = _make_position_fill("ETH-USD", "binance", 10.0, 3_000.0)
        position_mgr.apply_fill(fill3)

        # Check per-venue positions
        pos_binance = position_mgr.get_position("BTC-USD", "binance")
        pos_coinbase = position_mgr.get_position("BTC-USD", "coinbase")
        self.assertEqual(pos_binance.quantity, 1.0)
        self.assertEqual(pos_coinbase.quantity, 2.0)

        # Check aggregated positions
        self.assertEqual(position_mgr.get_net_position("BTC-USD"), 3.0)
        self.assertEqual(position_mgr.get_net_position("ETH-USD"), 10.0)

        # Check gross exposure
        gross = position_mgr.get_gross_exposure("BTC-USD")
        expected = 1.0 * 50_000.0 + 2.0 * 50_100.0
        self.assertEqual(gross, expected)

        # Update market price and check P&L
        position_mgr.update_market_price("BTC-USD", 51_000.0)
        unrealized = position_mgr.get_unrealized_pnl("BTC-USD")
        expected_unrealized = 1.0 * (51_000.0 - 50_000.0) + 2.0 * (51_000.0 - 50_100.0)
        self.assertEqual(unrealized, expected_unrealized)


# ---------------------------------------------------------------------------
# Test 6: Session Failover — Failure → Failover → Continue Trading
# ---------------------------------------------------------------------------


class TestSessionFailover(unittest.TestCase):
    """Test session failover during trading."""

    def test_failover_to_backup_venue(self) -> None:
        """Test trading continues after venue failover."""
        session_mgr = SessionManager()
        session_mgr.add_venue("binance", "binance.com", 443, weight=2)
        session_mgr.add_venue("coinbase", "coinbase.com", 443, weight=1)

        # Acquire session at binance
        session1 = session_mgr.acquire_session("binance")
        self.assertIsNotNone(session1)
        self.assertEqual(session1.venue_id, "binance")

        # Simulate binance failure
        session_mgr.mark_failed("binance")

        # Should not be able to acquire binance session
        session2 = session_mgr.acquire_session("binance")
        self.assertIsNone(session2)

        # Failover should route to coinbase
        failover_session = session_mgr.failover("binance")
        self.assertEqual(failover_session.venue_id, "coinbase")

        # Verify binance is marked failed
        stats = session_mgr.get_session_stats("binance")
        self.assertFalse(stats["is_active"])

        # Release and recover
        session_mgr.release_session("coinbase")
        session_mgr.mark_recovered("binance")
        stats = session_mgr.get_session_stats("binance")
        self.assertTrue(stats["is_active"])


# ---------------------------------------------------------------------------
# Test 7: Market Data to Execution — Feed → Normalize → Aggregate → Trade
# ---------------------------------------------------------------------------


class TestMarketDataToExecution(unittest.TestCase):
    """Test market data flowing from feed to execution decision."""

    def test_normalized_feed_to_aggregated_quote(self) -> None:
        """Test raw feed normalization and aggregation."""
        normalizer = FeedNormalizer()

        # Raw ticks from different venues
        raw_ticks = [
            {"symbol": "BTC-USD", "price": 50_000.0, "size": 1.0, "side": "buy", "timestamp": 1_700_000_000},
            {"sym": "BTC-USD", "px": 50_010.0, "sz": 2.0, "sd": "sell", "ts": 1_700_000_001},
            {"ticker": "BTC-USD", "last": 49_990.0, "volume": 1.5, "side": "buy", "epoch_ms": 1_700_000_002_000},
        ]

        # Normalize
        normalized = normalizer.normalize_batch(raw_ticks)
        self.assertEqual(len(normalized), 3)
        self.assertEqual(normalized[0].symbol, "BTC-USD")
        self.assertEqual(normalized[1].symbol, "BTC-USD")
        self.assertEqual(normalized[2].symbol, "BTC-USD")

        # Aggregate
        aggregator = VenueMarketDataAggregator()
        for tick in normalized:
            aggregator.add_venue_quote(
                MarketDataQuote(
                    venue=tick.venue,
                    symbol=tick.symbol,
                    bid=tick.price - 10.0,
                    ask=tick.price + 10.0,
                    bid_size=tick.quantity,
                    ask_size=tick.quantity,
                    timestamp=float(tick.timestamp),
                )
            )

        agg = aggregator.get_aggregated_quote("BTC-USD")
        self.assertIsNotNone(agg)
        self.assertGreater(agg.best_bid, 0)
        self.assertGreater(agg.best_ask, 0)
        self.assertGreaterEqual(agg.best_ask, agg.best_bid)


# ---------------------------------------------------------------------------
# Test 8: Position Limit Enforcement — Updates → Checks → Actions
# ---------------------------------------------------------------------------


class TestPositionLimitEnforcement(unittest.TestCase):
    """Test position limit enforcement across symbols and venues."""

    def test_symbol_specific_limits(self) -> None:
        """Test symbol-specific limits override defaults."""
        enforcer = PositionLimitEnforcer(
            default_limits=PositionLimit(max_position=100.0)
        )
        # Set tighter limit for BTC-USD
        enforcer.set_symbol_limit("BTC-USD", PositionLimit(max_position=10.0))

        # BTC-USD order within default but over symbol limit
        decision = enforcer.check_order(
            symbol="BTC-USD",
            venue="binance",
            account="acct-1",
            quantity=15.0,
            price=50_000.0,
        )
        self.assertEqual(decision.action, EnforcementAction.BLOCK)

        # ETH-USD order within default limit
        decision = enforcer.check_order(
            symbol="ETH-USD",
            venue="binance",
            account="acct-1",
            quantity=50.0,
            price=3_000.0,
        )
        self.assertEqual(decision.action, EnforcementAction.PASS)

    def test_venue_specific_limits(self) -> None:
        """Test venue-specific limits are enforced."""
        enforcer = PositionLimitEnforcer(
            default_limits=PositionLimit(max_venue_position=100.0)
        )
        # Set tighter limit for binance
        enforcer.set_venue_limit("binance", PositionLimit(max_venue_position=20.0))

        # Update position at binance
        enforcer.update_position("BTC-USD", "binance", "acct-1", 15.0, 50_000.0)

        # Another order at binance — projected 25 > 20
        decision = enforcer.check_order(
            symbol="ETH-USD",
            venue="binance",
            account="acct-1",
            quantity=10.0,
            price=3_000.0,
        )
        self.assertEqual(decision.action, EnforcementAction.BLOCK)

        # Same order at coinbase — should pass
        decision = enforcer.check_order(
            symbol="ETH-USD",
            venue="coinbase",
            account="acct-1",
            quantity=10.0,
            price=3_000.0,
        )
        self.assertEqual(decision.action, EnforcementAction.PASS)


# ---------------------------------------------------------------------------
# Test 9: End-to-End Settlement — Multiple Fills → Position → Settlement P&L
# ---------------------------------------------------------------------------


class TestEndToEndSettlement(unittest.TestCase):
    """Test settlement with multiple fills and position changes."""

    def test_partial_fills_and_settlement(self) -> None:
        """Test partial fills leading to correct settlement P&L."""
        position_mgr = VenuePositionManager(
            instruments=["BTC-USD"],
            venues=["binance"],
        )

        # Buy 1 BTC at 50,000
        fill1 = _make_position_fill("BTC-USD", "binance", 1.0, 50_000.0)
        position_mgr.apply_fill(fill1)

        # Buy 2 more BTC at 51,000
        fill2 = _make_position_fill("BTC-USD", "binance", 2.0, 51_000.0)
        position_mgr.apply_fill(fill2)

        # Position should be 3 BTC at avg price
        pos = position_mgr.get_position("BTC-USD", "binance")
        self.assertEqual(pos.quantity, 3.0)
        expected_avg = (1.0 * 50_000.0 + 2.0 * 51_000.0) / 3.0
        self.assertAlmostEqual(pos.avg_price, expected_avg, places=2)

        # Sell 1 BTC at 52,000 — realize P&L
        fill3 = _make_position_fill("BTC-USD", "binance", -1.0, 52_000.0)
        position_mgr.apply_fill(fill3)

        realized = position_mgr.get_realized_pnl("BTC-USD")
        expected_realized = 1.0 * (52_000.0 - expected_avg)
        self.assertAlmostEqual(realized, expected_realized, places=2)

        # Remaining position: 2 BTC
        pos = position_mgr.get_position("BTC-USD", "binance")
        self.assertEqual(pos.quantity, 2.0)

        # Mark to market
        position_mgr.update_market_price("BTC-USD", 53_000.0)
        unrealized = position_mgr.get_unrealized_pnl("BTC-USD")
        expected_unrealized = 2.0 * (53_000.0 - expected_avg)
        self.assertAlmostEqual(unrealized, expected_unrealized, places=2)

        total_pnl = position_mgr.get_total_pnl("BTC-USD")
        self.assertAlmostEqual(total_pnl, realized + unrealized, places=2)


# ---------------------------------------------------------------------------
# Test 10: Order Book Matching Pipeline — Orders → Trades → Fills → Positions
# ---------------------------------------------------------------------------


class TestOrderBookMatchingPipeline(unittest.TestCase):
    """Test order book matching generating fills that flow to positions."""

    def test_matching_engine_to_position_manager(self) -> None:
        """Test matched trades flow correctly to position manager."""
        book = OrderBook()
        position_mgr = VenuePositionManager(
            instruments=["ETH-USD"],
            venues=["binance"],
        )

        # Add sell orders to book
        book.add_order(_make_order("sell-1", Side.SELL, 3_000.0, 5, timestamp=1))
        book.add_order(_make_order("sell-2", Side.SELL, 3_010.0, 3, timestamp=2))

        # Buy order matches against both sell orders
        buy = _make_order("buy-1", Side.BUY, 3_010.0, 7, timestamp=3)
        trades = book.add_order(buy)

        # Should have 2 trades (5 @ 3000 + 2 @ 3010)
        self.assertEqual(len(trades), 2)
        self.assertEqual(trades[0].quantity, 5)
        self.assertEqual(trades[0].price, 3_000.0)
        self.assertEqual(trades[1].quantity, 2)
        self.assertEqual(trades[1].price, 3_010.0)

        # Apply fills to position manager
        for trade in trades:
            fill = _make_position_fill("ETH-USD", "binance", trade.quantity, trade.price)
            position_mgr.apply_fill(fill)

        pos = position_mgr.get_position("ETH-USD", "binance")
        self.assertEqual(pos.quantity, 7.0)
        expected_avg = (5 * 3_000.0 + 2 * 3_010.0) / 7.0
        self.assertAlmostEqual(pos.avg_price, expected_avg, places=2)


# ---------------------------------------------------------------------------
# Test 11: Execution Quality Analysis — Fills → Slippage → Venue Comparison
# ---------------------------------------------------------------------------


class TestExecutionQualityAnalysis(unittest.TestCase):
    """Test execution quality analysis across venues."""

    def test_slippage_analysis_across_venues(self) -> None:
        """Test slippage analysis comparing venues."""
        analyzer = ExecutionAnalyzer()

        # Binance fills — small slippage
        analyzer.add_fill(
            _make_execution_fill("binance", "BTC-USD", "buy", 1.0, 50_010.0, 50_000.0, fees=25.0)
        )
        analyzer.add_fill(
            _make_execution_fill("binance", "BTC-USD", "sell", 1.0, 49_990.0, 50_000.0, fees=25.0)
        )

        # Coinbase fills — larger slippage
        analyzer.add_fill(
            _make_execution_fill("coinbase", "BTC-USD", "buy", 1.0, 50_050.0, 50_000.0, fees=15.0)
        )
        analyzer.add_fill(
            _make_execution_fill("coinbase", "BTC-USD", "sell", 1.0, 49_950.0, 50_000.0, fees=15.0)
        )

        # Venue performance
        perf = analyzer.venue_performance()
        self.assertIn("binance", perf)
        self.assertIn("coinbase", perf)

        # Binance should have lower slippage
        self.assertLess(
            perf["binance"].avg_slippage_bps,
            perf["coinbase"].avg_slippage_bps,
        )

        # Best venue should be binance
        best = analyzer.best_venue()
        self.assertEqual(best, "binance")

        # Worst venue should be coinbase
        worst = analyzer.worst_venue()
        self.assertEqual(worst, "coinbase")

        # Total fees
        total_fees = analyzer.total_fees()
        self.assertEqual(total_fees, 80.0)  # 25*2 + 15*2

        # Total notional
        total_notional = analyzer.total_notional()
        expected = 1.0 * 50_010.0 + 1.0 * 49_990.0 + 1.0 * 50_050.0 + 1.0 * 49_950.0
        self.assertEqual(total_notional, expected)


# ---------------------------------------------------------------------------
# Test 12: Feed to Trading Pipeline — Raw → Normalize → Aggregate → Decide
# ---------------------------------------------------------------------------


class TestFeedToTradingPipeline(unittest.TestCase):
    """Test complete feed-to-trading pipeline."""

    def test_arbitrage_detection_from_normalized_feed(self) -> None:
        """Test arbitrage detection from normalized multi-venue feed."""
        normalizer = FeedNormalizer()
        aggregator = VenueMarketDataAggregator()

        # Simulate raw feeds with price discrepancy
        raw_feeds = [
            # Binance: BTC at 50,000
            {"symbol": "BTC-USD", "p": 50_000.0, "q": 5.0, "S": "buy", "T": 1_700_000_000},
            # Coinbase: BTC at 50,100 — 100 higher
            {"product_id": "BTC-USD", "price": 50_100.0, "size": 3.0, "side": "sell", "time": 1_700_000_001},
        ]

        normalized = normalizer.normalize_batch(raw_feeds)
        self.assertEqual(len(normalized), 2)

        # Add to aggregator
        for tick in normalized:
            aggregator.add_venue_quote(
                MarketDataQuote(
                    venue=tick.venue,
                    symbol=tick.symbol,
                    bid=tick.price - 5.0,
                    ask=tick.price + 5.0,
                    bid_size=tick.quantity,
                    ask_size=tick.quantity,
                    timestamp=float(tick.timestamp),
                )
            )

        # Detect arbitrage
        arb = aggregator.detect_arbitrage("BTC-USD", min_spread=50.0)
        self.assertIsNotNone(arb)
        self.assertEqual(arb.symbol, "BTC-USD")
        self.assertGreater(arb.profit_per_unit, 0)


# ---------------------------------------------------------------------------
# Test 13: Pre-Trade to Settlement — Risk → Execute → Settle → Verify
# ---------------------------------------------------------------------------


class TestPreTradeToSettlement(unittest.TestCase):
    """Test pre-trade risk through settlement."""

    def test_risk_approved_order_flows_to_settlement(self) -> None:
        """Test a risk-approved order flows through to settlement."""
        risk_engine = PreTradeRiskEngine(
            rules=RiskRules(
                max_order_value=1_000_000.0,
                max_position_size=10.0,
            )
        )
        position_mgr = VenuePositionManager(
            instruments=["BTC-USD"],
            venues=["binance"],
        )

        # Submit order
        result = risk_engine.check_order(
            symbol="BTC-USD",
            side=RiskOrderSide.BUY,
            quantity=5.0,
            price=50_000.0,
        )
        self.assertTrue(result.passed)

        # Execute and settle
        fill = _make_position_fill("BTC-USD", "binance", 5.0, 50_000.0)
        position_mgr.apply_fill(fill)

        # Update risk engine position
        risk_engine.update_position("BTC-USD", 5.0)

        # Verify settlement
        pos = position_mgr.get_position("BTC-USD", "binance")
        self.assertEqual(pos.quantity, 5.0)
        self.assertEqual(pos.avg_price, 50_000.0)

        # Another order within limits
        result = risk_engine.check_order(
            symbol="BTC-USD",
            side=RiskOrderSide.BUY,
            quantity=3.0,
            price=50_000.0,
        )
        self.assertTrue(result.passed)

        # Execute second fill
        fill2 = _make_position_fill("BTC-USD", "binance", 3.0, 50_100.0)
        position_mgr.apply_fill(fill2)
        risk_engine.update_position("BTC-USD", 3.0)

        # Verify aggregated position
        pos = position_mgr.get_position("BTC-USD", "binance")
        self.assertEqual(pos.quantity, 8.0)
        expected_avg = (5.0 * 50_000.0 + 3.0 * 50_100.0) / 8.0
        self.assertAlmostEqual(pos.avg_price, expected_avg, places=2)


# ---------------------------------------------------------------------------
# Test 14: Multi-Symbol Portfolio — Multiple Symbols → Track → Portfolio P&L
# ---------------------------------------------------------------------------


class TestMultiSymbolPortfolio(unittest.TestCase):
    """Test multi-symbol portfolio tracking and P&L."""

    def test_portfolio_pnl_across_symbols(self) -> None:
        """Test portfolio P&L across multiple symbols."""
        position_mgr = VenuePositionManager(
            instruments=["BTC-USD", "ETH-USD", "SOL-USD"],
            venues=["binance", "coinbase"],
        )

        # Execute trades across symbols and venues
        fills = [
            _make_position_fill("BTC-USD", "binance", 1.0, 50_000.0),
            _make_position_fill("BTC-USD", "coinbase", 2.0, 50_100.0),
            _make_position_fill("ETH-USD", "binance", 10.0, 3_000.0),
            _make_position_fill("ETH-USD", "coinbase", 5.0, 3_010.0),
            _make_position_fill("SOL-USD", "binance", 100.0, 100.0),
        ]
        for fill in fills:
            position_mgr.apply_fill(fill)

        # Update market prices
        position_mgr.update_market_price("BTC-USD", 51_000.0)
        position_mgr.update_market_price("ETH-USD", 3_100.0)
        position_mgr.update_market_price("SOL-USD", 105.0)

        # Check per-symbol P&L
        btc_pnl = position_mgr.get_unrealized_pnl("BTC-USD")
        eth_pnl = position_mgr.get_unrealized_pnl("ETH-USD")
        sol_pnl = position_mgr.get_unrealized_pnl("SOL-USD")

        self.assertGreater(btc_pnl, 0)
        self.assertGreater(eth_pnl, 0)
        self.assertGreater(sol_pnl, 0)

        # Check total exposure
        gross = position_mgr.get_gross_exposure()
        expected_gross = (
            1.0 * 50_000.0 + 2.0 * 50_100.0 +
            10.0 * 3_000.0 + 5.0 * 3_010.0 +
            100.0 * 100.0
        )
        self.assertEqual(gross, expected_gross)

        # Check net exposure
        net = position_mgr.get_net_exposure()
        self.assertIsNotNone(net)


# ---------------------------------------------------------------------------
# Test 15: Venue Failover Pipeline — Failure → Failover → Continue
# ---------------------------------------------------------------------------


class TestVenueFailoverPipeline(unittest.TestCase):
    """Test venue failover during active trading."""

    def test_failover_maintains_trading_capacity(self) -> None:
        """Test failover maintains trading capacity."""
        session_mgr = SessionManager()
        session_mgr.add_venue("binance", "binance.com", 443, weight=3, max_connections=5)
        session_mgr.add_venue("coinbase", "coinbase.com", 443, weight=2, max_connections=5)
        session_mgr.add_venue("kraken", "kraken.com", 443, weight=1, max_connections=5)

        # Acquire sessions up to capacity
        sessions = []
        for _ in range(5):
            s = session_mgr.acquire_session("binance")
            if s:
                sessions.append(s)

        # Binance should be at capacity
        self.assertIsNone(session_mgr.acquire_session("binance"))

        # Failover from binance
        failover = session_mgr.failover("binance")
        self.assertIn(failover.venue_id, ["coinbase", "kraken"])

        # Release binance sessions
        for s in sessions:
            session_mgr.release_session(s.venue_id)

        # Recover binance
        session_mgr.mark_recovered("binance")

        # Should be able to acquire binance again
        s = session_mgr.acquire_session("binance")
        self.assertIsNotNone(s)


# ---------------------------------------------------------------------------
# Test 16: Complete Trading Day — Full Pipeline Simulation
# ---------------------------------------------------------------------------


class TestCompleteTradingDay(unittest.TestCase):
    """Test a complete trading day simulation with all components."""

    def test_full_trading_day_simulation(self) -> None:
        """Simulate a full trading day with all pipeline components."""
        # Initialize all components
        book = OrderBook()
        risk_engine = PreTradeRiskEngine(
            rules=RiskRules(
                max_order_value=5_000_000.0,
                max_position_size=100.0,
                max_order_quantity=50.0,
            )
        )
        limit_enforcer = PositionLimitEnforcer(
            default_limits=PositionLimit(
                max_position=100.0,
                max_exposure=10_000_000.0,
            )
        )
        position_mgr = VenuePositionManager(
            instruments=["BTC-USD", "ETH-USD"],
            venues=["binance", "coinbase"],
        )
        analyzer = ExecutionAnalyzer()
        aggregator = VenueMarketDataAggregator()
        router = VenueOrderRouter()

        # Set up venues for routing
        router.add_venue(
            Venue(
                name="binance",
                quote=VenueQuote(bid=49_900.0, ask=50_100.0, bid_size=10.0, ask_size=10.0),
                latency_ms=10.0,
                fee_bps=5.0,
            )
        )
        router.add_venue(
            Venue(
                name="coinbase",
                quote=VenueQuote(bid=49_950.0, ask=50_050.0, bid_size=8.0, ask_size=8.0),
                latency_ms=15.0,
                fee_bps=3.0,
            )
        )

        # Morning: Add liquidity to order book
        book.add_order(_make_order("sell-btc-1", Side.SELL, 50_100.0, 5, timestamp=1))
        book.add_order(_make_order("sell-btc-2", Side.SELL, 50_200.0, 3, timestamp=2))
        book.add_order(_make_order("sell-eth-1", Side.SELL, 3_050.0, 20, timestamp=3))

        # Morning: Execute buy orders
        # BTC buy
        result = risk_engine.check_order(
            symbol="BTC-USD",
            side=RiskOrderSide.BUY,
            quantity=5.0,
            price=50_100.0,
        )
        self.assertTrue(result.passed)

        decision = limit_enforcer.check_order(
            symbol="BTC-USD",
            venue="binance",
            account="acct-1",
            quantity=5.0,
            price=50_100.0,
        )
        self.assertEqual(decision.action, EnforcementAction.PASS)

        # Match in order book
        buy_btc = _make_order("buy-btc-1", Side.BUY, 50_100.0, 5, timestamp=4)
        trades = book.add_order(buy_btc)
        self.assertEqual(len(trades), 1)

        # Settle
        for trade in trades:
            fill = _make_position_fill("BTC-USD", "binance", trade.quantity, trade.price)
            position_mgr.apply_fill(fill)
            analyzer.add_fill(
                _make_execution_fill(
                    "binance", "BTC-USD", "buy",
                    trade.quantity, trade.price, 50_000.0,
                )
            )

        # ETH buy
        result = risk_engine.check_order(
            symbol="ETH-USD",
            side=RiskOrderSide.BUY,
            quantity=20.0,
            price=3_050.0,
        )
        self.assertTrue(result.passed)

        buy_eth = _make_order("buy-eth-1", Side.BUY, 3_050.0, 20, timestamp=5)
        trades = book.add_order(buy_eth)
        self.assertEqual(len(trades), 1)

        for trade in trades:
            fill = _make_position_fill("ETH-USD", "binance", trade.quantity, trade.price)
            position_mgr.apply_fill(fill)

        # Mid-day: Route a new order
        order = {"symbol": "BTC-USD", "side": RouterOrderSide.BUY, "quantity": 2.0}
        decision = router.route(order)
        self.assertIn(decision.venue_name, ["binance", "coinbase"])

        # Update market data
        aggregator.add_venue_quote(
            MarketDataQuote(
                venue="binance",
                symbol="BTC-USD",
                bid=50_000.0,
                ask=50_200.0,
                bid_size=10.0,
                ask_size=10.0,
                timestamp=time.time(),
            )
        )

        agg = aggregator.get_aggregated_quote("BTC-USD")
        self.assertIsNotNone(agg)

        # Afternoon: Close BTC position
        btc_pos = position_mgr.get_position("BTC-USD", "binance")
        self.assertIsNotNone(btc_pos)

        close_fill = _make_position_fill(
            "BTC-USD", "binance", -btc_pos.quantity, 50_150.0
        )
        position_mgr.apply_fill(close_fill)

        # Verify realized P&L
        realized = position_mgr.get_realized_pnl("BTC-USD")
        self.assertGreater(realized, 0)

        # End of day: Verify portfolio state
        # BTC should be flat
        btc_pos = position_mgr.get_position("BTC-USD", "binance")
        self.assertIsNone(btc_pos)

        # ETH should still be open
        eth_pos = position_mgr.get_position("ETH-USD", "binance")
        self.assertIsNotNone(eth_pos)
        self.assertEqual(eth_pos.quantity, 20.0)

        # Check execution quality
        perf = analyzer.venue_performance()
        self.assertIn("binance", perf)
        self.assertGreater(perf["binance"].total_fills, 0)

        # Update market prices for final P&L
        position_mgr.update_market_price("ETH-USD", 3_100.0)
        eth_unrealized = position_mgr.get_unrealized_pnl("ETH-USD")
        self.assertEqual(eth_unrealized, 20.0 * (3_100.0 - 3_050.0))


# ---------------------------------------------------------------------------
# Test 17: Order Cancellation Pipeline — Add → Cancel → Verify
# ---------------------------------------------------------------------------


class TestOrderCancellationPipeline(unittest.TestCase):
    """Test order cancellation in the trading pipeline."""

    def test_cancel_order_updates_position_correctly(self) -> None:
        """Test cancelling an order and verifying position consistency."""
        book = OrderBook()
        position_mgr = VenuePositionManager(
            instruments=["BTC-USD"],
            venues=["binance"],
        )

        # Add buy order to book
        buy = _make_order("buy-1", Side.BUY, 50_000.0, 5, timestamp=1)
        book.add_order(buy)

        # Verify order is in book
        self.assertEqual(book.best_bid, 50_000.0)

        # Cancel the order
        book.cancel_order("buy-1")

        # Verify book is empty
        self.assertIsNone(book.best_bid)

        # Position should be unaffected (order was never filled)
        pos = position_mgr.get_position("BTC-USD", "binance")
        self.assertIsNone(pos)


# ---------------------------------------------------------------------------
# Test 18: Load Balancing Pipeline — Weighted Round-Robin
# ---------------------------------------------------------------------------


class TestLoadBalancingPipeline(unittest.TestCase):
    """Test load balancing across venues."""

    def test_weighted_round_robin_distribution(self) -> None:
        """Test weighted round-robin distributes load correctly."""
        session_mgr = SessionManager()
        session_mgr.add_venue("binance", "binance.com", 443, weight=3, max_connections=100)
        session_mgr.add_venue("coinbase", "coinbase.com", 443, weight=1, max_connections=100)

        # Acquire sessions — should get binance 3x more often
        venue_counts = {"binance": 0, "coinbase": 0}
        for _ in range(8):
            s = session_mgr.acquire_session()
            if s:
                venue_counts[s.venue_id] += 1

        # With weight 3:1, expect roughly 6:2 ratio
        self.assertGreater(venue_counts["binance"], venue_counts["coinbase"])
        self.assertEqual(venue_counts["binance"] + venue_counts["coinbase"], 8)


if __name__ == "__main__":
    unittest.main()
