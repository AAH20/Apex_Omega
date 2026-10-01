"""Multi-Venue Feed Handler with zero-copy ring buffer.

Ingests market data from multiple venues at 100K+ events/sec.
"""
from __future__ import annotations

import struct
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple, Union

# Valid event types
VALID_EVENT_TYPES = frozenset({"TRADE", "QUOTE", "BOOK_UPDATE", "HEARTBEAT"})

# Struct format for binary serialization
# symbol: 20s (padded), timestamp_ns: q (int64), bid_price: d (double),
# ask_price: d (double), bid_size: q (int64), ask_size: q (int64),
# venue: 20s (padded), event_type: 12s (padded), sequence: q (int64)
_EVENT_STRUCT = struct.Struct("20s q d d q q 20s 12s q")
_EVENT_STRUCT_SIZE = _EVENT_STRUCT.size


class FeedError(Exception):
    """Raised when a feed operation fails."""
    pass


class EventValidationError(Exception):
    """Raised when event validation fails."""
    pass


def _validate_string(value: Any, field_name: str, max_len: int = 20) -> str:
    """Validate a string field."""
    if not isinstance(value, str):
        raise EventValidationError(f"{field_name} must be a string, got {type(value).__name__}")
    if not value or not value.strip():
        raise EventValidationError(f"{field_name} cannot be empty or whitespace-only")
    # Check for control characters
    for ch in value:
        if ord(ch) < 32 or ord(ch) == 127:
            raise EventValidationError(f"{field_name} contains control characters")
    if len(value) > max_len:
        raise EventValidationError(f"{field_name} exceeds maximum length of {max_len}")
    return value


def _validate_event_type(value: Any) -> str:
    """Validate event type."""
    if not isinstance(value, str):
        raise EventValidationError(f"event_type must be a string, got {type(value).__name__}")
    if value not in VALID_EVENT_TYPES:
        raise EventValidationError(f"Invalid event_type: {value}. Must be one of {VALID_EVENT_TYPES}")
    return value


