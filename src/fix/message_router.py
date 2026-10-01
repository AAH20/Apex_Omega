"""FIX Message Router — routes incoming FIX messages to handlers by MsgType."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from src.fix.session.fix42_session import FIXMessage


class RoutingError(Exception):
    """Raised when a message cannot be routed."""


@dataclass
class RouteResult:
    """Result of routing a FIX message to a handler."""

    value: Any
    msg_type: str
    error: Optional[Exception] = None


@dataclass
class RoutingStats:
    """Statistics for message routing."""

    routed: int = 0
    errors: int = 0
    fallback: int = 0
    by_type: dict[str, int] = field(default_factory=dict)


class MessageRouter:
    """Routes FIX messages to registered handlers based on MsgType.

    Supports:
    - Handler registration by MsgType
    - Default handler for unregistered types
    - Middleware chain (pre-processing)
    - Routing statistics
    """

    def __init__(self) -> None:
        self._handlers: dict[str, Callable[[FIXMessage], Any]] = {}
        self._default_handler: Optional[Callable[[FIXMessage], Any]] = None
        self._middleware: list[Callable[[FIXMessage], Any]] = []
        self._stats = RoutingStats()

    # ── Registration ─────────────────────────────────────────────────

    def register(
        self,
        msg_type: str,
        handler: Optional[Callable[[FIXMessage], Any]] = None,
    ) -> Any:
        """Register a handler for a specific MsgType.

        Can be used as a regular method call or as a decorator:

            router.register("D", my_handler)

            @router.register("D")
            def my_handler(msg):
                ...

        Args:
            msg_type: The FIX MsgType (e.g., "D" for NewOrderSingle).
            handler: Callable that takes a FIXMessage and returns a result.
                    If None, returns a decorator.

        Returns:
            None when handler is provided, otherwise a decorator.
        """
        if handler is None:
            def decorator(fn: Callable[[FIXMessage], Any]) -> Callable[[FIXMessage], Any]:
                self._handlers[msg_type] = fn
                return fn
            return decorator
        self._handlers[msg_type] = handler

    def unregister(self, msg_type: str) -> None:
        """Unregister a handler for a MsgType. No-op if not registered."""
        self._handlers.pop(msg_type, None)

    def has_handler(self, msg_type: str) -> bool:
        """Check if a handler is registered for the given MsgType."""
        return msg_type in self._handlers

    def set_default_handler(self, handler: Callable[[FIXMessage], Any]) -> None:
        """Set a default handler for unregistered message types."""
        self._default_handler = handler

    # ── Middleware ───────────────────────────────────────────────────

    def add_middleware(self, middleware: Callable[[FIXMessage], Any]) -> None:
        """Add a middleware callable that runs before the handler.

        Middleware can modify the message or raise RoutingError to short-circuit.
        """
        self._middleware.append(middleware)

    # ── Routing ──────────────────────────────────────────────────────

    def route(self, msg: FIXMessage) -> RouteResult:
        """Route a FIX message to the appropriate handler.

        Args:
            msg: The FIXMessage to route.

        Returns:
            RouteResult with the handler's return value.

        Raises:
            RoutingError: If no handler is found and no default is set.
        """
        msg_type = msg.msg_type

        # Run middleware chain
        current_msg = msg
        for mw in self._middleware:
            result = mw(current_msg)
            if result is not None:
                current_msg = result

        # Find handler
        handler = self._handlers.get(msg_type)
        if handler is None:
            if self._default_handler is None:
                raise RoutingError(
                    f"No handler registered for MsgType '{msg_type}' and no default handler set"
                )
            handler = self._default_handler
            self._stats.fallback += 1

        # Execute handler
        try:
            value = handler(current_msg)
            self._stats.routed += 1
            self._stats.by_type[msg_type] = self._stats.by_type.get(msg_type, 0) + 1
            return RouteResult(value=value, msg_type=msg_type)
        except Exception as e:
            self._stats.errors += 1
            raise

    # ── Statistics ───────────────────────────────────────────────────

    def get_stats(self) -> RoutingStats:
        """Get current routing statistics."""
        return self._stats

    def reset_stats(self) -> None:
        """Reset all routing statistics to zero."""
        self._stats = RoutingStats()
