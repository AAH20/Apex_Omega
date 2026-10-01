"""Venue Session Manager — multi-session management, failover, load balancing."""
import threading
from dataclasses import dataclass
from typing import Optional


@dataclass
class VenueSession:
    """Represents a connection session to a trading venue."""

    venue_id: str
    host: str
    port: int
    weight: int = 1
    max_connections: int = 10
    is_active: bool = True
    current_connections: int = 0


class SessionManager:
    """Manages multiple venue sessions with failover and load balancing."""

    def __init__(self):
        self._sessions: dict[str, VenueSession] = {}
        self._lock = threading.RLock()
        self._sequence: list[str] = []
        self._seq_index: int = 0
        self._sequence_dirty: bool = True

    def _rebuild_sequence(self) -> None:
        """Rebuild the weighted round-robin sequence."""
        self._sequence = []
        for vid, session in self._sessions.items():
            self._sequence.extend([vid] * session.weight)
        self._seq_index = 0
        self._sequence_dirty = False

    def add_venue(
        self,
        venue_id: str,
        host: str,
        port: int,
        weight: int = 1,
        max_connections: int = 10,
    ) -> None:
        """Register a new venue."""
        with self._lock:
            if venue_id in self._sessions:
                raise ValueError(f"Venue '{venue_id}' already exists")
            self._sessions[venue_id] = VenueSession(
                venue_id=venue_id,
                host=host,
                port=port,
                weight=weight,
                max_connections=max_connections,
            )
            self._sequence_dirty = True

    def remove_venue(self, venue_id: str) -> None:
        """Remove a venue."""
        with self._lock:
            if venue_id not in self._sessions:
                raise KeyError(f"Venue '{venue_id}' not found")
            del self._sessions[venue_id]
            self._sequence_dirty = True

    def get_session(self, venue_id: str) -> Optional[VenueSession]:
        """Get a session by venue ID, or None if not found."""
        with self._lock:
            return self._sessions.get(venue_id)

    def list_sessions(self) -> list[VenueSession]:
        """Return all registered sessions."""
        with self._lock:
            return list(self._sessions.values())

    def get_active_sessions(self) -> list[VenueSession]:
        """Return all active (non-failed) sessions."""
        with self._lock:
            return [s for s in self._sessions.values() if s.is_active]

    def acquire_session(self, venue_id: Optional[str] = None) -> Optional[VenueSession]:
        """Acquire a session, optionally specifying a venue.

        If venue_id is None, load-balances across active venues using
        weighted round-robin. Returns None if no session is available.
        """
        with self._lock:
            if venue_id is not None:
                session = self._sessions.get(venue_id)
                if session is None or not session.is_active:
                    return None
                if session.current_connections >= session.max_connections:
                    return None
                session.current_connections += 1
                return session

            # Load balance using weighted round-robin
            if self._sequence_dirty or not self._sequence:
                self._rebuild_sequence()
            if not self._sequence:
                return None

            n = len(self._sequence)
            for _ in range(n):
                vid = self._sequence[self._seq_index]
                self._seq_index = (self._seq_index + 1) % n
                session = self._sessions.get(vid)
                if (
                    session
                    and session.is_active
                    and session.current_connections < session.max_connections
                ):
                    session.current_connections += 1
                    return session
            return None

    def release_session(self, venue_id: str) -> None:
        """Release a connection on a venue."""
        with self._lock:
            session = self._sessions.get(venue_id)
            if session and session.current_connections > 0:
                session.current_connections -= 1

    def mark_failed(self, venue_id: str) -> None:
        """Mark a venue as failed (inactive)."""
        with self._lock:
            session = self._sessions.get(venue_id)
            if session:
                session.is_active = False

    def mark_recovered(self, venue_id: str) -> None:
        """Mark a venue as recovered (active)."""
        with self._lock:
            session = self._sessions.get(venue_id)
            if session:
                session.is_active = True

    def failover(self, venue_id: str) -> VenueSession:
        """Fail over from a venue to the next available one.

        Marks the current venue as failed, releases its connections,
        and returns the next available session.
        """
        with self._lock:
            old = self._sessions.get(venue_id)
            if old is None:
                raise KeyError(f"Venue '{venue_id}' not found")
            old.is_active = False
            old.current_connections = 0

            # Find next available using weighted round-robin
            if self._sequence_dirty or not self._sequence:
                self._rebuild_sequence()
            n = len(self._sequence)
            for _ in range(n):
                vid = self._sequence[self._seq_index]
                self._seq_index = (self._seq_index + 1) % n
                session = self._sessions.get(vid)
                if (
                    session
                    and session.is_active
                    and session.current_connections < session.max_connections
                ):
                    session.current_connections += 1
                    return session
            raise RuntimeError("No available sessions for failover")

    def get_least_loaded_session(self) -> Optional[VenueSession]:
        """Return the active session with the fewest connections."""
        with self._lock:
            active = [s for s in self._sessions.values() if s.is_active]
            if not active:
                return None
            return min(active, key=lambda s: s.current_connections)

    def get_session_stats(self, venue_id: str) -> dict:
        """Return stats for a venue."""
        with self._lock:
            session = self._sessions.get(venue_id)
            if session is None:
                raise KeyError(f"Venue '{venue_id}' not found")
            return {
                "venue_id": session.venue_id,
                "current_connections": session.current_connections,
                "is_active": session.is_active,
                "weight": session.weight,
            }

    def health_check(self) -> dict:
        """Return health status for all venues."""
        with self._lock:
            return {
                vid: {
                    "is_active": s.is_active,
                    "current_connections": s.current_connections,
                }
                for vid, s in self._sessions.items()
            }

    def close(self) -> None:
        """Close all sessions and clear state."""
        with self._lock:
            self._sessions.clear()
            self._sequence.clear()
            self._seq_index = 0
            self._sequence_dirty = True
