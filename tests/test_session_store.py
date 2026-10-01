"""Tests for FIX Session Store — TDD: write tests first, watch them fail."""
import time

import pytest
import fakeredis

from src.fix.session_store import SessionStore


@pytest.fixture
def redis_client():
    """Provide a fresh FakeRedis client."""
    client = fakeredis.FakeRedis()
    yield client
    client.flushall()


@pytest.fixture
def store(redis_client):
    """Provide a SessionStore instance."""
    return SessionStore(redis_client, key_prefix="test:fix:session")


# ---------------------------------------------------------------------------
# Save and Load Session State
# ---------------------------------------------------------------------------


class TestSaveAndLoad:
    """Test saving and loading session state."""

    def test_save_and_load_session(self, store):
        session_id = "session-1"
        state = {
            "sender_comp_id": "SENDER",
            "target_comp_id": "TARGET",
            "state": "LOGGED_IN",
            "heartbeat_interval": 30,
        }
        store.save_session(session_id, state)
        loaded = store.load_session(session_id)
        assert loaded == state

    def test_load_nonexistent_session_returns_none(self, store):
        result = store.load_session("nonexistent")
        assert result is None

    def test_save_session_overwrites_existing(self, store):
        session_id = "session-1"
        store.save_session(session_id, {"sender_comp_id": "OLD"})
        store.save_session(session_id, {"sender_comp_id": "NEW"})
        loaded = store.load_session(session_id)
        assert loaded["sender_comp_id"] == "NEW"

    def test_save_session_with_empty_state(self, store):
        session_id = "session-empty"
        store.save_session(session_id, {})
        loaded = store.load_session(session_id)
        assert loaded == {}

    def test_save_session_with_many_fields(self, store):
        session_id = "session-complex"
        state = {
            "sender_comp_id": "BROKER1",
            "target_comp_id": "EXCHANGE1",
            "state": "CONNECTING",
            "heartbeat_interval": 60,
            "encrypt_method": 0,
            "reset_on_logon": True,
            "custom_field_1": "value1",
            "custom_field_2": "value2",
        }
        store.save_session(session_id, state)
        loaded = store.load_session(session_id)
        assert loaded == state


# ---------------------------------------------------------------------------
# Delete Session
# ---------------------------------------------------------------------------


class TestDeleteSession:
    """Test deleting session state."""

    def test_delete_session(self, store):
        session_id = "session-1"
        store.save_session(session_id, {"sender_comp_id": "SENDER"})
        store.delete_session(session_id)
        assert store.load_session(session_id) is None

    def test_delete_nonexistent_session_no_error(self, store):
        store.delete_session("nonexistent")
        # Should not raise

    def test_delete_session_does_not_affect_others(self, store):
        store.save_session("session-1", {"sender_comp_id": "S1"})
        store.save_session("session-2", {"sender_comp_id": "S2"})
        store.delete_session("session-1")
        assert store.load_session("session-1") is None
        assert store.load_session("session-2") is not None


# ---------------------------------------------------------------------------
# Sequence Number Persistence
# ---------------------------------------------------------------------------


class TestSequenceNumbers:
    """Test sequence number save/load."""

    def test_save_and_load_sequence_numbers(self, store):
        store.save_sequence_numbers("session-1", send_seq=100, recv_seq=200)
        send_seq, recv_seq = store.load_sequence_numbers("session-1")
        assert send_seq == 100
        assert recv_seq == 200

    def test_load_sequence_numbers_nonexistent_returns_none(self, store):
        result = store.load_sequence_numbers("nonexistent")
        assert result is None

    def test_save_sequence_numbers_overwrites(self, store):
        store.save_sequence_numbers("session-1", send_seq=10, recv_seq=20)
        store.save_sequence_numbers("session-1", send_seq=50, recv_seq=60)
        send_seq, recv_seq = store.load_sequence_numbers("session-1")
        assert send_seq == 50
        assert recv_seq == 60

    def test_save_sequence_numbers_large_values(self, store):
        store.save_sequence_numbers("session-1", send_seq=999999, recv_seq=888888)
        send_seq, recv_seq = store.load_sequence_numbers("session-1")
        assert send_seq == 999999
        assert recv_seq == 888888

    def test_save_sequence_numbers_zero(self, store):
        store.save_sequence_numbers("session-1", send_seq=0, recv_seq=0)
        send_seq, recv_seq = store.load_sequence_numbers("session-1")
        assert send_seq == 0
        assert recv_seq == 0

    def test_sequence_numbers_isolated_per_session(self, store):
        store.save_sequence_numbers("session-1", send_seq=10, recv_seq=20)
        store.save_sequence_numbers("session-2", send_seq=100, recv_seq=200)
        s1_send, s1_recv = store.load_sequence_numbers("session-1")
        s2_send, s2_recv = store.load_sequence_numbers("session-2")
        assert s1_send == 10
        assert s1_recv == 20
        assert s2_send == 100
        assert s2_recv == 200


# ---------------------------------------------------------------------------
# Session Recovery
# ---------------------------------------------------------------------------


