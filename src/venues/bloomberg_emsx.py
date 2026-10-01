"""Bloomberg EMSX adapter: order entry, execution reports, and position management."""
from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Set

logger = logging.getLogger(__name__)


class EMSXSide(Enum):
    """Order side for EMSX."""
    BUY = "BUY"
    SELL = "SELL"


class EMSXOrderType(Enum):
    """Order type for EMSX."""
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP = "STOP"
    STOP_LIMIT = "STOP_LIMIT"


class EMSXOrderStatus(Enum):
    """Order lifecycle status for EMSX."""
    PENDING_NEW = "PENDING_NEW"
    NEW = "NEW"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    PENDING_CANCEL = "PENDING_CANCEL"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class EMSXTimeInForce(Enum):
    """Time in force for EMSX orders."""
    DAY = "DAY"
    IOC = "IOC"
    FOK = "FOK"
    GTC = "GTC"
    GTD = "GTD"


@dataclass
class EMSXSession:
    """Connection session for Bloomberg EMSX."""
    host: str
    port: int = 8094
    account: str = ""
    user: str = ""
    uuid: str = ""
    _connected: bool = False

    @property
    def is_connected(self) -> bool:
        return self._connected

    def connect(self) -> None:
        """Establish connection to EMSX."""
        if self._connected:
            return
        if not self.host:
            raise EMSXConnectionError("Host is required for EMSX connection")
        self._connected = True
        logger.info(f"EMSX: connected to {self.host}:{self.port}")

    def disconnect(self) -> None:
        """Disconnect from EMSX."""
        if not self._connected:
            return
        self._connected = False
        logger.info("EMSX: disconnected")

    def __enter__(self) -> EMSXSession:
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.disconnect()


@dataclass
class EMSXOrder:
    """An EMSX order."""
    symbol: str
    side: EMSXSide
    quantity: float
    order_type: EMSXOrderType
    price: float = 0.0
    time_in_force: EMSXTimeInForce = EMSXTimeInForce.DAY
    order_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    status: EMSXOrderStatus = EMSXOrderStatus.PENDING_NEW
    filled_quantity: float = 0.0
    avg_fill_price: float = 0.0
    timestamp: float = field(default_factory=time.time)


@dataclass
class EMSXPosition:
    """An EMSX position."""
    symbol: str
    quantity: float
    avg_price: float
    unrealized_pnl: float = 0.0


@dataclass
class EMSXMarketDataTick:
    """A market data tick from EMSX."""
    symbol: str
    bid: float
    ask: float
    bid_size: float
    ask_size: float
    timestamp: float = field(default_factory=time.time)


@dataclass
class EMSXMetrics:
    """Runtime metrics for the EMSX adapter."""
    orders_submitted: int = 0
    orders_filled: int = 0
    orders_cancelled: int = 0
    errors: int = 0


class EMSXConnectionError(Exception):
    """Raised when EMSX connection fails."""
    pass


class EMSXOrderRejectedError(Exception):
    """Raised when an order is rejected by EMSX."""
    pass


