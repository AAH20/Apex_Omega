#!/usr/bin/env python3
"""
demo_order_book.py — Apex_Omega Order Book Matching Demo

Demonstrates a simplified limit order book with price-time priority matching.
Shows how incoming orders are matched against resting orders, producing trades
and updating the book state.

Usage:
    python demo_order_book.py
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class Side(Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(Enum):
    LIMIT = "LIMIT"
    MARKET = "MARKET"


@dataclass
class Order:
    order_id: str
    side: Side
    order_type: OrderType
    quantity: int
    price: Optional[float] = None  # None for market orders
    timestamp: int = 0

    def __post_init__(self):
        if self.order_type == OrderType.LIMIT and self.price is None:
            raise ValueError("Limit orders must have a price")
        if self.order_type == OrderType.MARKET and self.price is not None:
            raise ValueError("Market orders must not have a price")


@dataclass
class Trade:
    trade_id: str
    buy_order_id: str
    sell_order_id: str
    price: float
    quantity: int
    timestamp: int = 0


@dataclass
class BookLevel:
    price: float
    quantity: int
    orders: list[Order] = field(default_factory=list)


class OrderBook:
    """Simplified limit order book with price-time priority."""

    def __init__(self, symbol: str):
        self.symbol = symbol
        self.bids: dict[float, BookLevel] = {}  # price -> BookLevel
        self.asks: dict[float, BookLevel] = {}  # price -> BookLevel
        self.trades: list[Trade] = []
        self._trade_counter = 0
        self._timestamp = 0

    def submit_order(self, order: Order) -> list[Trade]:
        """Submit an order and return any trades generated."""
        self._timestamp += 1
        order.timestamp = self._timestamp

        if order.side == Side.BUY:
            trades = self._match_buy(order)
        else:
            trades = self._match_sell(order)

        self.trades.extend(trades)
        return trades

    def _match_buy(self, order: Order) -> list[Trade]:
        trades = []
        remaining = order.quantity

        while remaining > 0:
            best_ask_price = min(self.asks.keys()) if self.asks else None
            if best_ask_price is None:
                break

            # Check if buy order can match
            if order.order_type == OrderType.LIMIT and order.price is not None and order.price < best_ask_price:
                break

            level = self.asks[best_ask_price]
            while remaining > 0 and level.orders:
                resting = level.orders[0]
                match_qty = min(remaining, resting.quantity)
                match_price = resting.price if resting.price is not None else best_ask_price

                self._trade_counter += 1
                trade = Trade(
                    trade_id=f"T{self._trade_counter:04d}",
                    buy_order_id=order.order_id,
                    sell_order_id=resting.order_id,
                    price=match_price,
                    quantity=match_qty,
                    timestamp=self._timestamp,
                )
                trades.append(trade)

                remaining -= match_qty
                resting.quantity -= match_qty
                level.quantity -= match_qty

                if resting.quantity == 0:
                    level.orders.pop(0)

            if level.quantity == 0:
                del self.asks[best_ask_price]

        # Add remaining to book
        if remaining > 0 and order.order_type == OrderType.LIMIT and order.price is not None:
            if order.price not in self.bids:
                self.bids[order.price] = BookLevel(price=order.price, quantity=0)
            self.bids[order.price].quantity += remaining
            self.bids[order.price].orders.append(
                Order(
                    order_id=order.order_id,
                    side=Side.BUY,
                    order_type=OrderType.LIMIT,
                    quantity=remaining,
                    price=order.price,
                    timestamp=self._timestamp,
                )
            )

        return trades

    def _match_sell(self, order: Order) -> list[Trade]:
        trades = []
        remaining = order.quantity

        while remaining > 0:
            best_bid_price = max(self.bids.keys()) if self.bids else None
            if best_bid_price is None:
                break

            # Check if sell order can match
            if order.order_type == OrderType.LIMIT and order.price is not None and order.price > best_bid_price:
                break

            level = self.bids[best_bid_price]
            while remaining > 0 and level.orders:
                resting = level.orders[0]
                match_qty = min(remaining, resting.quantity)
                match_price = resting.price if resting.price is not None else best_bid_price

                self._trade_counter += 1
                trade = Trade(
                    trade_id=f"T{self._trade_counter:04d}",
                    buy_order_id=resting.order_id,
                    sell_order_id=order.order_id,
                    price=match_price,
                    quantity=match_qty,
                    timestamp=self._timestamp,
                )
                trades.append(trade)

                remaining -= match_qty
                resting.quantity -= match_qty
                level.quantity -= match_qty

                if resting.quantity == 0:
                    level.orders.pop(0)

            if level.quantity == 0:
                del self.bids[best_bid_price]

        # Add remaining to book
        if remaining > 0 and order.order_type == OrderType.LIMIT and order.price is not None:
            if order.price not in self.asks:
                self.asks[order.price] = BookLevel(price=order.price, quantity=0)
            self.asks[order.price].quantity += remaining
            self.asks[order.price].orders.append(
                Order(
                    order_id=order.order_id,
                    side=Side.SELL,
                    order_type=OrderType.LIMIT,
                    quantity=remaining,
                    price=order.price,
                    timestamp=self._timestamp,
                )
            )

        return trades

    def get_best_bid(self) -> Optional[float]:
        return max(self.bids.keys()) if self.bids else None

    def get_best_ask(self) -> Optional[float]:
        return min(self.asks.keys()) if self.asks else None

    def get_spread(self) -> Optional[float]:
        bid = self.get_best_bid()
        ask = self.get_best_ask()
        if bid is not None and ask is not None:
            return ask - bid
        return None

    def display(self) -> None:
        """Print the current state of the order book."""
        print(f"\n{'='*60}")
        print(f"  Order Book: {self.symbol}")
        print(f"{'='*60}")

        # Asks (sorted ascending, best ask at bottom)
        print("\n  ASKS (Sell):")
        print(f"  {'Price':>10} {'Qty':>10} {'Orders':>10}")
        print(f"  {'-'*10} {'-'*10} {'-'*10}")
        for price in sorted(self.asks.keys()):
            level = self.asks[price]
            print(f"  {price:>10.2f} {level.quantity:>10} {len(level.orders):>10}")

        spread = self.get_spread()
        if spread is not None:
            print(f"\n  Spread: {spread:.2f}")
        else:
            print(f"\n  Spread: N/A")

        # Bids (sorted descending, best bid at top)
        print(f"\n  BIDS (Buy):")
        print(f"  {'Price':>10} {'Qty':>10} {'Orders':>10}")
        print(f"  {'-'*10} {'-'*10} {'-'*10}")
        for price in sorted(self.bids.keys(), reverse=True):
            level = self.bids[price]
            print(f"  {price:>10.2f} {level.quantity:>10} {len(level.orders):>10}")

        print(f"{'='*60}")


def run_demo() -> None:
    """Run the order book demonstration."""
    print("=" * 60)
    print("  Apex_Omega — Order Book Matching Demo")
    print("=" * 60)

    book = OrderBook("AAPL")

    # Scenario: Build up the book with resting orders
    print("\n[Phase 1] Building the order book with resting orders...")

    resting_orders = [
        Order("B001", Side.BUY, OrderType.LIMIT, 100, 150.00),
        Order("B002", Side.BUY, OrderType.LIMIT, 200, 149.50),
        Order("B003", Side.BUY, OrderType.LIMIT, 150, 149.00),
        Order("S001", Side.SELL, OrderType.LIMIT, 100, 150.50),
        Order("S002", Side.SELL, OrderType.LIMIT, 200, 151.00),
        Order("S003", Side.SELL, OrderType.LIMIT, 150, 151.50),
    ]

    for order in resting_orders:
        trades = book.submit_order(order)
        print(f"  Submitted {order.order_id}: {order.side.value} {order.quantity} @ {order.price:.2f}")
        if trades:
            for t in trades:
                print(f"    -> TRADE: {t.trade_id} {t.quantity} @ {t.price:.2f}")

    book.display()

    # Scenario: Aggressive buy order that sweeps multiple levels
    print("\n[Phase 2] Aggressive BUY order sweeping multiple ask levels...")
    aggressive_buy = Order("B004", Side.BUY, OrderType.LIMIT, 350, 151.00)
    print(f"  Submitting {aggressive_buy.order_id}: BUY {aggressive_buy.quantity} @ {aggressive_buy.price:.2f}")
    trades = book.submit_order(aggressive_buy)
    for t in trades:
        print(f"    -> TRADE: {t.trade_id} {t.quantity} @ {t.price:.2f} (buyer: {t.buy_order_id}, seller: {t.sell_order_id})")

    book.display()

    # Scenario: Market order
    print("\n[Phase 3] Market SELL order...")
    market_sell = Order("S004", Side.SELL, OrderType.MARKET, 200)
    print(f"  Submitting {market_sell.order_id}: SELL {market_sell.quantity} @ MARKET")
    trades = book.submit_order(market_sell)
    for t in trades:
        print(f"    -> TRADE: {t.trade_id} {t.quantity} @ {t.price:.2f} (buyer: {t.buy_order_id}, seller: {t.sell_order_id})")

    book.display()

    # Summary
    print("\n[Summary]")
    print(f"  Total trades executed: {len(book.trades)}")
    print(f"  Total volume: {sum(t.quantity for t in book.trades)}")
    print(f"  VWAP: {sum(t.price * t.quantity for t in book.trades) / sum(t.quantity for t in book.trades):.4f}")
    print(f"  Best bid: {book.get_best_bid()}")
    print(f"  Best ask: {book.get_best_ask()}")
    print(f"  Spread: {book.get_spread()}")


if __name__ == "__main__":
    run_demo()
