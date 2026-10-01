"""Tests for Order Book Manager — TDD enforced."""
import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from order_book.manager import OrderBook, Order, OrderSide, OrderType


class TestOrderCreation:
    """Test order creation and basic properties."""

    def test_create_buy_limit_order(self):
        order = Order(id="1", side=OrderSide.BUY, price=100.0, quantity=10)
        assert order.id == "1"
        assert order.side == OrderSide.BUY
        assert order.price == 100.0
        assert order.quantity == 10
        assert order.filled == 0
        assert order.remaining == 10

    def test_create_sell_limit_order(self):
        order = Order(id="2", side=OrderSide.SELL, price=105.0, quantity=5)
        assert order.side == OrderSide.SELL
        assert order.price == 105.0
        assert order.quantity == 5

    def test_order_with_market_type(self):
        order = Order(id="3", side=OrderSide.BUY, price=0, quantity=10, order_type=OrderType.MARKET)
        assert order.order_type == OrderType.MARKET

    def test_order_timestamp_auto_set(self):
        order = Order(id="4", side=OrderSide.BUY, price=100.0, quantity=1)
        assert order.timestamp > 0

    def test_order_custom_timestamp(self):
        order = Order(id="5", side=OrderSide.BUY, price=100.0, quantity=1, timestamp=999)
        assert order.timestamp == 999


class TestOrderBookBasicOperations:
    """Test basic order book operations."""

    def test_add_single_order(self):
        ob = OrderBook()
        order = Order(id="1", side=OrderSide.BUY, price=100.0, quantity=10)
        ob.add_order(order)
        assert ob.get_order("1") is not None
        assert ob.get_order("1").quantity == 10

    def test_add_multiple_orders_same_side(self):
        ob = OrderBook()
        ob.add_order(Order(id="1", side=OrderSide.BUY, price=100.0, quantity=10))
        ob.add_order(Order(id="2", side=OrderSide.BUY, price=99.0, quantity=5))
        assert ob.get_order("1") is not None
        assert ob.get_order("2") is not None

    def test_cancel_order(self):
        ob = OrderBook()
        ob.add_order(Order(id="1", side=OrderSide.BUY, price=100.0, quantity=10))
        ob.cancel_order("1")
        assert ob.get_order("1") is None

    def test_cancel_nonexistent_order_raises(self):
        ob = OrderBook()
        with pytest.raises(KeyError):
            ob.cancel_order("nonexistent")

    def test_get_best_bid_empty(self):
        ob = OrderBook()
        assert ob.get_best_bid() is None

    def test_get_best_ask_empty(self):
        ob = OrderBook()
        assert ob.get_best_ask() is None

    def test_get_best_bid(self):
        ob = OrderBook()
        ob.add_order(Order(id="1", side=OrderSide.BUY, price=100.0, quantity=10))
        ob.add_order(Order(id="2", side=OrderSide.BUY, price=101.0, quantity=5))
        assert ob.get_best_bid() == 101.0

    def test_get_best_ask(self):
        ob = OrderBook()
        ob.add_order(Order(id="1", side=OrderSide.SELL, price=105.0, quantity=10))
        ob.add_order(Order(id="2", side=OrderSide.SELL, price=104.0, quantity=5))
        assert ob.get_best_ask() == 104.0

    def test_get_spread(self):
        ob = OrderBook()
        ob.add_order(Order(id="1", side=OrderSide.BUY, price=100.0, quantity=10))
        ob.add_order(Order(id="2", side=OrderSide.SELL, price=105.0, quantity=5))
        assert ob.get_spread() == 5.0

    def test_get_spread_no_orders(self):
        ob = OrderBook()
        assert ob.get_spread() is None


