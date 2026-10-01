"""Real-time feed statistics: VWAP, TWAP, volatility."""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field


@dataclass
class FeedStatistics:
    """Streaming market data statistics."""

    _prices: deque[float] = field(default_factory=deque)
    _volumes: deque[float] = field(default_factory=deque)
    _pv_sum: float = 0.0
    _v_sum: float = 0.0

    def add_tick(self, price: float, volume: float) -> None:
        """Add a price/volume tick."""
        self._prices.append(price)
        self._volumes.append(volume)
        self._pv_sum += price * volume
        self._v_sum += volume

    def vwap(self) -> float:
        """Volume-weighted average price."""
        if self._v_sum == 0.0:
            return 0.0
        return self._pv_sum / self._v_sum

    def twap(self) -> float:
        """Time-weighted average price (simple mean of prices)."""
        if not self._prices:
            return 0.0
        return sum(self._prices) / len(self._prices)

    def volatility(self) -> float:
        """Population standard deviation of prices."""
        n = len(self._prices)
        if n < 2:
            return 0.0
        mean = sum(self._prices) / n
        variance = sum((p - mean) ** 2 for p in self._prices) / n
        return math.sqrt(variance)
