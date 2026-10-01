"""Tests for Order Book Matching Engine — price-time priority."""
import pytest
from src.order_book.matching import Order, Side, OrderBook, Trade


# ── helpers ──────────────────────────────────────────────────────────────────

def make_order(order_id, side, price, qty, timestamp=0):
    return Order(order_id=order_id, side=side, price=price, quantity=qty, timestamp=timestamp)


# ── Order dataclass ──────────────────────────────────────────────────────────

class TestOrder:
    def test_order_creation(self):
        o = make_order("1", Side.BUY, 100.0, 10, timestamp=1)
        assert o.order_id == "1"
        assert o.side == Side.BUY
        assert o.price == 100.0
        assert o.quantity == 10
        assert o.timestamp == 1

    def test_order_filled_quantity_initially_zero(self):
        o = make_order("1", Side.BUY, 100.0, 10)
        assert o.filled == 0

    def test_order_remaining(self):
        o = make_order("1", Side.BUY, 100.0, 10)
        o.filled = 3
        assert o.remaining == 7

    def test_order_is_filled(self):
        o = make_order("1", Side.BUY, 100.0, 10)
        o.filled = 10
        assert o.is_filled is True

    def test_order_is_not_filled(self):
        o = make_order("1", Side.BUY, 100.0, 10)
        assert o.is_filled is False


# ── Basic matching ───────────────────────────────────────────────────────────

class TestBasicMatching:
    def test_simple_match(self):
        book = OrderBook()
        book.add_order(make_order("s1", Side.SELL, 100.0, 5, timestamp=1))
        trades = book.add_order(make_order("b1", Side.BUY, 100.0, 5, timestamp=2))
        assert len(trades) == 1
        assert trades[0].price == 100.0
        assert trades[0].quantity == 5

    def test_buy_above_ask_matches(self):
        book = OrderBook()
        book.add_order(make_order("s1", Side.SELL, 99.0, 5, timestamp=1))
        trades = book.add_order(make_order("b1", Side.BUY, 100.0, 5, timestamp=2))
        assert len(trades) == 1
        assert trades[0].price == 99.0  # trade at resting (passive) price

    def test_sell_below_bid_matches(self):
        book = OrderBook()
        book.add_order(make_order("b1", Side.BUY, 101.0, 5, timestamp=1))
        trades = book.add_order(make_order("s1", Side.SELL, 100.0, 5, timestamp=2))
        assert len(trades) == 1
        assert trades[0].price == 101.0

    def test_no_match_when_buy_below_ask(self):
        book = OrderBook()
        book.add_order(make_order("s1", Side.SELL, 101.0, 5, timestamp=1))
        trades = book.add_order(make_order("b1", Side.BUY, 100.0, 5, timestamp=2))
        assert len(trades) == 0

    def test_no_match_when_sell_above_bid(self):
        book = OrderBook()
        book.add_order(make_order("b1", Side.BUY, 99.0, 5, timestamp=1))
        trades = book.add_order(make_order("s1", Side.SELL, 100.0, 5, timestamp=2))
        assert len(trades) == 0


# ── Partial fills ────────────────────────────────────────────────────────────

class TestPartialFills:
    def test_buy_partial_fill(self):
        book = OrderBook()
        book.add_order(make_order("s1", Side.SELL, 100.0, 3, timestamp=1))
        trades = book.add_order(make_order("b1", Side.BUY, 100.0, 5, timestamp=2))
        assert len(trades) == 1
        assert trades[0].quantity == 3
        # remaining 2 should be in book
        assert book.best_bid == 100.0
        assert book.bid_volume == 2

    def test_sell_partial_fill(self):
        book = OrderBook()
        book.add_order(make_order("b1", Side.BUY, 100.0, 3, timestamp=1))
        trades = book.add_order(make_order("s1", Side.SELL, 100.0, 5, timestamp=2))
        assert len(trades) == 1
        assert trades[0].quantity == 3
        assert book.best_ask == 100.0
        assert book.ask_volume == 2

    def test_exact_fill_removes_order(self):
        book = OrderBook()
        book.add_order(make_order("s1", Side.SELL, 100.0, 5, timestamp=1))
        trades = book.add_order(make_order("b1", Side.BUY, 100.0, 5, timestamp=2))
        assert len(trades) == 1
        assert book.best_ask is None
        assert book.best_bid is None


# ── Price priority ───────────────────────────────────────────────────────────