class TestPriceTimePriority:
    """Test price-time priority matching."""

    def test_price_priority_buy_side(self):
        """Higher bid prices have priority."""
        ob = OrderBook()
        ob.add_order(Order(id="1", side=OrderSide.BUY, price=100.0, quantity=10))
        ob.add_order(Order(id="2", side=OrderSide.BUY, price=101.0, quantity=5))
        best_bid = ob.get_best_bid()
        assert best_bid == 101.0

    def test_price_priority_sell_side(self):
        """Lower ask prices have priority."""
        ob = OrderBook()
        ob.add_order(Order(id="1", side=OrderSide.SELL, price=105.0, quantity=10))
        ob.add_order(Order(id="2", side=OrderSide.SELL, price=104.0, quantity=5))
        best_ask = ob.get_best_ask()
        assert best_ask == 104.0

    def test_time_priority_same_price(self):
        """Earlier orders at same price have priority."""
        ob = OrderBook()
        ob.add_order(Order(id="1", side=OrderSide.BUY, price=100.0, quantity=10, timestamp=100))
        ob.add_order(Order(id="2", side=OrderSide.BUY, price=100.0, quantity=5, timestamp=200))
        # First order at price should be id "1"
        orders_at_price = ob.get_orders_at_price(OrderSide.BUY, 100.0)
        assert orders_at_price[0].id == "1"
        assert orders_at_price[1].id == "2"

    def test_time_priority_fifo_matching(self):
        """When matching, earlier orders fill first."""
        ob = OrderBook()
        ob.add_order(Order(id="1", side=OrderSide.SELL, price=100.0, quantity=5, timestamp=100))
        ob.add_order(Order(id="2", side=OrderSide.SELL, price=100.0, quantity=5, timestamp=200))
        ob.add_order(Order(id="3", side=OrderSide.BUY, price=100.0, quantity=7, timestamp=300))
        # Order 1 should be fully filled, order 2 partially
        assert ob.get_order("1").filled == 5
        assert ob.get_order("2").filled == 2


class TestOrderMatching:
    """Test order matching engine."""

    def test_exact_match(self):
        ob = OrderBook()
        ob.add_order(Order(id="1", side=OrderSide.SELL, price=100.0, quantity=10))
        ob.add_order(Order(id="2", side=OrderSide.BUY, price=100.0, quantity=10))
        assert ob.get_order("1").filled == 10
        assert ob.get_order("2").filled == 10

    def test_partial_fill_sell(self):
        ob = OrderBook()
        ob.add_order(Order(id="1", side=OrderSide.SELL, price=100.0, quantity=10))
        ob.add_order(Order(id="2", side=OrderSide.BUY, price=100.0, quantity=4))
        assert ob.get_order("1").filled == 4
        assert ob.get_order("1").remaining == 6
        assert ob.get_order("2").filled == 4

    def test_partial_fill_buy(self):
        ob = OrderBook()
        ob.add_order(Order(id="1", side=OrderSide.SELL, price=100.0, quantity=4))
        ob.add_order(Order(id="2", side=OrderSide.BUY, price=100.0, quantity=10))
        assert ob.get_order("1").filled == 4
        assert ob.get_order("2").filled == 4
        assert ob.get_order("2").remaining == 6

    def test_no_match_price_mismatch(self):
        ob = OrderBook()
        ob.add_order(Order(id="1", side=OrderSide.SELL, price=101.0, quantity=10))
        ob.add_order(Order(id="2", side=OrderSide.BUY, price=100.0, quantity=10))
        assert ob.get_order("1").filled == 0
        assert ob.get_order("2").filled == 0

    def test_multiple_fills(self):
        ob = OrderBook()
        ob.add_order(Order(id="1", side=OrderSide.SELL, price=100.0, quantity=5))
        ob.add_order(Order(id="2", side=OrderSide.SELL, price=100.0, quantity=5))
        ob.add_order(Order(id="3", side=OrderSide.BUY, price=100.0, quantity=8))
        assert ob.get_order("1").filled == 5
        assert ob.get_order("2").filled == 3
        assert ob.get_order("3").filled == 8

    def test_sweep_across_prices(self):
        ob = OrderBook()
        ob.add_order(Order(id="1", side=OrderSide.SELL, price=100.0, quantity=5))
        ob.add_order(Order(id="2", side=OrderSide.SELL, price=101.0, quantity=5))
        ob.add_order(Order(id="3", side=OrderSide.BUY, price=101.0, quantity=8))
        assert ob.get_order("1").filled == 5
        assert ob.get_order("2").filled == 3
        assert ob.get_order("3").filled == 8