class BloombergEMSXAdapter:
    """Bloomberg EMSX adapter for order entry, execution reports, and position management."""

    def __init__(self, session: EMSXSession) -> None:
        self._session = session
        self._lock = threading.RLock()
        self._orders: Dict[str, EMSXOrder] = {}
        self._positions: Dict[str, EMSXPosition] = {}
        self._subscribed_symbols: Set[str] = set()
        self._metrics = EMSXMetrics()

    @property
    def session(self) -> EMSXSession:
        return self._session

    @property
    def is_connected(self) -> bool:
        return self._session.is_connected

    @property
    def metrics(self) -> EMSXMetrics:
        return self._metrics

    @property
    def subscribed_symbols(self) -> Set[str]:
        with self._lock:
            return self._subscribed_symbols.copy()

    def connect(self) -> None:
        """Connect to EMSX."""
        with self._lock:
            if self.is_connected:
                return
            self._session.connect()

    def disconnect(self) -> None:
        """Disconnect from EMSX."""
        with self._lock:
            if not self.is_connected:
                return
            self._session.disconnect()

    def __enter__(self) -> BloombergEMSXAdapter:
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.disconnect()

    def submit_order(
        self,
        symbol: str,
        side: EMSXSide,
        quantity: float,
        order_type: EMSXOrderType,
        price: float = 0.0,
        time_in_force: EMSXTimeInForce = EMSXTimeInForce.DAY,
        order_id: Optional[str] = None,
    ) -> EMSXOrder:
        """Submit an order to EMSX."""
        with self._lock:
            if not self.is_connected:
                raise EMSXConnectionError("Not connected to EMSX")
            order = EMSXOrder(
                symbol=symbol,
                side=side,
                quantity=quantity,
                order_type=order_type,
                price=price,
                time_in_force=time_in_force,
                order_id=order_id or str(uuid.uuid4()),
            )
            self._orders[order.order_id] = order
            self._metrics.orders_submitted += 1
            self._send_message({
                "type": "NEW_ORDER",
                "order_id": order.order_id,
                "symbol": symbol,
                "side": side.value,
                "quantity": quantity,
                "order_type": order_type.value,
                "price": price,
                "time_in_force": time_in_force.value,
            })
            return order

    def cancel_order(self, order_id: str) -> bool:
        """Cancel an order at EMSX."""
        with self._lock:
            if not self.is_connected:
                raise EMSXConnectionError("Not connected to EMSX")
            order = self._orders.get(order_id)
            if order is None:
                return False
            order.status = EMSXOrderStatus.PENDING_CANCEL
            self._metrics.orders_cancelled += 1
            self._send_message({
                "type": "CANCEL_ORDER",
                "order_id": order_id,
            })
            return True

    def replace_order(
        self,
        order_id: str,
        new_quantity: Optional[float] = None,
        new_price: Optional[float] = None,
    ) -> EMSXOrder:
        """Replace an order at EMSX."""
        with self._lock:
            if not self.is_connected:
                raise EMSXConnectionError("Not connected to EMSX")
            old_order = self._orders.get(order_id)
            if old_order is None:
                raise EMSXOrderRejectedError(f"Order {order_id} not found")
            # Cancel old order
            old_order.status = EMSXOrderStatus.CANCELLED
            # Create new order
            new_order = EMSXOrder(
                symbol=old_order.symbol,
                side=old_order.side,
                quantity=new_quantity if new_quantity is not None else old_order.quantity,
                order_type=old_order.order_type,
                price=new_price if new_price is not None else old_order.price,
                time_in_force=old_order.time_in_force,
            )
            self._orders[new_order.order_id] = new_order
            self._metrics.orders_submitted += 1
            self._send_message({
                "type": "REPLACE_ORDER",
                "old_order_id": order_id,
                "new_order_id": new_order.order_id,
                "symbol": new_order.symbol,
                "side": new_order.side.value,
                "quantity": new_order.quantity,
                "order_type": new_order.order_type.value,
                "price": new_order.price,
            })
            return new_order

    def get_order(self, order_id: str) -> Optional[EMSXOrder]:
        """Get an order by ID."""
        with self._lock:
            return self._orders.get(order_id)

    def get_all_orders(self) -> List[EMSXOrder]:
        """Get all orders."""
        with self._lock:
            return list(self._orders.values())

    def get_orders_by_status(self, status: EMSXOrderStatus) -> List[EMSXOrder]:
        """Get orders filtered by status."""
        with self._lock:
            return [o for o in self._orders.values() if o.status == status]

    def get_positions(self) -> List[EMSXPosition]:
        """Get all positions."""
        with self._lock:
            return list(self._positions.values())

    def get_position(self, symbol: str) -> Optional[EMSXPosition]:
        """Get position for a symbol."""
        with self._lock:
            return self._positions.get(symbol)

    def subscribe_market_data(self, symbols: List[str]) -> None:
        """Subscribe to market data for symbols."""
        with self._lock:
            if not self.is_connected:
                raise EMSXConnectionError("Not connected to EMSX")
            self._subscribed_symbols.update(symbols)
            self._send_message({
                "type": "SUBSCRIBE",
                "symbols": symbols,
            })

    def unsubscribe_market_data(self, symbols: List[str]) -> None:
        """Unsubscribe from market data for symbols."""
        with self._lock:
            if not self.is_connected:
                raise EMSXConnectionError("Not connected to EMSX")
            self._subscribed_symbols.difference_update(symbols)
            self._send_message({
                "type": "UNSUBSCRIBE",
                "symbols": symbols,
            })

    def _on_execution_report(
        self,
        order_id: str,
        exec_type: str,
        status: EMSXOrderStatus,
        filled_quantity: float,
        avg_fill_price: float,
    ) -> None:
        """Handle an execution report from EMSX.

        filled_quantity is the cumulative fill quantity for the order.
        avg_fill_price is the average price for this specific fill.
        """
        with self._lock:
            order = self._orders.get(order_id)
            if order is None:
                logger.warning(f"Execution report for unknown order: {order_id}")
                return
            order.status = status
            # Calculate incremental fill
            incremental_fill = filled_quantity - order.filled_quantity
            if incremental_fill > 0:
                # Update position with the incremental fill
                self._update_position(order, incremental_fill, avg_fill_price)
            order.filled_quantity = filled_quantity
            # Weighted average fill price
            if order.filled_quantity > 0:
                order.avg_fill_price = (
                    (order.avg_fill_price * (order.filled_quantity - incremental_fill))
                    + (avg_fill_price * incremental_fill)
                ) / order.filled_quantity
            if status == EMSXOrderStatus.FILLED:
                self._metrics.orders_filled += 1

    def _update_position(self, order: EMSXOrder, fill_qty: float, avg_fill_price: float) -> None:
        """Update position based on a fill.

        fill_qty is the incremental fill quantity (positive for buy, negative for sell).
        avg_fill_price is the average price for this specific fill.
        """
        symbol = order.symbol
        position = self._positions.get(symbol)
        if position is None:
            position = EMSXPosition(
                symbol=symbol,
                quantity=0.0,
                avg_price=0.0,
            )
            self._positions[symbol] = position
        # Determine signed fill quantity based on order side
        signed_fill = fill_qty if order.side == EMSXSide.BUY else -fill_qty
        new_quantity = position.quantity + signed_fill
        if position.quantity == 0 or (position.quantity > 0 and order.side == EMSXSide.BUY) or (position.quantity < 0 and order.side == EMSXSide.SELL):
            # Adding to position
            total_cost = position.quantity * position.avg_price + signed_fill * avg_fill_price
            position.avg_price = total_cost / new_quantity if new_quantity != 0 else 0.0
        elif (position.quantity > 0 and order.side == EMSXSide.SELL) or (position.quantity < 0 and order.side == EMSXSide.BUY):
            # Reducing or flipping position
            if abs(signed_fill) >= abs(position.quantity):
                # Flip
                position.avg_price = avg_fill_price
            # else: reducing, avg_price stays the same
        position.quantity = new_quantity
        if position.quantity == 0:
            position.avg_price = 0.0

    def _on_market_data_tick(
        self,
        symbol: str,
        bid: float,
        ask: float,
        bid_size: float,
        ask_size: float,
    ) -> EMSXMarketDataTick:
        """Handle a market data tick from EMSX."""
        tick = EMSXMarketDataTick(
            symbol=symbol,
            bid=bid,
            ask=ask,
            bid_size=bid_size,
            ask_size=ask_size,
        )
        return tick

    def _send_message(self, message: dict) -> None:
        """Send a message to EMSX."""
        if not self.is_connected:
            raise EMSXConnectionError("Not connected to EMSX")
        logger.debug(f"EMSX send: {message}")
