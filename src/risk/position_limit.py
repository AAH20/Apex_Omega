"""Position Limit Enforcer — per symbol, venue, and account limits.

Implements the Position Limit Framework from the ApexAMM Risk Framework spec.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple


class EnforcementAction(Enum):
    PASS = "pass"
    WARN = "warn"
    BLOCK = "block"
    HALT = "halt"


@dataclass
class PositionLimit:
    max_position: float = 1_000_000.0
    max_exposure: float = 10_000_000.0
    max_venue_position: float = 500_000.0
    max_venue_exposure: float = 5_000_000.0
    max_gross_position: float = 2_000_000.0
    max_gross_exposure: float = 20_000_000.0
    warn_threshold_pct: float = 80.0
    block_threshold_pct: float = 100.0
    halt_threshold_pct: float = 120.0

    def is_disabled(self, limit_name: str) -> bool:
        return getattr(self, limit_name, 0) <= 0


@dataclass
class LimitBreach:
    limit_type: str
    current_value: float
    limit_value: float
    utilization_pct: float


@dataclass
class EnforcementDecision:
    action: EnforcementAction
    breaches: List[LimitBreach]
    symbol: str
    venue: str
    account: str


@dataclass
class UtilizationReport:
    symbol_utilization: Dict[str, Dict[str, float]] = field(default_factory=dict)
    venue_utilization: Dict[str, Dict[str, float]] = field(default_factory=dict)


class PositionTracker:
    """Tracks positions per (symbol, venue, account) tuple."""

    def __init__(self) -> None:
        self._positions: Dict[Tuple[str, str, str], Tuple[float, float]] = {}

    def update(self, symbol: str, venue: str, account: str, quantity: float, price: float) -> None:
        key = (symbol, venue, account)
        current_qty, current_price = self._positions.get(key, (0.0, 0.0))
        self._positions[key] = (current_qty + quantity, price)

    def get_position(self, symbol: str, venue: str, account: str) -> float:
        return self._positions.get((symbol, venue, account), (0.0, 0.0))[0]

    def get_exposure(self, symbol: str, venue: str, account: str) -> float:
        qty, price = self._positions.get((symbol, venue, account), (0.0, 0.0))
        return abs(qty * price)

    def get_gross_position(self, account: str) -> float:
        total = 0.0
        for (sym, ven, acc), (qty, _) in self._positions.items():
            if acc == account:
                total += abs(qty)
        return total

    def get_gross_exposure(self, account: str) -> float:
        total = 0.0
        for (sym, ven, acc), (qty, price) in self._positions.items():
            if acc == account:
                total += abs(qty * price)
        return total

    def get_net_position(self, account: str) -> float:
        total = 0.0
        for (sym, ven, acc), (qty, _) in self._positions.items():
            if acc == account:
                total += qty
        return total

    def get_venue_position(self, venue: str, account: str) -> float:
        total = 0.0
        for (sym, ven, acc), (qty, _) in self._positions.items():
            if ven == venue and acc == account:
                total += abs(qty)
        return total

    def get_venue_exposure(self, venue: str, account: str) -> float:
        total = 0.0
        for (sym, ven, acc), (qty, price) in self._positions.items():
            if ven == venue and acc == account:
                total += abs(qty * price)
        return total

    def reset(self) -> None:
        self._positions.clear()


class PositionLimitEnforcer:
    """Enforces position limits per symbol, venue, and account."""

    def __init__(self, default_limits: Optional[PositionLimit] = None) -> None:
        self._default_limits = default_limits or PositionLimit()
        self._symbol_limits: Dict[str, PositionLimit] = {}
        self._venue_limits: Dict[str, PositionLimit] = {}
        self._account_limits: Dict[str, PositionLimit] = {}
        self._tracker = PositionTracker()

    def set_symbol_limit(self, symbol: str, limits: PositionLimit) -> None:
        self._symbol_limits[symbol] = limits

    def set_venue_limit(self, venue: str, limits: PositionLimit) -> None:
        self._venue_limits[venue] = limits

    def set_account_limit(self, account: str, limits: PositionLimit) -> None:
        self._account_limits[account] = limits

    def remove_symbol_limit(self, symbol: str) -> None:
        self._symbol_limits.pop(symbol, None)

    def remove_venue_limit(self, venue: str) -> None:
        self._venue_limits.pop(venue, None)

    def remove_account_limit(self, account: str) -> None:
        self._account_limits.pop(account, None)

    def update_default_limits(self, limits: PositionLimit) -> None:
        self._default_limits = limits

    def update_position(self, symbol: str, venue: str, account: str, quantity: float, price: float) -> None:
        self._tracker.update(symbol, venue, account, quantity, price)

    def get_effective_limit(self, symbol: str, venue: str, account: str) -> PositionLimit:
        """Resolve limit priority: symbol > venue > account > default."""
        if symbol in self._symbol_limits:
            return self._symbol_limits[symbol]
        if venue in self._venue_limits:
            return self._venue_limits[venue]
        if account in self._account_limits:
            return self._account_limits[account]
        return self._default_limits

    def get_tracker(self) -> PositionTracker:
        return self._tracker

    def check_order(
        self,
        symbol: str,
        venue: str,
        account: str,
        quantity: float,
        price: float,
    ) -> EnforcementDecision:
        lim = self.get_effective_limit(symbol, venue, account)
        breaches: List[LimitBreach] = []

        # Current values from tracker
        current_position = self._tracker.get_position(symbol, venue, account)
        current_exposure = self._tracker.get_exposure(symbol, venue, account)
        current_venue_position = self._tracker.get_venue_position(venue, account)
        current_venue_exposure = self._tracker.get_venue_exposure(venue, account)
        current_gross_position = self._tracker.get_gross_position(account)
        current_gross_exposure = self._tracker.get_gross_exposure(account)

        # Projected values after this order
        projected_position = current_position + quantity
        projected_exposure = abs(projected_position * price)
        projected_venue_position = current_venue_position + abs(quantity)
        projected_venue_exposure = current_venue_exposure + abs(quantity * price)
        projected_gross_position = current_gross_position + abs(quantity)
        projected_gross_exposure = current_gross_exposure + abs(quantity * price)

        # Check each limit
        checks = [
            ("max_position", abs(projected_position), lim.max_position),
            ("max_exposure", projected_exposure, lim.max_exposure),
            ("max_venue_position", projected_venue_position, lim.max_venue_position),
            ("max_venue_exposure", projected_venue_exposure, lim.max_venue_exposure),
            ("max_gross_position", projected_gross_position, lim.max_gross_position),
            ("max_gross_exposure", projected_gross_exposure, lim.max_gross_exposure),
        ]

        for limit_type, current_val, limit_val in checks:
            if limit_val <= 0:
                continue  # disabled
            utilization = (current_val / limit_val) * 100.0
            if utilization >= lim.halt_threshold_pct:
                breaches.append(LimitBreach(limit_type, current_val, limit_val, utilization))
            elif utilization >= lim.block_threshold_pct:
                breaches.append(LimitBreach(limit_type, current_val, limit_val, utilization))
            elif utilization >= lim.warn_threshold_pct:
                breaches.append(LimitBreach(limit_type, current_val, limit_val, utilization))

        # Determine action from worst breach
        action = EnforcementAction.PASS
        for b in breaches:
            if b.utilization_pct >= lim.halt_threshold_pct:
                action = EnforcementAction.HALT
                break
            elif b.utilization_pct >= lim.block_threshold_pct:
                action = EnforcementAction.BLOCK
            elif b.utilization_pct >= lim.warn_threshold_pct:
                if action == EnforcementAction.PASS:
                    action = EnforcementAction.WARN

        return EnforcementDecision(
            action=action,
            breaches=breaches,
            symbol=symbol,
            venue=venue,
            account=account,
        )


class LimitUtilizationReporter:
    """Reports limit utilization metrics."""

    def __init__(self, enforcer: PositionLimitEnforcer) -> None:
        self._enforcer = enforcer

    def generate_report(self) -> UtilizationReport:
        report = UtilizationReport()
        tracker = self._enforcer.get_tracker()

        # Collect all unique symbols and venues from tracker
        symbols: set = set()
        venues: set = set()
        for (sym, ven, acc) in tracker._positions:
            symbols.add(sym)
            venues.add(ven)

        for sym in symbols:
            lim = self._enforcer.get_effective_limit(sym, "binance", "acct-1")
            pos = abs(tracker.get_position(sym, "binance", "acct-1"))
            exp = tracker.get_exposure(sym, "binance", "acct-1")
            report.symbol_utilization[sym] = {
                "position_utilization_pct": (pos / lim.max_position * 100.0) if lim.max_position > 0 else 0.0,
                "exposure_utilization_pct": (exp / lim.max_exposure * 100.0) if lim.max_exposure > 0 else 0.0,
            }

        for ven in venues:
            lim = self._enforcer.get_effective_limit("BTC-USD", ven, "acct-1")
            vpos = tracker.get_venue_position(ven, "acct-1")
            vexp = tracker.get_venue_exposure(ven, "acct-1")
            report.venue_utilization[ven] = {
                "position_utilization_pct": (vpos / lim.max_venue_position * 100.0) if lim.max_venue_position > 0 else 0.0,
                "exposure_utilization_pct": (vexp / lim.max_venue_exposure * 100.0) if lim.max_venue_exposure > 0 else 0.0,
            }

        return report