class TestPricePriority:
    def test_best_sell_matched_first(self):
        book = OrderBook()
        book.add_order(make_order("s1", Side.SELL, 102.0, 5, timestamp=1))
        book.add_order(make_order("s2", Side.SELL, 100.0, 5, timestamp=2))
        trades = book.add_order(make_order("b1", Side.BUY, 102.0, 5, timestamp=3))
        assert len(trades) == 1
        assert trades[0].price == 100.0  # best (lowest) ask matched

    def test_best_buy_matched_first(self):
        book = OrderBook()
        book.add_order(make_order("b1", Side.BUY, 98.0, 5, timestamp=1))
        book.add_order(make_order("b2", Side.BUY, 100.0, 5, timestamp=2))
        trades = book.add_order(make_order("s1", Side.SELL, 98.0, 5, timestamp=3))
        assert len(trades) == 1
        assert trades[0].price == 100.0  # best (highest) bid matched

    def test_sweep_multiple_price_levels(self):
        book = OrderBook()
        book.add_order(make_order("s1", Side.SELL, 100.0, 3, timestamp=1))
        book.add_order(make_order("s2", Side.SELL, 101.0, 3, timestamp=2))
        book.add_order(make_order("s3", Side.SELL, 102.0, 3, timestamp=3))
        trades = book.add_order(make_order("b1", Side.BUY, 102.0, 8, timestamp=4))
        assert len(trades) == 3
        assert trades[0].price == 100.0
        assert trades[1].price == 101.0
        assert trades[2].price == 102.0
        assert sum(t.quantity for t in trades) == 8


# ── Time priority ────────────────────────────────────────────────────────────

class TestTimePriority:
    def test_earlier_order_at_same_price_fills_first(self):
        book = OrderBook()
        book.add_order(make_order("s1", Side.SELL, 100.0, 5, timestamp=1))
        book.add_order(make_order("s2", Side.SELL, 100.0, 5, timestamp=2))
        trades = book.add_order(make_order("b1", Side.BUY, 100.0, 5, timestamp=3))
        assert len(trades) == 1
        assert trades[0].maker_order_id == "s1"  # earlier timestamp wins

    def test_fifo_at_same_price_level(self):
        book = OrderBook()
        book.add_order(make_order("s1", Side.SELL, 100.0, 3, timestamp=1))
        book.add_order(make_order("s2", Side.SELL, 100.0, 3, timestamp=2))
        book.add_order(make_order("s3", Side.SELL, 100.0, 3, timestamp=3))
        trades = book.add_order(make_order("b1", Side.BUY, 100.0, 7, timestamp=4))
        assert len(trades) == 3
        assert trades[0].maker_order_id == "s1"
        assert trades[1].maker_order_id == "s2"
        assert trades[2].maker_order_id == "s3"
        assert trades[0].quantity == 3
        assert trades[1].quantity == 3
        assert trades[2].quantity == 1
        # s3 has 2 remaining
        assert book.best_ask == 100.0
        assert book.ask_volume == 2


# ── Order book state ─────────────────────────────────────────────────────────

class TestOrderBookState:
    def test_empty_book(self):
        book = OrderBook()
        assert book.best_bid is None
        assert book.best_ask is None
        assert book.spread is None

    def test_best_bid_and_ask(self):
        book = OrderBook()
        book.add_order(make_order("b1", Side.BUY, 99.0, 5, timestamp=1))
        book.add_order(make_order("s1", Side.SELL, 101.0, 5, timestamp=2))
        assert book.best_bid == 99.0
        assert book.best_ask == 101.0
        assert book.spread == 2.0

    def test_spread_zero_when_equal(self):
        book = OrderBook()
        book.add_order(make_order("b1", Side.BUY, 100.0, 5, timestamp=1))
        book.add_order(make_order("s1", Side.SELL, 100.0, 5, timestamp=2))
        # they match, so book should be empty
        assert book.spread is None

    def test_bid_volume(self):
        book = OrderBook()
        book.add_order(make_order("b1", Side.BUY, 99.0, 5, timestamp=1))
        book.add_order(make_order("b2", Side.BUY, 99.0, 3, timestamp=2))
        assert book.bid_volume == 8

    def test_ask_volume(self):
        book = OrderBook()
        book.add_order(make_order("s1", Side.SELL, 101.0, 5, timestamp=1))
        book.add_order(make_order("s2", Side.SELL, 101.0, 3, timestamp=2))
        assert book.ask_volume == 8

    def test_multiple_bid_levels(self):
        book = OrderBook()
        book.add_order(make_order("b1", Side.BUY, 99.0, 5, timestamp=1))
        book.add_order(make_order("b2", Side.BUY, 98.0, 5, timestamp=2))
        assert book.best_bid == 99.0
        assert book.bid_volume == 5

    def test_multiple_ask_levels(self):
        book = OrderBook()
        book.add_order(make_order("s1", Side.SELL, 101.0, 5, timestamp=1))
        book.add_order(make_order("s2", Side.SELL, 102.0, 5, timestamp=2))
        assert book.best_ask == 101.0
        assert book.ask_volume == 5


