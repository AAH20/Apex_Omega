"""FIX Session Store — Redis-backed persistent session state.

Provides persistent storage for FIX session state, sequence numbers,
and heartbeat tracking with full recovery support.
"""

from __future__ import annotations

import json
import time
from typing import Any, Optional

import redis


class SessionStore:
    """Redis-backed store for FIX session state and sequence numbers.

    Stores session state as JSON in Redis hashes, sequence numbers in
    separate keys, and supports full session recovery after restarts.
    """

    def __init__(self, redis_client: redis.Redis, key_prefix: str = "fix:session") -> None:
        """Initialize the session store.

        Args:
            redis_client: A Redis client instance.
            key_prefix: Prefix for all Redis keys to isolate stores.
        """
        self._redis = redis_client
        self._prefix = key_prefix

    def _session_key(self, session_id: str) -> str:
        """Build the Redis key for session state."""
        return f"{self._prefix}:state:{session_id}"

    def _seq_key(self, session_id: str) -> str:
        """Build the Redis key for sequence numbers."""
        return f"{self._prefix}:seq:{session_id}"

    def _heartbeat_key(self, session_id: str) -> str:
        """Build the Redis key for heartbeat timestamp."""
        return f"{self._prefix}:hb:{session_id}"

    def _index_key(self) -> str:
        """Build the Redis key for the session index set."""
        return f"{self._prefix}:index"

    def save_session(self, session_id: str, state: dict[str, Any]) -> None:
        """Save session state to Redis.

        Args:
            session_id: Unique session identifier.
            state: Dictionary of session state fields.
        """
        key = self._session_key(session_id)
        self._redis.set(key, json.dumps(state))
        self._redis.sadd(self._index_key(), session_id)

    def load_session(self, session_id: str) -> Optional[dict[str, Any]]:
        """Load session state from Redis.

        Args:
            session_id: Unique session identifier.

        Returns:
            The session state dict, or None if not found.
        """
        key = self._session_key(session_id)
        data = self._redis.get(key)
        if data is None:
            return None
        return json.loads(data)

    def delete_session(self, session_id: str) -> None:
        """Delete session state and associated data from Redis.

        Args:
            session_id: Unique session identifier.
        """
        self._redis.delete(self._session_key(session_id))
        self._redis.delete(self._seq_key(session_id))
        self._redis.delete(self._heartbeat_key(session_id))
        self._redis.srem(self._index_key(), session_id)

    def save_sequence_numbers(
        self, session_id: str, send_seq: int, recv_seq: int
    ) -> None:
        """Save sequence numbers for a session.

        Args:
            session_id: Unique session identifier.
            send_seq: Next expected send sequence number.
            recv_seq: Next expected receive sequence number.
        """
        key = self._seq_key(session_id)
        self._redis.set(key, json.dumps({"send_seq": send_seq, "recv_seq": recv_seq}))
        self._redis.sadd(self._index_key(), session_id)

    def load_sequence_numbers(
        self, session_id: str
    ) -> Optional[tuple[int, int]]:
        """Load sequence numbers for a session.

        Args:
            session_id: Unique session identifier.

        Returns:
            Tuple of (send_seq, recv_seq), or None if not found.
        """
        key = self._seq_key(session_id)
        data = self._redis.get(key)
        if data is None:
            return None
        parsed = json.loads(data)
        return (parsed["send_seq"], parsed["recv_seq"])

    def recover_session(self, session_id: str) -> Optional[dict[str, Any]]:
        """Recover full session state including sequence numbers.

        Args:
            session_id: Unique session identifier.

        Returns:
            Dict with 'state', 'send_seq_num', 'recv_seq_num', and
            'last_heartbeat' keys, or None if session not found.
        """
        state = self.load_session(session_id)
        seq_nums = self.load_sequence_numbers(session_id)
        heartbeat_raw = self._redis.get(self._heartbeat_key(session_id))

        # Check if any data exists for this session
        if state is None and seq_nums is None and heartbeat_raw is None:
            return None

        result: dict[str, Any] = {
            "state": state,
            "send_seq_num": seq_nums[0] if seq_nums else None,
            "recv_seq_num": seq_nums[1] if seq_nums else None,
        }

        if heartbeat_raw is not None:
            result["last_heartbeat"] = float(heartbeat_raw)

        return result

    def list_sessions(self) -> list[str]:
        """List all active session IDs.

        Returns:
            List of session ID strings.
        """
        members = self._redis.smembers(self._index_key())
        return sorted([m.decode() if isinstance(m, bytes) else m for m in members])

    def update_heartbeat(self, session_id: str) -> None:
        """Update the heartbeat timestamp for a session.

        Args:
            session_id: Unique session identifier.
        """
        self._redis.set(self._heartbeat_key(session_id), str(time.time()))

    def is_session_active(self, session_id: str) -> bool:
        """Check if a session has stored data.

        Args:
            session_id: Unique session identifier.

        Returns:
            True if the session exists in the store.
        """
        return self._redis.exists(self._session_key(session_id)) > 0

    def clear_all(self) -> None:
        """Clear all sessions and associated data from the store."""
        # Find all keys with our prefix and delete them
        pattern = f"{self._prefix}:*"
        keys = self._redis.keys(pattern)
        if keys:
            self._redis.delete(*keys)