class TestSessionRecovery:
    """Test full session recovery with state and sequence numbers."""

    def test_recover_session(self, store):
        session_id = "session-1"
        state = {
            "sender_comp_id": "SENDER",
            "target_comp_id": "TARGET",
            "state": "LOGGED_IN",
        }
        store.save_session(session_id, state)
        store.save_sequence_numbers(session_id, send_seq=42, recv_seq=84)
        recovered = store.recover_session(session_id)
        assert recovered is not None
        assert recovered["state"] == state
        assert recovered["send_seq_num"] == 42
        assert recovered["recv_seq_num"] == 84

    def test_recover_nonexistent_session_returns_none(self, store):
        result = store.recover_session("nonexistent")
        assert result is None

    def test_recover_session_with_state_only(self, store):
        session_id = "session-1"
        store.save_session(session_id, {"sender_comp_id": "SENDER"})
        recovered = store.recover_session(session_id)
        assert recovered is not None
        assert recovered["state"]["sender_comp_id"] == "SENDER"
        assert recovered["send_seq_num"] is None
        assert recovered["recv_seq_num"] is None

    def test_recover_session_with_seqs_only(self, store):
        session_id = "session-1"
        store.save_sequence_numbers(session_id, send_seq=10, recv_seq=20)
        recovered = store.recover_session(session_id)
        assert recovered is not None
        assert recovered["state"] is None
        assert recovered["send_seq_num"] == 10
        assert recovered["recv_seq_num"] == 20


# ---------------------------------------------------------------------------
# List Sessions
# ---------------------------------------------------------------------------


class TestListSessions:
    """Test listing active sessions."""

    def test_list_sessions_empty(self, store):
        sessions = store.list_sessions()
        assert sessions == []

    def test_list_sessions_single(self, store):
        store.save_session("session-1", {"sender_comp_id": "S1"})
        sessions = store.list_sessions()
        assert "session-1" in sessions

    def test_list_sessions_multiple(self, store):
        store.save_session("session-1", {"sender_comp_id": "S1"})
        store.save_session("session-2", {"sender_comp_id": "S2"})
        store.save_session("session-3", {"sender_comp_id": "S3"})
        sessions = store.list_sessions()
        assert len(sessions) == 3
        assert "session-1" in sessions
        assert "session-2" in sessions
        assert "session-3" in sessions

    def test_list_sessions_excludes_deleted(self, store):
        store.save_session("session-1", {"sender_comp_id": "S1"})
        store.save_session("session-2", {"sender_comp_id": "S2"})
        store.delete_session("session-1")
        sessions = store.list_sessions()
        assert "session-1" not in sessions
        assert "session-2" in sessions


# ---------------------------------------------------------------------------
# Heartbeat
# ---------------------------------------------------------------------------


class TestHeartbeat:
    """Test heartbeat tracking."""

    def test_update_heartbeat(self, store):
        store.save_session("session-1", {"sender_comp_id": "S1"})
        before = time.time()
        store.update_heartbeat("session-1")
        after = time.time()
        # Heartbeat should be stored - verify by checking session is active
        assert store.is_session_active("session-1")

    def test_update_heartbeat_nonexistent_session(self, store):
        store.update_heartbeat("nonexistent")
        # Should not raise

    def test_heartbeat_timestamp_persisted(self, store):
        store.save_session("session-1", {"sender_comp_id": "S1"})
        store.update_heartbeat("session-1")
        recovered = store.recover_session("session-1")
        assert recovered is not None
        assert "last_heartbeat" in recovered
        assert recovered["last_heartbeat"] > 0


# ---------------------------------------------------------------------------
# Session Active Check
# ---------------------------------------------------------------------------


class TestSessionActive:
    """Test session active status."""

    def test_is_session_active_true(self, store):
        store.save_session("session-1", {"sender_comp_id": "S1"})
        assert store.is_session_active("session-1") is True

    def test_is_session_active_false(self, store):
        assert store.is_session_active("nonexistent") is False

    def test_is_session_active_after_delete(self, store):
        store.save_session("session-1", {"sender_comp_id": "S1"})
        store.delete_session("session-1")
        assert store.is_session_active("session-1") is False


# ---------------------------------------------------------------------------
# Clear All
# ---------------------------------------------------------------------------


class TestClearAll:
    """Test clearing all sessions."""

    def test_clear_all_sessions(self, store):
        store.save_session("session-1", {"sender_comp_id": "S1"})
        store.save_session("session-2", {"sender_comp_id": "S2"})
        store.save_sequence_numbers("session-1", send_seq=10, recv_seq=20)
        store.clear_all()
        assert store.list_sessions() == []
        assert store.load_session("session-1") is None
        assert store.load_sequence_numbers("session-1") is None

    def test_clear_all_empty_store(self, store):
        store.clear_all()
        assert store.list_sessions() == []


# ---------------------------------------------------------------------------
# Key Prefix Isolation
# ---------------------------------------------------------------------------


class TestKeyPrefixIsolation:
    """Test that different key prefixes isolate sessions."""

    def test_different_prefixes_isolated(self, redis_client):
        store1 = SessionStore(redis_client, key_prefix="app1:fix")
        store2 = SessionStore(redis_client, key_prefix="app2:fix")
        store1.save_session("session-1", {"sender_comp_id": "S1"})
        assert store1.load_session("session-1") is not None
        assert store2.load_session("session-1") is None