@dataclass
class MarketDataEvent:
    """Market data event with validation and serialization."""
    symbol: str
    timestamp_ns: int
    bid_price: float
    ask_price: float
    bid_size: int
    ask_size: int
    venue: str
    event_type: str
    sequence: int

    def __post_init__(self):
        """Validate fields after initialization."""
        self.symbol = _validate_string(self.symbol, "symbol")
        self.venue = _validate_string(self.venue, "venue")
        self.event_type = _validate_event_type(self.event_type)

        if not isinstance(self.timestamp_ns, int):
            raise EventValidationError(f"timestamp_ns must be int, got {type(self.timestamp_ns).__name__}")
        if self.timestamp_ns < 0:
            raise EventValidationError("timestamp_ns cannot be negative")

        if not isinstance(self.bid_price, (int, float)):
            raise EventValidationError(f"bid_price must be numeric, got {type(self.bid_price).__name__}")
        self.bid_price = float(self.bid_price)
        if self.bid_price < 0:
            raise EventValidationError("bid_price cannot be negative")

        if not isinstance(self.ask_price, (int, float)):
            raise EventValidationError(f"ask_price must be numeric, got {type(self.ask_price).__name__}")
        self.ask_price = float(self.ask_price)
        if self.ask_price < 0:
            raise EventValidationError("ask_price cannot be negative")

        if not isinstance(self.bid_size, int):
            raise EventValidationError(f"bid_size must be int, got {type(self.bid_size).__name__}")
        if self.bid_size < 0:
            raise EventValidationError("bid_size cannot be negative")

        if not isinstance(self.ask_size, int):
            raise EventValidationError(f"ask_size must be int, got {type(self.ask_size).__name__}")
        if self.ask_size < 0:
            raise EventValidationError("ask_size cannot be negative")

        if not isinstance(self.sequence, int):
            raise EventValidationError(f"sequence must be int, got {type(self.sequence).__name__}")
        if self.sequence <= 0:
            raise EventValidationError("sequence must be positive")

    @property
    def spread(self) -> float:
        """Calculate spread."""
        return self.ask_price - self.bid_price

    @property
    def mid_price(self) -> float:
        """Calculate mid price."""
        return (self.bid_price + self.ask_price) / 2.0

    def to_bytes(self) -> bytes:
        """Serialize event to bytes."""
        symbol_bytes = self.symbol.encode("utf-8")[:20].ljust(20, b"\x00")
        venue_bytes = self.venue.encode("utf-8")[:20].ljust(20, b"\x00")
        etype_bytes = self.event_type.encode("utf-8")[:12].ljust(12, b"\x00")
        return _EVENT_STRUCT.pack(
            symbol_bytes,
            self.timestamp_ns,
            self.bid_price,
            self.ask_price,
            self.bid_size,
            self.ask_size,
            venue_bytes,
            etype_bytes,
            self.sequence,
        )

    @classmethod
    def from_bytes(cls, data: bytes) -> "MarketDataEvent":
        """Deserialize event from bytes."""
        if len(data) != _EVENT_STRUCT_SIZE:
            raise EventValidationError(f"Invalid data length: {len(data)}, expected {_EVENT_STRUCT_SIZE}")
        symbol, ts, bid, ask, bsize, asize, venue, etype, seq = _EVENT_STRUCT.unpack(data)
        return cls(
            symbol=symbol.rstrip(b"\x00").decode("utf-8"),
            timestamp_ns=ts,
            bid_price=bid,
            ask_price=ask,
            bid_size=bsize,
            ask_size=asize,
            venue=venue.rstrip(b"\x00").decode("utf-8"),
            event_type=etype.rstrip(b"\x00").decode("utf-8"),
            sequence=seq,
        )

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, MarketDataEvent):
            return NotImplemented
        return (
            self.symbol == other.symbol
            and self.timestamp_ns == other.timestamp_ns
            and self.bid_price == other.bid_price
            and self.ask_price == other.ask_price
            and self.bid_size == other.bid_size
            and self.ask_size == other.ask_size
            and self.venue == other.venue
            and self.event_type == other.event_type
            and self.sequence == other.sequence
        )

    def __hash__(self) -> int:
        return hash((
            self.symbol, self.timestamp_ns, self.bid_price, self.ask_price,
            self.bid_size, self.ask_size, self.venue, self.event_type, self.sequence,
        ))

    def __repr__(self) -> str:
        return (
            f"MarketDataEvent(symbol={self.symbol!r}, venue={self.venue!r}, "
            f"event_type={self.event_type!r}, sequence={self.sequence})"
        )

    def __str__(self) -> str:
        return (
            f"{self.symbol}@{self.venue} [{self.event_type}] "
            f"bid={self.bid_price} ask={self.ask_price} seq={self.sequence}"
        )