# ── Trade details ────────────────────────────────────────────────────────────

class TestTradeDetails:
    def test_trade_has_ids(self):
        book = OrderBook()
        book.add_order(make_order("s1", Side.SELL, 100.0, 5, timestamp=1))
        trades = book.add_order(make_order("b1", Side.BUY, 100.0, 5, timestamp=2))
        assert trades[0].taker_order_id == "b1"
        assert trades[0].maker_order_id == "s1"

    def test_trade_price_is_passive_price(self):
        book = OrderBook()
        book.add_order(make_order("s1", Side.SELL, 99.5, 5, timestamp=1))
        trades = book.add_order(make_order("b1", Side.BUY, 100.0, 5, timestamp=2))
        assert trades[0].price == 99.5

    def test_multiple_trades_from_one_taker(self):
        book = OrderBook()
        book.add_order(make_order("s1", Side.SELL, 100.0, 2, timestamp=1))
        book.add_order(make_order("s2", Side.SELL, 100.0, 2, timestamp=2))
        book.add_order(make_order("s3", Side.SELL, 100.0, 2, timestamp=3))
        trades = book.add_order(make_order("b1", Side.BUY, 100.0, 5, timestamp=4))
        assert len(trades) == 3
        assert all(t.taker_order_id == "b1" for t in trades)


# ── Cancellation ─────────────────────────────────────────────────────────────

class TestCancellation:
    def test_cancel_bid(self):
        book = OrderBook()
        book.add_order(make_order("b1", Side.BUY, 99.0, 5, timestamp=1))
        book.cancel_order("b1")
        assert book.best_bid is None

    def test_cancel_ask(self):
        book = OrderBook()
        book.add_order(make_order("s1", Side.SELL, 101.0, 5, timestamp=1))
        book.cancel_order("s1")
        assert book.best_ask is None

    def test_cancel_nonexistent_raises(self):
        book = OrderBook()
        with pytest.raises(ValueError):
            book.cancel_order("nonexistent")

    def test_cancel_updates_best_price(self):
        book = OrderBook()
        book.add_order(make_order("b1", Side.BUY, 99.0, 5, timestamp=1))
        book.add_order(make_order("b2", Side.BUY, 98.0, 5, timestamp=2))
        book.cancel_order("b1")
        assert book.best_bid == 98.0


# ── Edge cases ───────────────────────────────────────────────────────────────

class TestEdgeCases:
    def test_zero_quantity_order_ignored(self):
        book = OrderBook()
        trades = book.add_order(make_order("b1", Side.BUY, 100.0, 0, timestamp=1))
        assert len(trades) == 0
        assert book.best_bid is None

    def test_large_quantity_sweep(self):
        book = OrderBook()
        for i in range(10):
            book.add_order(make_order(f"s{i}", Side.SELL, 100.0 + i, 1, timestamp=i))
        trades = book.add_order(make_order("b1", Side.BUY, 109.0, 10, timestamp=100))
        assert len(trades) == 10
        assert sum(t.quantity for t in trades) == 10

    def test_alternating_sides_no_match(self):
        book = OrderBook()
        book.add_order(make_order("b1", Side.BUY, 99.0, 5, timestamp=1))
        book.add_order(make_order("s1", Side.SELL, 101.0, 5, timestamp=2))
        book.add_order(make_order("b2", Side.BUY, 98.0, 5, timestamp=3))
        book.add_order(make_order("s2", Side.SELL, 102.0, 5, timestamp=4))
        assert book.best_bid == 99.0
        assert book.best_ask == 101.0
        assert book.spread == 2.0

    def test_match_at_exact_price(self):
        book = OrderBook()
        book.add_order(make_order("s1", Side.SELL, 100.0, 5, timestamp=1))
        trades = book.add_order(make_order("b1", Side.BUY, 100.0, 5, timestamp=2))
        assert len(trades) == 1
        assert trades[0].price == 100.0

    def test_buy_sweep_leaves_partial_at_last_level(self):
        book = OrderBook()
        book.add_order(make_order("s1", Side.SELL, 100.0, 3, timestamp=1))
        book.add_order(make_order("s2", Side.SELL, 101.0, 3, timestamp=2))
        trades = book.add_order(make_order("b1", Side.BUY, 101.0, 5, timestamp=3))
        assert len(trades) == 2
        assert trades[0].quantity == 3
        assert trades[1].quantity == 2
        assert book.best_ask == 101.0
        assert book.ask_volume == 1
