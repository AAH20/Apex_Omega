"""Order Book Matching Engine — price-time priority."""
from __future__ import annotations

import heapq
from dataclasses import dataclass, field
from enum import Enum
from itertools import count


class Side(Enum):
    BUY = "buy"
    SELL = "sell"


@dataclass
class Order:
    order_id: str
    side: Side
    price: float
    quantity: int
    timestamp: int
    filled: int = 0

    @property
    def remaining(self) -> int:
        return self.quantity - self.filled

    @property
    def is_filled(self) -> bool:
        return self.remaining <= 0


@dataclass
class Trade:
    taker_order_id: str
    maker_order_id: str
    price: float
    quantity: int


class OrderBook:
    """Price-time priority order book."""

    def __init__(self):
        # Bids: max-heap by price (use negated price), then min timestamp
        self._bids: list[tuple[float, int, int, Order]] = []
        # Asks: min-heap by price, then min timestamp
        self._asks: list[tuple[float, int, int, Order]] = []
        self._orders: dict[str, Order] = {}
        self._counter = count()  # tie-breaker for heap stability

    def add_order(self, order: Order) -> list[Trade]:
        """Add an order and return list of trades executed."""
        if order.quantity <= 0:
            return []

        self._orders[order.order_id] = order
        trades = []

        if order.side == Side.BUY:
            trades = self._match_buy(order)
        else:
            trades = self._match_sell(order)

        # If not fully filled, add remainder to book
        if not order.is_filled:
            self._add_to_book(order)

        return trades

    def cancel_order(self, order_id: str) -> None:
        """Cancel an order by ID."""
        if order_id not in self._orders:
            raise ValueError(f"Order {order_id} not found")
        del self._orders[order_id]

    @property
    def best_bid(self) -> float | None:
        """Highest bid price, or None if no bids."""
        self._clean_bids()
        if not self._bids:
            return None
        return -self._bids[0][0]

    @property
    def best_ask(self) -> float | None:
        """Lowest ask price, or None if no asks."""
        self._clean_asks()
        if not self._asks:
            return None
        return self._asks[0][0]

    @property
    def spread(self) -> float | None:
        """Spread between best ask and best bid, or None if either side empty."""
        bid = self.best_bid
        ask = self.best_ask
        if bid is None or ask is None:
            return None
        return ask - bid

    @property
    def bid_volume(self) -> int:
        """Total volume at best bid level."""
        self._clean_bids()
        if not self._bids:
            return 0
        best_price = -self._bids[0][0]
        return sum(
            o.remaining
            for neg_price, _, _, o in self._bids
            if -neg_price == best_price and o.order_id in self._orders
        )

    @property
    def ask_volume(self) -> int:
        """Total volume at best ask level."""
        self._clean_asks()
        if not self._asks:
            return 0
        best_price = self._asks[0][0]
        return sum(
            o.remaining
            for ask_price, _, _, o in self._asks
            if ask_price == best_price and o.order_id in self._orders
        )

    # ── internal ──────────────────────────────────────────────────────────────

    def _match_buy(self, order: Order) -> list[Trade]:
        trades = []
        while order.remaining > 0:
            self._clean_asks()
            if not self._asks:
                break

            ask_price, _, _, ask_order = self._asks[0]
            if ask_price > order.price:
                break

            heapq.heappop(self._asks)
            fill_qty = min(order.remaining, ask_order.remaining)

            ask_order.filled += fill_qty
            order.filled += fill_qty

            trades.append(Trade(
                taker_order_id=order.order_id,
                maker_order_id=ask_order.order_id,
                price=ask_price,
                quantity=fill_qty,
            ))

            if not ask_order.is_filled:
                heapq.heappush(self._asks, (ask_price, ask_order.timestamp, next(self._counter), ask_order))
            else:
                del self._orders[ask_order.order_id]

        return trades

    def _match_sell(self, order: Order) -> list[Trade]:
        trades = []
        while order.remaining > 0:
            self._clean_bids()
            if not self._bids:
                break

            bid_price = -self._bids[0][0]
            if bid_price < order.price:
                break

            _, _, _, bid_order = heapq.heappop(self._bids)
            fill_qty = min(order.remaining, bid_order.remaining)

            bid_order.filled += fill_qty
            order.filled += fill_qty

            trades.append(Trade(
                taker_order_id=order.order_id,
                maker_order_id=bid_order.order_id,
                price=bid_price,
                quantity=fill_qty,
            ))

            if not bid_order.is_filled:
                heapq.heappush(self._bids, (-bid_price, bid_order.timestamp, next(self._counter), bid_order))
            else:
                del self._orders[bid_order.order_id]

        return trades

    def _add_to_book(self, order: Order) -> None:
        if order.side == Side.BUY:
            heapq.heappush(self._bids, (-order.price, order.timestamp, next(self._counter), order))
        else:
            heapq.heappush(self._asks, (order.price, order.timestamp, next(self._counter), order))

    def _clean_bids(self) -> None:
        while self._bids:
            price, _, _, order = self._bids[0]
            if order.order_id not in self._orders or order.is_filled:
                heapq.heappop(self._bids)
            else:
                break

    def _clean_asks(self) -> None:
        while self._asks:
            price, _, _, order = self._asks[0]
            if order.order_id not in self._orders or order.is_filled:
                heapq.heappop(self._asks)
            else:
                break
