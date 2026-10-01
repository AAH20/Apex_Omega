"""Order Book Manager — 10K+ orders/sec with price-time priority."""
from __future__ import annotations

import bisect
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional


class OrderSide(Enum):
    BUY = "buy"
    SELL = "sell"


class OrderType(Enum):
    LIMIT = "limit"
    MARKET = "market"


@dataclass
class Order:
    id: str
    side: OrderSide
    price: float
    quantity: int
    timestamp: float = field(default_factory=time.time)
    order_type: OrderType = OrderType.LIMIT
    filled: int = 0

    @property
    def remaining(self) -> int:
        return self.quantity - self.filled

    @property
    def is_filled(self) -> bool:
        return self.filled >= self.quantity


class OrderBook:
    """High-performance order book with price-time priority matching."""

    def __init__(self):
        self._orders: Dict[str, Order] = {}
        # Price levels: sorted lists of prices for bisect operations
        self._bid_prices: List[float] = []  # sorted ascending
        self._ask_prices: List[float] = []  # sorted ascending
        # Price -> list of orders at that price (FIFO by timestamp)
        self._bid_levels: Dict[float, List[Order]] = {}
        self._ask_levels: Dict[float, List[Order]] = {}

    def add_order(self, order: Order) -> None:
        """Add an order to the book and attempt to match."""
        if order.quantity <= 0:
            raise ValueError(f"Quantity must be positive, got {order.quantity}")
        if order.price < 0:
            raise ValueError(f"Price must be non-negative, got {order.price}")

        # Register order in the system
        self._orders[order.id] = order

        # Try to match before adding remaining to book
        if order.side == OrderSide.BUY:
            self._match_buy(order)
        else:
            self._match_sell(order)

        # Add remaining quantity to book
        if order.remaining > 0:
            self._add_to_book(order)

    def cancel_order(self, order_id: str) -> None:
        """Cancel an order by ID."""
        if order_id not in self._orders:
            raise KeyError(f"Order {order_id} not found")
        order = self._orders.pop(order_id)
        # Remove from price level
        if order.side == OrderSide.BUY:
            self._remove_from_level(self._bid_levels, self._bid_prices, order)
        else:
            self._remove_from_level(self._ask_levels, self._ask_prices, order)

    def get_order(self, order_id: str) -> Optional[Order]:
        """Get an order by ID."""
        return self._orders.get(order_id)

    def modify_order(self, order_id: str, new_quantity: Optional[int] = None, new_price: Optional[float] = None) -> None:
        """Modify an existing order's quantity and/or price."""
        if order_id not in self._orders:
            raise KeyError(f"Order {order_id} not found")
        order = self._orders[order_id]
        if new_quantity is not None:
            if new_quantity <= 0:
                raise ValueError(f"Quantity must be positive, got {new_quantity}")
            if new_quantity < order.filled:
                raise ValueError(f"New quantity {new_quantity} cannot be less than filled {order.filled}")
            order.quantity = new_quantity
        if new_price is not None:
            if new_price < 0:
                raise ValueError(f"Price must be non-negative, got {new_price}")
            # Remove from old price level
            if order.side == OrderSide.BUY:
                self._remove_from_level(self._bid_levels, self._bid_prices, order)
            else:
                self._remove_from_level(self._ask_levels, self._ask_prices, order)
            order.price = new_price
            # Add to new price level
            self._add_to_book(order)

    def get_best_bid(self) -> Optional[float]:
        """Get the highest bid price."""
        if not self._bid_prices:
            return None
        return self._bid_prices[-1]

    def get_best_ask(self) -> Optional[float]:
        """Get the lowest ask price."""
        if not self._ask_prices:
            return None
        return self._ask_prices[0]

    def get_spread(self) -> Optional[float]:
        """Get the spread (best ask - best bid)."""
        best_bid = self.get_best_bid()
        best_ask = self.get_best_ask()
        if best_bid is None or best_ask is None:
            return None
        return best_ask - best_bid

    def get_orders_at_price(self, side: OrderSide, price: float) -> List[Order]:
        """Get all orders at a specific price level, sorted by time."""
        levels = self._bid_levels if side == OrderSide.BUY else self._ask_levels
        return list(levels.get(price, []))

    def get_volume_at_price(self, side: OrderSide, price: float) -> int:
        """Get total volume at a specific price level."""
        orders = self.get_orders_at_price(side, price)
        return sum(o.remaining for o in orders)

    def get_bid_depth(self) -> Dict[float, int]:
        """Get bid depth as {price: volume}."""
        return {price: self.get_volume_at_price(OrderSide.BUY, price) for price in self._bid_prices}

    def get_ask_depth(self) -> Dict[float, int]:
        """Get ask depth as {price: volume}."""
        return {price: self.get_volume_at_price(OrderSide.SELL, price) for price in self._ask_prices}

    def get_total_bid_volume(self) -> int:
        """Get total bid volume."""
        return sum(self.get_volume_at_price(OrderSide.BUY, p) for p in self._bid_prices)

    def get_total_ask_volume(self) -> int:
        """Get total ask volume."""
        return sum(self.get_volume_at_price(OrderSide.SELL, p) for p in self._ask_prices)

    def _add_to_book(self, order: Order) -> None:
        """Add an order to the book at its price level."""
        self._orders[order.id] = order
        if order.side == OrderSide.BUY:
            if order.price not in self._bid_levels:
                bisect.insort(self._bid_prices, order.price)
                self._bid_levels[order.price] = []
            self._bid_levels[order.price].append(order)
        else:
            if order.price not in self._ask_levels:
                bisect.insort(self._ask_prices, order.price)
                self._ask_levels[order.price] = []
            self._ask_levels[order.price].append(order)

    def _remove_from_level(self, levels: Dict[float, List[Order]], prices: List[float], order: Order) -> None:
        """Remove an order from its price level."""
        price_levels = levels.get(order.price)
        if price_levels:
            price_levels[:] = [o for o in price_levels if o.id != order.id]
            if not price_levels:
                del levels[order.price]
                prices.remove(order.price)

    def _match_buy(self, order: Order) -> None:
        """Match a buy order against the ask side."""
        while order.remaining > 0 and self._ask_prices:
            best_ask = self._ask_prices[0]
            if order.price < best_ask:
                break
            self._match_against_level(order, self._ask_levels[best_ask])
            if not self._ask_levels[best_ask]:
                del self._ask_levels[best_ask]
                self._ask_prices.pop(0)

    def _match_sell(self, order: Order) -> None:
        """Match a sell order against the bid side."""
        while order.remaining > 0 and self._bid_prices:
            best_bid = self._bid_prices[-1]
            if order.price > best_bid:
                break
            self._match_against_level(order, self._bid_levels[best_bid])
            if not self._bid_levels[best_bid]:
                del self._bid_levels[best_bid]
                self._bid_prices.pop()

    def _match_against_level(self, order: Order, level: List[Order]) -> None:
        """Match an order against all orders at a price level."""
        for resting in level[:]:
            if order.remaining <= 0:
                break
            trade_qty = min(order.remaining, resting.remaining)
            order.filled += trade_qty
            resting.filled += trade_qty
            if resting.is_filled:
                level.remove(resting)
