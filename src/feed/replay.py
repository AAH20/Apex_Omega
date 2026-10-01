"""Feed Replay — historical market data replay for backtesting."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterator, List, Optional


@dataclass
class ReplayTick:
    """A single tick of market data."""

    symbol: str
    timestamp: int
    price: float
    volume: int
    bid: Optional[float] = None
    ask: Optional[float] = None


class FeedReplay:
    """Replays historical market data for backtesting.

    Iterates over a sequence of ReplayTick objects in order,
    with optional filtering by symbol, time range, and limit.
    """

    def __init__(
        self,
        ticks: List[ReplayTick],
        symbol: Optional[str] = None,
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
        limit: Optional[int] = None,
        callback: Optional[Callable[[ReplayTick], None]] = None,
    ) -> None:
        self._ticks = ticks
        self._symbol = symbol
        self._start_time = start_time
        self._end_time = end_time
        self._limit = limit
        self._callback = callback
        self._position = 0

    def _filtered_ticks(self) -> List[ReplayTick]:
        """Return ticks matching the configured filters."""
        result = self._ticks
        if self._symbol is not None:
            result = [t for t in result if t.symbol == self._symbol]
        if self._start_time is not None:
            result = [t for t in result if t.timestamp >= self._start_time]
        if self._end_time is not None:
            result = [t for t in result if t.timestamp <= self._end_time]
        if self._limit is not None:
            result = result[: self._limit]
        return result

    def __iter__(self) -> Iterator[ReplayTick]:
        """Iterate over all filtered ticks from the beginning."""
        self._position = 0
        filtered = self._filtered_ticks()
        for tick in filtered:
            self._position += 1
            if self._callback is not None:
                self._callback(tick)
            yield tick

    def __next__(self) -> ReplayTick:
        """Return the next tick in the replay."""
        filtered = self._filtered_ticks()
        if self._position >= len(filtered):
            raise StopIteration
        tick = filtered[self._position]
        self._position += 1
        if self._callback is not None:
            self._callback(tick)
        return tick

    @property
    def position(self) -> int:
        """Current position in the replay."""
        return self._position

    @property
    def tick_count(self) -> int:
        """Total number of ticks after filtering."""
        return len(self._filtered_ticks())

    def reset(self) -> None:
        """Reset position to the beginning."""
        self._position = 0

    def seek(self, position: int) -> None:
        """Seek to a specific position."""
        if position < 0 or position > self.tick_count:
            raise IndexError(f"Position {position} out of range [0, {self.tick_count}]")
        self._position = position
