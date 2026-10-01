"""Bloomberg B-PIPE adapter for session management, order routing, and market data."""
from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


# ── Enums ───────────────────────────────────────────────────────────────


class OrderSide(Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP = "STOP"
    STOP_LIMIT = "STOP_LIMIT"


class OrderStatus(Enum):
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


class SessionState(Enum):
    DISCONNECTED = "DISCONNECTED"
    CONNECTED = "CONNECTED"
    AUTHENTICATED = "AUTHENTICATED"


# ── Errors ──────────────────────────────────────────────────────────────


class BpipeConnectionError(Exception):
    """Raised when B-PIPE connection fails."""


class BpipeAuthenticationError(Exception):
    """Raised when B-PIPE authentication fails."""


class BpipeOrderError(Exception):
    """Raised when order routing fails."""


class BpipeMarketDataError(Exception):
    """Raised when market data subscription fails."""


# ── Session ─────────────────────────────────────────────────────────────


@dataclass
class BpipeSession:
    """Manages a B-PIPE session lifecycle."""

    host: str
    port: int
    state: SessionState = SessionState.DISCONNECTED
    _connection: Any = None
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def connect(self) -> None:
        """Establish connection to B-PIPE server."""
        with self._lock:
            if self.state != SessionState.DISCONNECTED:
                return
            try:
                self._open_connection()
                self.state = SessionState.CONNECTED
                logger.info("Connected to B-PIPE at %s:%d", self.host, self.port)
            except Exception as exc:
                self.state = SessionState.DISCONNECTED
                raise BpipeConnectionError(f"Failed to connect: {exc}") from exc

    def authenticate(self, username: str, password: str) -> None:
        """Authenticate with B-PIPE server."""
        with self._lock:
            if self.state != SessionState.CONNECTED:
                raise BpipeConnectionError("Not connected")
            result = self._send_auth(username, password)
            if result.get("status") != "SUCCESS":
                raise BpipeAuthenticationError(
                    result.get("reason", "Authentication failed")
                )
            self.state = SessionState.AUTHENTICATED
            logger.info("Authenticated with B-PIPE")

    def disconnect(self) -> None:
        """Close B-PIPE session."""
        with self._lock:
            if self.state == SessionState.DISCONNECTED:
                return
            try:
                self._close_connection()
            finally:
                self.state = SessionState.DISCONNECTED
                self._connection = None
                logger.info("Disconnected from B-PIPE")

    def send_heartbeat(self) -> bool:
        """Send heartbeat to keep session alive."""
        if self.state != SessionState.AUTHENTICATED:
            raise BpipeConnectionError("Not authenticated")
        return self._send_heartbeat()

    def is_authenticated(self) -> bool:
        """Check if session is authenticated."""
        return self.state == SessionState.AUTHENTICATED

    def __enter__(self) -> BpipeSession:
        self.connect()
        return self

    def __exit__(self, *args: Any) -> None:
        self.disconnect()

    # ── Internal methods (to be overridden in tests) ───────────────────

    def _open_connection(self) -> None:
        """Open the underlying connection."""
        raise NotImplementedError

    def _close_connection(self) -> None:
        """Close the underlying connection."""
        raise NotImplementedError

    def _send_auth(self, username: str, password: str) -> Dict[str, Any]:
        """Send authentication request."""
        raise NotImplementedError

    def _send_heartbeat(self) -> bool:
        """Send heartbeat message."""
        raise NotImplementedError


# ── Order ───────────────────────────────────────────────────────────────


@dataclass
class BpipeOrder:
    """Represents a B-PIPE order."""

    symbol: str
    side: OrderSide
    quantity: int
    order_type: OrderType
    limit_price: Optional[float] = None
    stop_price: Optional[float] = None
    time_in_force: str = "DAY"
    account: Optional[str] = None
    order_id: Optional[str] = None
    status: OrderStatus = OrderStatus.PENDING

    def to_dict(self) -> Dict[str, Any]:
        """Convert order to dictionary."""
        return {
            "symbol": self.symbol,
            "side": self.side.value,
            "quantity": self.quantity,
            "order_type": self.order_type.value,
            "limit_price": self.limit_price,
            "stop_price": self.stop_price,
            "time_in_force": self.time_in_force,
            "account": self.account,
            "order_id": self.order_id,
            "status": self.status.value,
        }


# ── Market Data Subscription ────────────────────────────────────────────


@dataclass
class BpipeMarketDataSubscription:
    """Represents a market data subscription."""

    symbol: str
    fields: List[str]
    interval: int = 0
    active: bool = False
    subscription_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert subscription to dictionary."""
        return {
            "symbol": self.symbol,
            "fields": self.fields,
            "interval": self.interval,
            "active": self.active,
            "subscription_id": self.subscription_id,
        }


# ── Adapter ─────────────────────────────────────────────────────────────


class BloombergBpipeAdapter:
    """Bloomberg B-PIPE adapter for order routing and market data."""

    def __init__(
        self,
        host: str,
        port: int = 8194,
        username: str = "",
        password: str = "",
    ) -> None:
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.session = BpipeSession(host=host, port=port)
        self.order_history: List[BpipeOrder] = []
        self.active_subscriptions: Dict[str, BpipeMarketDataSubscription] = {}
        self._market_data_callbacks: Dict[str, List[Callable]] = {}
        self._lock = threading.Lock()

    def connect(self) -> None:
        """Connect and authenticate with B-PIPE."""
        self.session.connect()
        self.session.authenticate(self.username, self.password)

    def disconnect(self) -> None:
        """Disconnect from B-PIPE."""
        self.session.disconnect()

    def is_connected(self) -> bool:
        """Check if adapter is connected and authenticated."""
        return self.session.is_authenticated()

    def __enter__(self) -> BloombergBpipeAdapter:
        self.connect()
        return self

    def __exit__(self, *args: Any) -> None:
        self.disconnect()

    # ── Order Routing ──────────────────────────────────────────────────

    def submit_order(self, order: BpipeOrder) -> Dict[str, Any]:
        """Submit an order to B-PIPE."""
        self._require_auth()
        self._validate_order(order)
        result = self._route_order(order)
        order.status = OrderStatus.SUBMITTED
        with self._lock:
            self.order_history.append(order)
        return result

    def cancel_order(self, order_id: str) -> Dict[str, Any]:
        """Cancel an existing order."""
        self._require_auth()
        return self._cancel_order(order_id)

    def amend_order(self, order_id: str, **kwargs: Any) -> Dict[str, Any]:
        """Amend an existing order."""
        self._require_auth()
        return self._amend_order(order_id, **kwargs)

    def get_order_status(self, order_id: str) -> Dict[str, Any]:
        """Get status of an existing order."""
        self._require_auth()
        return self._get_order_status(order_id)

    # ── Market Data ────────────────────────────────────────────────────

    def subscribe_market_data(
        self, symbol: str, fields: List[str], interval: int = 0
    ) -> Dict[str, Any]:
        """Subscribe to market data for a symbol."""
        self._require_auth()
        if not symbol:
            raise BpipeMarketDataError("Symbol cannot be empty")
        if not fields:
            raise BpipeMarketDataError("Fields cannot be empty")
        return self._subscribe(symbol, fields, interval)

    def unsubscribe_market_data(self, subscription_id: str) -> Dict[str, Any]:
        """Unsubscribe from market data."""
        self._require_auth()
        return self._unsubscribe(subscription_id)

    def get_market_data(self, symbol: str) -> Dict[str, Any]:
        """Get current market data for a symbol."""
        self._require_auth()
        return self._get_market_data(symbol)

    def register_market_data_callback(
        self, symbol: str, callback: Callable
    ) -> None:
        """Register a callback for market data updates."""
        with self._lock:
            if symbol not in self._market_data_callbacks:
                self._market_data_callbacks[symbol] = []
            self._market_data_callbacks[symbol].append(callback)

    def unregister_market_data_callback(
        self, symbol: str, callback: Callable
    ) -> None:
        """Unregister a market data callback."""
        with self._lock:
            if symbol in self._market_data_callbacks:
                self._market_data_callbacks[symbol] = [
                    cb for cb in self._market_data_callbacks[symbol] if cb is not callback
                ]

    def _notify_market_data(self, symbol: str, data: Dict[str, Any]) -> None:
        """Notify registered callbacks of market data update."""
        with self._lock:
            callbacks = list(self._market_data_callbacks.get(symbol, []))
        for callback in callbacks:
            try:
                callback(symbol, data)
            except Exception:
                logger.exception("Market data callback failed for %s", symbol)

    # ── Internal Methods ───────────────────────────────────────────────

    def _require_auth(self) -> None:
        """Ensure session is authenticated."""
        if not self.session.is_authenticated():
            raise BpipeConnectionError("Not authenticated")

    def _validate_order(self, order: BpipeOrder) -> None:
        """Validate order before submission."""
        if order.quantity <= 0:
            raise BpipeOrderError("Quantity must be positive")
        if not order.symbol:
            raise BpipeOrderError("Symbol cannot be empty")

    def _route_order(self, order: BpipeOrder) -> Dict[str, Any]:
        """Route order to B-PIPE (to be overridden)."""
        raise NotImplementedError

    def _cancel_order(self, order_id: str) -> Dict[str, Any]:
        """Cancel order on B-PIPE (to be overridden)."""
        raise NotImplementedError

    def _amend_order(self, order_id: str, **kwargs: Any) -> Dict[str, Any]:
        """Amend order on B-PIPE (to be overridden)."""
        raise NotImplementedError

    def _get_order_status(self, order_id: str) -> Dict[str, Any]:
        """Get order status from B-PIPE (to be overridden)."""
        raise NotImplementedError

    def _subscribe(
        self, symbol: str, fields: List[str], interval: int
    ) -> Dict[str, Any]:
        """Subscribe to market data on B-PIPE (to be overridden)."""
        raise NotImplementedError

    def _unsubscribe(self, subscription_id: str) -> Dict[str, Any]:
        """Unsubscribe from market data on B-PIPE (to be overridden)."""
        raise NotImplementedError

    def _get_market_data(self, symbol: str) -> Dict[str, Any]:
        """Get market data from B-PIPE (to be overridden)."""
        raise NotImplementedError