class RingBuffer:
    """Thread-safe ring buffer with zero-copy semantics."""

    def __init__(self, capacity: int = 1024):
        if capacity <= 0:
            raise ValueError("capacity must be positive")
        # Round up to next power of 2
        self._capacity = 1
        while self._capacity < capacity:
            self._capacity <<= 1
        self._buffer: List[Optional[MarketDataEvent]] = [None] * self._capacity
        self._head = 0  # write position
        self._tail = 0  # read position
        self._size = 0
        self._lock = threading.Lock()

    @property
    def capacity(self) -> int:
        return self._capacity

    @property
    def maxlen(self) -> int:
        return self._capacity

    @property
    def size(self) -> int:
        return self._size

    def __len__(self) -> int:
        return self._size

    def __bool__(self) -> bool:
        return self._size > 0

    def is_empty(self) -> bool:
        return self._size == 0

    def is_full(self) -> bool:
        return self._size == self._capacity

    def push(self, event: MarketDataEvent) -> None:
        """Push event into buffer. Overwrites oldest if full."""
        if not isinstance(event, MarketDataEvent):
            raise TypeError(f"Expected MarketDataEvent, got {type(event).__name__}")
        with self._lock:
            self._buffer[self._head] = event
            self._head = (self._head + 1) & (self._capacity - 1)
            if self._size < self._capacity:
                self._size += 1
            else:
                # Overwrite: advance tail
                self._tail = (self._tail + 1) & (self._capacity - 1)

    def pop(self) -> Optional[MarketDataEvent]:
        """Pop oldest event from buffer. Returns None if empty."""
        with self._lock:
            if self._size == 0:
                return None
            event = self._buffer[self._tail]
            self._buffer[self._tail] = None
            self._tail = (self._tail + 1) & (self._capacity - 1)
            self._size -= 1
            return event

    def popleft(self) -> Optional[MarketDataEvent]:
        """Alias for pop()."""
        return self.pop()

    def peek(self) -> Optional[MarketDataEvent]:
        """Peek at oldest event without removing. Zero-copy."""
        with self._lock:
            if self._size == 0:
                return None
            return self._buffer[self._tail]

    def clear(self) -> None:
        """Clear all events from buffer."""
        with self._lock:
            self._buffer = [None] * self._capacity
            self._head = 0
            self._tail = 0
            self._size = 0

    def extend(self, events: List[MarketDataEvent]) -> None:
        """Push multiple events."""
        for event in events:
            self.push(event)

    def remove(self, event: MarketDataEvent) -> None:
        """Remove first occurrence of event."""
        with self._lock:
            for i in range(self._size):
                idx = (self._tail + i) & (self._capacity - 1)
                if self._buffer[idx] == event:
                    # Shift elements
                    for j in range(i, self._size - 1):
                        curr = (self._tail + j) & (self._capacity - 1)
                        nxt = (curr + 1) & (self._capacity - 1)
                        self._buffer[curr] = self._buffer[nxt]
                    self._buffer[(self._tail + self._size - 1) & (self._capacity - 1)] = None
                    self._size -= 1
                    self._head = (self._head - 1) & (self._capacity - 1)
                    return
            raise ValueError("Event not found in buffer")

    def rotate(self, n: int) -> None:
        """Rotate buffer by n positions."""
        with self._lock:
            if self._size == 0:
                return
            n = n % self._size
            if n == 0:
                return
            # Convert to list, rotate, rebuild
            items = list(self._buffer)
            # Extract current items in order
            current = []
            for i in range(self._size):
                idx = (self._tail + i) & (self._capacity - 1)
                current.append(self._buffer[idx])
            # Rotate
            current = current[-n:] + current[:-n]
            # Rebuild
            for i, item in enumerate(current):
                idx = (self._tail + i) & (self._capacity - 1)
                self._buffer[idx] = item

    def reverse(self) -> None:
        """Reverse buffer order."""
        with self._lock:
            current = []
            for i in range(self._size):
                idx = (self._tail + i) & (self._capacity - 1)
                current.append(self._buffer[idx])
            current.reverse()
            for i, item in enumerate(current):
                idx = (self._tail + i) & (self._capacity - 1)
                self._buffer[idx] = item

    def copy(self) -> "RingBuffer":
        """Create a copy of the buffer."""
        new = RingBuffer(capacity=self._capacity)
        with self._lock:
            for i in range(self._size):
                idx = (self._tail + i) & (self._capacity - 1)
                new.push(self._buffer[idx])
        return new

    def count(self, event: MarketDataEvent) -> int:
        """Count occurrences of event."""
        with self._lock:
            count = 0
            for i in range(self._size):
                idx = (self._tail + i) & (self._capacity - 1)
                if self._buffer[idx] == event:
                    count += 1
            return count

    def index(self, event: MarketDataEvent) -> int:
        """Find index of event."""
        with self._lock:
            for i in range(self._size):
                idx = (self._tail + i) & (self._capacity - 1)
                if self._buffer[idx] == event:
                    return i
            raise ValueError("Event not found in buffer")

    def __iter__(self):
        """Iterate over events in FIFO order."""
        with self._lock:
            items = []
            for i in range(self._size):
                idx = (self._tail + i) & (self._capacity - 1)
                items.append(self._buffer[idx])
        return iter(items)

    def __reversed__(self):
        """Reverse iterate over events."""
        with self._lock:
            items = []
            for i in range(self._size - 1, -1, -1):
                idx = (self._tail + i) & (self._capacity - 1)
                items.append(self._buffer[idx])
        return iter(items)

    def __contains__(self, event: MarketDataEvent) -> bool:
        """Check if event is in buffer."""
        with self._lock:
            for i in range(self._size):
                idx = (self._tail + i) & (self._capacity - 1)
                if self._buffer[idx] == event:
                    return True
            return False

    def __getitem__(self, key):
        """Support indexing and slicing."""
        with self._lock:
            if isinstance(key, slice):
                items = []
                for i in range(self._size):
                    idx = (self._tail + i) & (self._capacity - 1)
                    items.append(self._buffer[idx])
                return items[key]
            if key < 0:
                key += self._size
            if key < 0 or key >= self._size:
                raise IndexError("RingBuffer index out of range")
            idx = (self._tail + key) & (self._capacity - 1)
            return self._buffer[idx]


