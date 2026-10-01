"""Venue Session Manager — unit tests (written first, TDD RED phase)."""
import threading
import time

import pytest

from venues.session_manager import SessionManager, VenueSession


@pytest.fixture
def manager():
    return SessionManager()


@pytest.fixture
def manager_with_venues():
    m = SessionManager()
    m.add_venue("binance", "api.binance.com", 443, weight=3, max_connections=10)
    m.add_venue("coinbase", "api.coinbase.com", 443, weight=1, max_connections=10)
    m.add_venue("kraken", "api.kraken.com", 443, weight=1, max_connections=10)
    return m


# ── Construction & Registration ──


def test_add_venue_creates_session(manager):
    manager.add_venue("binance", "api.binance.com", 443)
    session = manager.get_session("binance")
    assert session is not None
    assert session.venue_id == "binance"
    assert session.host == "api.binance.com"
    assert session.port == 443
    assert session.is_active is True
    assert session.current_connections == 0


def test_add_venue_duplicate_raises(manager):
    manager.add_venue("binance", "api.binance.com", 443)
    with pytest.raises(ValueError, match="already exists"):
        manager.add_venue("binance", "api.binance.com", 443)


def test_remove_venue_deletes_session(manager):
    manager.add_venue("binance", "api.binance.com", 443)
    manager.remove_venue("binance")
    assert manager.get_session("binance") is None


def test_remove_venue_nonexistent_raises(manager):
    with pytest.raises(KeyError):
        manager.remove_venue("nonexistent")


def test_get_session_returns_none_for_missing(manager):
    assert manager.get_session("nonexistent") is None


def test_list_sessions_returns_all(manager_with_venues):
    sessions = manager_with_venues.list_sessions()
    assert len(sessions) == 3
    ids = {s.venue_id for s in sessions}
    assert ids == {"binance", "coinbase", "kraken"}


def test_get_active_sessions_filters_inactive(manager_with_venues):
    manager_with_venues.mark_failed("binance")
    active = manager_with_venues.get_active_sessions()
    assert len(active) == 2
    assert all(s.venue_id != "binance" for s in active)


# ── Acquire / Release ──


def test_acquire_session_increments_connections(manager_with_venues):
    s = manager_with_venues.acquire_session("binance")
    assert s.venue_id == "binance"
    assert s.current_connections == 1


def test_acquire_session_round_robin_load_balances():
    # Equal weight → round-robin across all three
    m = SessionManager()
    m.add_venue("binance", "api.binance.com", 443, weight=1, max_connections=10)
    m.add_venue("coinbase", "api.coinbase.com", 443, weight=1, max_connections=10)
    m.add_venue("kraken", "api.kraken.com", 443, weight=1, max_connections=10)
    acquired = [m.acquire_session().venue_id for _ in range(6)]
    # First pass: each venue once; second pass: each venue once
    assert sorted(acquired[:3]) == ["binance", "coinbase", "kraken"]
    assert sorted(acquired[3:]) == ["binance", "coinbase", "kraken"]


def test_acquire_session_weighted_distribution(manager):
    manager.add_venue("heavy", "h1", 443, weight=3, max_connections=100)
    manager.add_venue("light", "h2", 443, weight=1, max_connections=100)
    acquired = [manager.acquire_session().venue_id for _ in range(40)]
    heavy_count = acquired.count("heavy")
    light_count = acquired.count("light")
    # Weighted: heavy should get roughly 75%
    assert heavy_count == 30
    assert light_count == 10


def test_acquire_session_skips_failed_venues(manager_with_venues):
    manager_with_venues.mark_failed("binance")
    # Binance is failed; should never be selected
    for _ in range(20):
        s = manager_with_venues.acquire_session()
        assert s.venue_id != "binance"


def test_acquire_session_returns_none_when_all_failed(manager_with_venues):
    for vid in ("binance", "coinbase", "kraken"):
        manager_with_venues.mark_failed(vid)
    assert manager_with_venues.acquire_session() is None


