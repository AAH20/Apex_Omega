"""MiFID II Article 16 / RTS 6 Article 12 — Risk Kill Switch.

Implements immediate cancellation of all unexecuted orders across all venues.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable


class KillSwitchStatus(Enum):
    INACTIVE = "INACTIVE"
    ACTIVE = "ACTIVE"


@dataclass
class OrderOwnership:
    """Identifies which algorithm, trader, desk, or client owns an order."""

    algorithm: str
    trader: str
    desk: str
    client: str


class Venue:
    """Abstract base for trading venues."""

    name: str

    def cancel_all_orders(self) -> list[str]:
        raise NotImplementedError

    def get_open_orders(self) -> list[dict]:
        raise NotImplementedError


class KillSwitch:
    """MiFID II Art 16 kill switch — immediate cancellation of all unexecuted orders.

    Supports:
    - Manual trigger by authorised personnel
    - Automatic trigger on anomaly detection
    - Venue-level and global cancellation
    - Order ownership identification
    - Comprehensive audit logging
    """

    def __init__(self):
        self._status = KillSwitchStatus.INACTIVE
        self._venues: list[Venue] = []
        self._cancelled_order_ids: list[str] = []
        self._audit_log: list[dict[str, Any]] = []
        self._order_ownership: dict[str, OrderOwnership] = {}
        self._automatic_trigger: Callable[[], None] | None = None
        self._lock = threading.Lock()

    @property
    def status(self) -> KillSwitchStatus:
        return self._status

    @property
    def cancelled_order_ids(self) -> list[str]:
        return list(self._cancelled_order_ids)

    @property
    def audit_log(self) -> list[dict[str, Any]]:
        return list(self._audit_log)

    def is_active(self) -> bool:
        return self._status == KillSwitchStatus.ACTIVE

    def register_venue(self, venue: Venue) -> None:
        """Register a trading venue for kill switch coverage."""
        with self._lock:
            self._venues.append(venue)

    def register_order_ownership(self, order_id: str, ownership: OrderOwnership) -> None:
        """Map an order to its ownership (algorithm, trader, desk, client)."""
        with self._lock:
            self._order_ownership[order_id] = ownership

    def get_order_ownership(self, order_id: str) -> OrderOwnership | None:
        """Retrieve ownership information for a specific order."""
        return self._order_ownership.get(order_id)

    def set_automatic_trigger(self, callback: Callable[[], None]) -> None:
        """Set a callback for automatic kill switch triggering."""
        self._automatic_trigger = callback

    def check_automatic_trigger(self, condition: bool) -> None:
        """Check if automatic trigger condition is met and fire if so."""
        if condition and self._automatic_trigger is not None:
            self._automatic_trigger()

    def trigger(
        self,
        triggered_by: str = "system",
        venue_filter: str | None = None,
    ) -> dict[str, Any]:
        """Activate the kill switch and cancel all unexecuted orders.

        Args:
            triggered_by: Identifier of who/what triggered the kill switch.
            venue_filter: If specified, only cancel orders on this venue.

        Returns:
            Dict with cancellation results.
        """
        with self._lock:
            if self._status == KillSwitchStatus.ACTIVE:
                return {
                    "cancelled_count": len(self._cancelled_order_ids),
                    "failed_venues": [],
                    "already_active": True,
                }

            self._status = KillSwitchStatus.ACTIVE
            cancelled: list[str] = []
            failed_venues: list[str] = []

            venues_to_cancel = self._venues
            if venue_filter is not None:
                venues_to_cancel = [v for v in self._venues if v.name == venue_filter]

            for venue in venues_to_cancel:
                try:
                    orders = venue.cancel_all_orders()
                    cancelled.extend(orders)
                except Exception:
                    failed_venues.append(venue.name)

            self._cancelled_order_ids.extend(cancelled)

            event: dict[str, Any] = {
                "action": "KILL_TRIGGERED",
                "timestamp": time.time(),
                "triggered_by": triggered_by,
                "cancelled_count": len(cancelled),
                "failed_venues": failed_venues,
            }
            self._audit_log.append(event)

            return {
                "cancelled_count": len(cancelled),
                "failed_venues": failed_venues,
                "already_active": False,
            }

    def reset(self) -> None:
        """Reset the kill switch to inactive state."""
        with self._lock:
            self._status = KillSwitchStatus.INACTIVE
            self._cancelled_order_ids.clear()
            self._audit_log.clear()

    def should_reject_order(self) -> bool:
        """Check if new orders should be rejected (kill switch active)."""
        return self.is_active()

    def get_status_report(self) -> dict[str, Any]:
        """Get a comprehensive status report."""
        return {
            "status": self._status.value,
            "cancelled_count": len(self._cancelled_order_ids),
            "venue_count": len(self._venues),
            "timestamp": time.time(),
        }