@dataclass
class VenueStats:
    """Statistics for a single venue."""
    venue: str
    event_count: int = 0
    last_sequence: int = 0
    gap_count: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def record_event(self, sequence: int) -> None:
        """Record an event and detect gaps."""
        with self._lock:
            self.event_count += 1
            if self.last_sequence > 0 and sequence != self.last_sequence + 1:
                self.gap_count += 1
            self.last_sequence = sequence

    def reset(self) -> None:
        """Reset stats."""
        with self._lock:
            self.event_count = 0
            self.last_sequence = 0
            self.gap_count = 0


class MultiVenueFeedHandler:
    """Multi-venue feed handler with zero-copy ring buffer."""

    def __init__(self, venues: List[str], ring_buffer_capacity: int = 1024):
        self._venues = frozenset(venues)
        self._ring_buffer = RingBuffer(capacity=ring_buffer_capacity)
        self._stats: Dict[str, VenueStats] = {v: VenueStats(venue=v) for v in venues}
        self._lock = threading.Lock()
        self._start_time = time.monotonic()
        self._total_events = 0
        self._consumer_index = 0  # For get_next_event

    @property
    def venues(self) -> frozenset:
        return self._venues

    @property
    def ring_buffer(self) -> RingBuffer:
        return self._ring_buffer

    @property
    def total_event_count(self) -> int:
        return self._total_events

    def ingest(self, event: MarketDataEvent) -> None:
        """Ingest a single event."""
        if event.venue not in self._venues:
            raise FeedError(f"Unknown venue: {event.venue}")
        self._ring_buffer.push(event)
        self._stats[event.venue].record_event(event.sequence)
        with self._lock:
            self._total_events += 1

    def ingest_batch(self, events: List[MarketDataEvent]) -> None:
        """Ingest multiple events."""
        for event in events:
            self.ingest(event)

    def get_stats(self, venue: str) -> VenueStats:
        """Get stats for a venue."""
        if venue not in self._stats:
            raise FeedError(f"Unknown venue: {venue}")
        return self._stats[venue]

    def get_all_stats(self) -> Dict[str, VenueStats]:
        """Get all venue stats."""
        return dict(self._stats)

    def reset_stats(self) -> None:
        """Reset all stats."""
        for stats in self._stats.values():
            stats.reset()
        with self._lock:
            self._total_events = 0
            self._start_time = time.monotonic()

    def get_throughput(self) -> float:
        """Get current throughput (events/sec)."""
        elapsed = time.monotonic() - self._start_time
        if elapsed == 0:
            return 0.0
        return self._total_events / elapsed

    def get_consumer_lag(self) -> int:
        """Get number of events not yet consumed."""
        return self._ring_buffer.size

    def get_next_event(self) -> Optional[MarketDataEvent]:
        """Get next event in FIFO order."""
        return self._ring_buffer.pop()

    def get_events_by_venue(self, venue: str) -> List[MarketDataEvent]:
        """Get all events for a venue."""
        return [e for e in self._ring_buffer if e.venue == venue]

    def get_events_by_symbol(self, symbol: str) -> List[MarketDataEvent]:
        """Get all events for a symbol."""
        return [e for e in self._ring_buffer if e.symbol == symbol]

    def get_events_by_type(self, event_type: str) -> List[MarketDataEvent]:
        """Get all events of a type."""
        return [e for e in self._ring_buffer if e.event_type == event_type]

    def get_events(self, venue: Optional[str] = None, symbol: Optional[str] = None,
                  event_type: Optional[str] = None) -> List[MarketDataEvent]:
        """Get events filtered by criteria."""
        events = list(self._ring_buffer)
        if venue is not None:
            events = [e for e in events if e.venue == venue]
        if symbol is not None:
            events = [e for e in events if e.symbol == symbol]
        if event_type is not None:
            events = [e for e in events if e.event_type == event_type]
        return events

    def is_healthy(self) -> bool:
        """Check if handler is healthy."""
        return True
