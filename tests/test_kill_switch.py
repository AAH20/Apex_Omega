"""Tests for MiFID II Art 16 / RTS 6 Art 12 Kill Switch."""
import threading
import time

import pytest

from src.risk.kill_switch import (
    KillSwitch,
    KillSwitchStatus,
    OrderOwnership,
    Venue,
)


# ── Helpers ────────────────────────────────────────────────────────────


class MockVenue(Venue):
    """Test double for a trading venue."""

    def __init__(self, name: str, fail_cancel: bool = False):
        self.name = name
        self._fail_cancel = fail_cancel
        self.cancelled_orders: list[str] = []
        self.cancel_all_called = False

    def cancel_all_orders(self) -> list[str]:
        self.cancel_all_called = True
        if self._fail_cancel:
            raise ConnectionError(f"Venue {self.name} unreachable")
        return self.cancelled_orders

    def get_open_orders(self) -> list[dict]:
        return []


def make_ownership(
    algorithm: str = "alpha-1",
    trader: str = "trader-a",
    desk: str = "desk-1",
    client: str = "client-x",
) -> OrderOwnership:
    return OrderOwnership(
        algorithm=algorithm,
        trader=trader,
        desk=desk,
        client=client,
    )


# ── Tests ──────────────────────────────────────────────────────────────


def test_kill_switch_initializes_inactive():
    """Kill switch should start in INACTIVE state."""
    ks = KillSwitch()
    assert ks.status == KillSwitchStatus.INACTIVE
    assert not ks.is_active()


def test_trigger_kill_switch_activates():
    """Triggering kill switch should activate it."""
    ks = KillSwitch()
    ks.trigger()
    assert ks.status == KillSwitchStatus.ACTIVE
    assert ks.is_active()


def test_reset_kill_switch_deactivates():
    """Resetting kill switch should return it to INACTIVE."""
    ks = KillSwitch()
    ks.trigger()
    ks.reset()
    assert ks.status == KillSwitchStatus.INACTIVE
    assert not ks.is_active()


def test_cancel_all_orders_calls_all_venues():
    """Kill switch should call cancel_all_orders on every registered venue."""
    ks = KillSwitch()
    v1 = MockVenue("venue-a")
    v2 = MockVenue("venue-b")
    ks.register_venue(v1)
    ks.register_venue(v2)
    ks.trigger()
    assert v1.cancel_all_called
    assert v2.cancel_all_called


def test_cancel_all_orders_returns_cancelled_count():
    """Kill switch should return total number of cancelled orders."""
    ks = KillSwitch()
    v1 = MockVenue("venue-a")
    v1.cancelled_orders = ["ord-1", "ord-2"]
    v2 = MockVenue("venue-b")
    v2.cancelled_orders = ["ord-3"]
    ks.register_venue(v1)
    ks.register_venue(v2)
    result = ks.trigger()
    assert result["cancelled_count"] == 3


def test_kill_switch_cancels_specific_venue():
    """Kill switch should support cancelling orders for a specific venue only."""
    ks = KillSwitch()
    v1 = MockVenue("venue-a")
    v2 = MockVenue("venue-b")
    v1.cancelled_orders = ["ord-1"]
    v2.cancelled_orders = ["ord-2", "ord-3"]
    ks.register_venue(v1)
    ks.register_venue(v2)
    result = ks.trigger(venue_filter="venue-a")
    assert result["cancelled_count"] == 1
    assert v1.cancel_all_called
    assert not v2.cancel_all_called


def test_kill_switch_tracks_cancelled_orders():
    """Kill switch should track which orders were cancelled."""
    ks = KillSwitch()
    v1 = MockVenue("venue-a")
    v1.cancelled_orders = ["ord-1", "ord-2"]
    ks.register_venue(v1)
    ks.trigger()
    assert "ord-1" in ks.cancelled_order_ids
    assert "ord-2" in ks.cancelled_order_ids


def test_kill_switch_logs_audit_event():
    """Kill switch should log an audit event on trigger."""
    ks = KillSwitch()
    ks.trigger()
    assert len(ks.audit_log) == 1
    event = ks.audit_log[0]
    assert event["action"] == "KILL_TRIGGERED"
    assert "timestamp" in event