class TestVolumeAndDepth:
    """Test volume and depth queries."""

    def test_get_volume_at_price(self):
        ob = OrderBook()
        ob.add_order(Order(id="1", side=OrderSide.BUY, price=100.0, quantity=10))
        ob.add_order(Order(id="2", side=OrderSide.BUY, price=100.0, quantity=5))
        ob.add_order(Order(id="3", side=OrderSide.BUY, price=99.0, quantity=3))
        assert ob.get_volume_at_price(OrderSide.BUY, 100.0) == 15

    def test_get_volume_at_price_empty(self):
        ob = OrderBook()
        assert ob.get_volume_at_price(OrderSide.BUY, 100.0) == 0

    def test_get_bid_depth(self):
        ob = OrderBook()
        ob.add_order(Order(id="1", side=OrderSide.BUY, price=100.0, quantity=10))
        ob.add_order(Order(id="2", side=OrderSide.BUY, price=99.0, quantity=5))
        depth = ob.get_bid_depth()
        assert depth[100.0] == 10
        assert depth[99.0] == 5

    def test_get_ask_depth(self):
        ob = OrderBook()
        ob.add_order(Order(id="1", side=OrderSide.SELL, price=105.0, quantity=10))
        ob.add_order(Order(id="2", side=OrderSide.SELL, price=106.0, quantity=5))
        depth = ob.get_ask_depth()
        assert depth[105.0] == 10
        assert depth[106.0] == 5

    def test_get_total_bid_volume(self):
        ob = OrderBook()
        ob.add_order(Order(id="1", side=OrderSide.BUY, price=100.0, quantity=10))
        ob.add_order(Order(id="2", side=OrderSide.BUY, price=99.0, quantity=5))
        assert ob.get_total_bid_volume() == 15

    def test_get_total_ask_volume(self):
        ob = OrderBook()
        ob.add_order(Order(id="1", side=OrderSide.SELL, price=105.0, quantity=10))
        ob.add_order(Order(id="2", side=OrderSide.SELL, price=106.0, quantity=5))
        assert ob.get_total_ask_volume() == 15


class TestOrderModification:
    """Test order modification."""

    def test_modify_order_quantity(self):
        ob = OrderBook()
        ob.add_order(Order(id="1", side=OrderSide.BUY, price=100.0, quantity=10))
        ob.modify_order("1", new_quantity=15)
        assert ob.get_order("1").quantity == 15
        assert ob.get_order("1").remaining == 15

    def test_modify_order_price(self):
        ob = OrderBook()
        ob.add_order(Order(id="1", side=OrderSide.BUY, price=100.0, quantity=10))
        ob.modify_order("1", new_price=99.0)
        assert ob.get_order("1").price == 99.0

    def test_modify_nonexistent_order_raises(self):
        ob = OrderBook()
        with pytest.raises(KeyError):
            ob.modify_order("nonexistent", new_quantity=5)


class TestPerformance:
    """Test performance requirements."""

    def test_throughput_10k_orders_per_sec(self):
        """Verify order book can handle 10K+ orders/sec."""
        import time
        ob = OrderBook()
        start = time.time()
        for i in range(10000):
            ob.add_order(Order(id=str(i), side=OrderSide.BUY, price=100.0 + (i % 10), quantity=1))
        elapsed = time.time() - start
        rate = 10000 / elapsed
        assert rate > 10000, f"Throughput {rate:.0f} orders/sec below 10K target"

    def test_matching_throughput(self):
        """Verify matching engine handles 10K+ matches/sec."""
        import time
        ob = OrderBook()
        # Pre-load sell orders
        for i in range(5000):
            ob.add_order(Order(id=f"s{i}", side=OrderSide.SELL, price=100.0, quantity=1))
        start = time.time()
        for i in range(5000):
            ob.add_order(Order(id=f"b{i}", side=OrderSide.BUY, price=100.0, quantity=1))
        elapsed = time.time() - start
        rate = 5000 / elapsed
        assert rate > 10000, f"Matching throughput {rate:.0f} orders/sec below 10K target"


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_zero_quantity_order(self):
        ob = OrderBook()
        with pytest.raises(ValueError):
            ob.add_order(Order(id="1", side=OrderSide.BUY, price=100.0, quantity=0))

    def test_negative_quantity_order(self):
        ob = OrderBook()
        with pytest.raises(ValueError):
            ob.add_order(Order(id="1", side=OrderSide.BUY, price=100.0, quantity=-5))

    def test_negative_price_order(self):
        ob = OrderBook()
        with pytest.raises(ValueError):
            ob.add_order(Order(id="1", side=OrderSide.BUY, price=-100.0, quantity=10))

    def test_cancel_already_cancelled_order(self):
        ob = OrderBook()
        ob.add_order(Order(id="1", side=OrderSide.BUY, price=100.0, quantity=10))
        ob.cancel_order("1")
        with pytest.raises(KeyError):
            ob.cancel_order("1")

    def test_get_orders_at_price_empty(self):
        ob = OrderBook()
        assert ob.get_orders_at_price(OrderSide.BUY, 100.0) == []

    def test_large_order_book(self):
        """Test with a large number of orders."""
        ob = OrderBook()
        for i in range(1000):
            ob.add_order(Order(id=str(i), side=OrderSide.BUY, price=100.0 + (i % 50), quantity=1))
        assert ob.get_total_bid_volume() == 1000