def test_release_session_decrements_connections(manager_with_venues):
    manager_with_venues.acquire_session("binance")
    manager_with_venues.release_session("binance")
    s = manager_with_venues.get_session("binance")
    assert s.current_connections == 0


def test_release_session_not_below_zero(manager_with_venues):
    manager_with_venues.release_session("binance")
    s = manager_with_venues.get_session("binance")
    assert s.current_connections == 0


def test_acquire_session_respects_max_connections(manager):
    manager.add_venue("small", "h", 443, max_connections=2)
    manager.acquire_session("small")
    manager.acquire_session("small")
    # Third acquire should return None (venue full)
    assert manager.acquire_session("small") is None


# ── Failover ──


def test_mark_failed_marks_venue_inactive(manager_with_venues):
    manager_with_venues.mark_failed("binance")
    assert manager_with_venues.get_session("binance").is_active is False


def test_mark_recovered_marks_venue_active(manager_with_venues):
    manager_with_venues.mark_failed("binance")
    manager_with_venues.mark_recovered("binance")
    assert manager_with_venues.get_session("binance").is_active is True


def test_failover_returns_next_available_session(manager_with_venues):
    primary = manager_with_venues.get_session("binance")
    backup = manager_with_venues.failover("binance")
    assert backup is not None
    assert backup.venue_id != "binance"
    assert backup.is_active is True
    # Original is now marked failed
    assert manager_with_venues.get_session("binance").is_active is False


def test_failover_raises_when_no_available(manager_with_venues):
    for vid in ("binance", "coinbase", "kraken"):
        manager_with_venues.mark_failed(vid)
    with pytest.raises(RuntimeError, match="No available"):
        manager_with_venues.failover("binance")


def test_failover_connections_migrate(manager_with_venues):
    s = manager_with_venues.acquire_session("binance")
    assert s.current_connections == 1
    manager_with_venues.failover("binance")
    # After failover the old venue should have released its connections
    assert manager_with_venues.get_session("binance").current_connections == 0


# ── Load Balancing ──


def test_get_least_loaded_session(manager_with_venues):
    manager_with_venues.acquire_session("binance")
    manager_with_venues.acquire_session("binance")
    # binance has 2, coinbase/kraken have 0
    least = manager_with_venues.get_least_loaded_session()
    assert least.venue_id in ("coinbase", "kraken")
    assert least.current_connections == 0


# ── Stats ──


def test_get_session_stats_returns_metrics(manager_with_venues):
    manager_with_venues.acquire_session("binance")
    stats = manager_with_venues.get_session_stats("binance")
    assert stats["venue_id"] == "binance"
    assert stats["current_connections"] == 1
    assert stats["is_active"] is True
    assert stats["weight"] == 3


# ── Health Check ──


def test_health_check_reports_status(manager_with_venues):
    health = manager_with_venues.health_check()
    assert health["binance"]["is_active"] is True
    assert health["coinbase"]["is_active"] is True
    assert health["kraken"]["is_active"] is True


def test_health_check_detects_failed(manager_with_venues):
    manager_with_venues.mark_failed("binance")
    health = manager_with_venues.health_check()
    assert health["binance"]["is_active"] is False


# ── Thread Safety ──


def test_concurrent_acquire_release_thread_safety(manager):
    manager.add_venue("v1", "h", 443, max_connections=1000)
    errors = []

    def worker():
        try:
            for _ in range(100):
                s = manager.acquire_session("v1")
                if s is not None:
                    time.sleep(0.0001)
                    manager.release_session("v1")
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=worker) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    s = manager.get_session("v1")
    assert s.current_connections == 0


# ── Close ──


def test_close_clears_all_sessions(manager_with_venues):
    manager_with_venues.close()
    assert manager_with_venues.list_sessions() == []
