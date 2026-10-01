"""FIX Heartbeat Monitor — configurable interval, missed heartbeat detection, and test requests."""
from __future__ import annotations

import threading
import time
from enum import Enum, auto
from typing import Callable, Optional


class HeartbeatState(Enum):
    """Health state of the heartbeat monitor."""
    UNKNOWN = auto()
    HEALTHY = auto()
    UNHEALTHY = auto()
    CRITICAL = auto()


class HeartbeatMonitor:
    """Monitors FIX heartbeat health with configurable interval and missed-beat detection.

    Args:
        interval_s: Expected heartbeat interval in seconds (must be positive).
        max_missed: Number of missed heartbeats before state becomes UNHEALTHY (must be positive).
        clock: Optional clock function returning current time (defaults to time.time).
    """

    def __init__(
        self,
        interval_s: float = 30.0,
        max_missed: int = 3,
        clock: Optional[Callable[[], float]] = None,
    ) -> None:
        if interval_s <= 0:
            raise ValueError("interval_s must be positive")
        if max_missed <= 0:
            raise ValueError("max_missed must be positive")
        self._interval_s = interval_s
        self._max_missed = max_missed
        self._clock = clock or time.time
        self._lock = threading.Lock()
        self._last_heartbeat_time: Optional[float] = None
        self._missed_count = 0
        self._state = HeartbeatState.UNKNOWN
        self._test_pending = False
        self._test_request_id = 0
        self._last_test_request_id: Optional[str] = None
        self._test_sent_time: Optional[float] = None

    @property
    def interval_s(self) -> float:
        return self._interval_s

    @property
    def max_missed(self) -> int:
        return self._max_missed

    @property
    def state(self) -> HeartbeatState:
        with self._lock:
            return self._state

    @property
    def missed_count(self) -> int:
        with self._lock:
            return self._missed_count

    @property
    def last_test_request_id(self) -> Optional[str]:
        with self._lock:
            return self._last_test_request_id

    def time_since_last_heartbeat(self) -> Optional[float]:
        """Return seconds since last heartbeat, or None if no heartbeat recorded."""
        with self._lock:
            if self._last_heartbeat_time is None:
                return None
            return self._clock() - self._last_heartbeat_time

    def is_overdue(self) -> bool:
        """Return True if the time since last heartbeat exceeds the interval."""
        with self._lock:
            if self._last_heartbeat_time is None:
                return False
            return (self._clock() - self._last_heartbeat_time) > self._interval_s

    def is_healthy(self) -> bool:
        """Return True if the monitor is in HEALTHY state."""
        with self._lock:
            return self._state == HeartbeatState.HEALTHY

    def is_test_pending(self) -> bool:
        """Return True if a test request has been sent but not yet answered."""
        with self._lock:
            return self._test_pending

    def is_test_timed_out(self) -> bool:
        """Return True if a pending test request has exceeded the interval."""
        with self._lock:
            if not self._test_pending or self._test_sent_time is None:
                return False
            return (self._clock() - self._test_sent_time) > self._interval_s

    def record_heartbeat(self) -> None:
        """Record that a heartbeat was received."""
        with self._lock:
            self._last_heartbeat_time = self._clock()
            self._missed_count = 0
            self._state = HeartbeatState.HEALTHY
            self._test_pending = False
            self._test_sent_time = None

    def check(self) -> None:
        """Check if a heartbeat is overdue and update missed count and state."""
        with self._lock:
            if self._last_heartbeat_time is None:
                return
            if (self._clock() - self._last_heartbeat_time) > self._interval_s:
                self._missed_count += 1
                if self._missed_count >= self._max_missed * 2:
                    self._state = HeartbeatState.CRITICAL
                elif self._missed_count >= self._max_missed:
                    self._state = HeartbeatState.UNHEALTHY
                else:
                    self._state = HeartbeatState.HEALTHY

    def send_test_request(self) -> str:
        """Send a test request and mark it as pending. Returns the test request ID."""
        with self._lock:
            self._test_request_id += 1
            test_id = f"TEST-{self._test_request_id}"
            self._last_test_request_id = test_id
            self._test_pending = True
            self._test_sent_time = self._clock()
            return test_id

    def record_test_response(self) -> None:
        """Record that a test response was received, clearing the pending flag."""
        with self._lock:
            self._test_pending = False
            self._test_sent_time = None

    def reset(self) -> None:
        """Reset all state to initial values."""
        with self._lock:
            self._last_heartbeat_time = None
            self._missed_count = 0
            self._state = HeartbeatState.UNKNOWN
            self._test_pending = False
            self._test_request_id = 0
            self._last_test_request_id = None
            self._test_sent_time = None