def test_kill_switch_with_no_venues():
    """Kill switch with no venues should still activate but cancel nothing."""
    ks = KillSwitch()
    result = ks.trigger()
    assert result["cancelled_count"] == 0
    assert ks.is_active()


def test_kill_switch_prevents_new_orders():
    """When kill switch is active, new orders should be rejected."""
    ks = KillSwitch()
    ks.trigger()
    assert ks.should_reject_order() is True


def test_kill_switch_allows_orders_when_inactive():
    """When kill switch is inactive, orders should be allowed."""
    ks = KillSwitch()
    assert ks.should_reject_order() is False


def test_kill_switch_with_order_ownership():
    """Kill switch should identify order ownership (algorithm, trader, desk, client)."""
    ks = KillSwitch()
    ownership = make_ownership(algorithm="mm-bot", trader="t1", desk="d1", client="c1")
    ks.register_order_ownership("ord-1", ownership)
    info = ks.get_order_ownership("ord-1")
    assert info is not None
    assert info.algorithm == "mm-bot"
    assert info.trader == "t1"
    assert info.desk == "d1"
    assert info.client == "c1"


def test_kill_switch_automatic_trigger():
    """Kill switch should support automatic triggering via callback."""
    ks = KillSwitch()
    triggered = []

    def auto_trigger():
        triggered.append(True)
        ks.trigger()

    ks.set_automatic_trigger(auto_trigger)
    ks.check_automatic_trigger(condition=True)
    assert ks.is_active()
    assert len(triggered) == 1


def test_kill_switch_manual_trigger():
    """Kill switch should support manual triggering."""
    ks = KillSwitch()
    ks.trigger(triggered_by="operator-joe")
    assert ks.is_active()
    assert ks.audit_log[0]["triggered_by"] == "operator-joe"


def test_kill_switch_idempotent_trigger():
    """Triggering kill switch multiple times should be safe."""
    ks = KillSwitch()
    v1 = MockVenue("venue-a")
    v1.cancelled_orders = ["ord-1"]
    ks.register_venue(v1)
    ks.trigger()
    ks.trigger()
    ks.trigger()
    assert ks.is_active()
    # Venue cancel should only be called once
    assert v1.cancel_all_called


def test_kill_switch_venue_failure_handling():
    """Kill switch should handle venue cancellation failures gracefully."""
    ks = KillSwitch()
    v1 = MockVenue("venue-a", fail_cancel=True)
    v2 = MockVenue("venue-b")
    v2.cancelled_orders = ["ord-1"]
    ks.register_venue(v1)
    ks.register_venue(v2)
    result = ks.trigger()
    # Should still cancel on v2 even though v1 failed
    assert result["cancelled_count"] == 1
    assert result["failed_venues"] == ["venue-a"]


def test_kill_switch_status_report():
    """Kill switch should provide a comprehensive status report."""
    ks = KillSwitch()
    v1 = MockVenue("venue-a")
    v1.cancelled_orders = ["ord-1", "ord-2"]
    ks.register_venue(v1)
    ks.trigger()
    report = ks.get_status_report()
    assert report["status"] == "ACTIVE"
    assert report["cancelled_count"] == 2
    assert report["venue_count"] == 1
    assert "timestamp" in report


def test_kill_switch_reset_clears_state():
    """Resetting kill switch should clear cancelled orders and audit state."""
    ks = KillSwitch()
    v1 = MockVenue("venue-a")
    v1.cancelled_orders = ["ord-1"]
    ks.register_venue(v1)
    ks.trigger()
    ks.reset()
    assert ks.cancelled_order_ids == []
    assert len(ks.audit_log) == 0


def test_kill_switch_thread_safety():
    """Kill switch should be thread-safe for concurrent triggers."""
    ks = KillSwitch()
    v1 = MockVenue("venue-a")
    v1.cancelled_orders = ["ord-1"]
    ks.register_venue(v1)

    errors = []

    def trigger_repeatedly():
        try:
            for _ in range(50):
                ks.trigger()
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=trigger_repeatedly) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    assert ks.is_active()
