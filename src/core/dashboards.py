"""APEX-OS Real-Time Dashboards, Alerting Rules, and SLA Monitoring.

Provides:
- TimeSeries: ring-buffer metric storage
- Dashboard / DashboardPanel: real-time dashboard with panel history
- AlertRule / AlertManager: threshold-based alerting with firing tracking
- SLO / SLAMonitor: SLO tracking with error budget and availability calculation
"""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class MetricType(Enum):
    """Types of metrics a dashboard panel can display."""

    GAUGE = "gauge"
    COUNTER = "counter"
    HISTOGRAM = "histogram"
    SUMMARY = "summary"


class AlertSeverity(Enum):
    """Severity levels for alerts."""

    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class AlertState(Enum):
    """Lifecycle state of an alert."""

    FIRING = "firing"
    RESOLVED = "resolved"


class SLOStatus(Enum):
    """Status of an SLO."""

    MET = "met"
    BREACHED = "breached"
    UNKNOWN = "unknown"


# ---------------------------------------------------------------------------
# TimeSeries
# ---------------------------------------------------------------------------


class TimeSeries:
    """A thread-safe ring buffer for metric data points."""

    def __init__(self, name: str, max_points: int = 1000) -> None:
        self.name = name
        self.max_points = max_points
        self._data: deque[float] = deque(maxlen=max_points)
        self._lock = threading.Lock()

    def append(self, value: float) -> None:
        """Add a new data point."""
        with self._lock:
            self._data.append(value)

    def values(self) -> list[float]:
        """Return all stored values as a list."""
        with self._lock:
            return list(self._data)

    def latest(self) -> float | None:
        """Return the most recent value, or None if empty."""
        with self._lock:
            return self._data[-1] if self._data else None

    def mean(self) -> float:
        """Return the mean of all values, or 0.0 if empty."""
        with self._lock:
            if not self._data:
                return 0.0
            return sum(self._data) / len(self._data)

    def max(self) -> float:
        """Return the maximum value, or 0.0 if empty."""
        with self._lock:
            return max(self._data) if self._data else 0.0

    def min(self) -> float:
        """Return the minimum value, or 0.0 if empty."""
        with self._lock:
            return min(self._data) if self._data else 0.0

    def clear(self) -> None:
        """Remove all data points."""
        with self._lock:
            self._data.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._data)


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------


@dataclass
class DashboardPanel:
    """A single panel in a dashboard."""

    name: str
    metric_type: MetricType
    unit: str = ""
    current_value: float = 0.0
    history: TimeSeries = field(default_factory=lambda: TimeSeries("default", max_points=1000))
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.history or self.history.name == "default":
            self.history = TimeSeries(self.name, max_points=1000)

    def update(self, value: float) -> None:
        """Update the panel with a new value."""
        self.current_value = value
        self.history.append(value)

    def to_dict(self) -> dict[str, Any]:
        """Serialize panel to dict."""
        return {
            "name": self.name,
            "metric_type": self.metric_type.value,
            "unit": self.unit,
            "value": self.current_value,
            "history_length": len(self.history),
        }


class Dashboard:
    """A real-time dashboard containing multiple panels."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.panels: list[DashboardPanel] = []
        self._panel_map: dict[str, DashboardPanel] = {}
        self._lock = threading.Lock()

    def add_panel(self, panel: DashboardPanel) -> None:
        """Add a panel to the dashboard."""
        with self._lock:
            if panel.name in self._panel_map:
                raise ValueError(f"Panel '{panel.name}' already exists")
            self.panels.append(panel)
            self._panel_map[panel.name] = panel

    def remove_panel(self, name: str) -> None:
        """Remove a panel by name."""
        with self._lock:
            if name not in self._panel_map:
                raise KeyError(f"Panel '{name}' not found")
            panel = self._panel_map.pop(name)
            self.panels.remove(panel)

    def get_panel(self, name: str) -> DashboardPanel:
        """Get a panel by name."""
        with self._lock:
            if name not in self._panel_map:
                raise KeyError(f"Panel '{name}' not found")
            return self._panel_map[name]

    def update_panel(self, name: str, value: float) -> None:
        """Update a panel's current value."""
        panel = self.get_panel(name)
        panel.update(value)

    def to_dict(self) -> dict[str, Any]:
        """Serialize dashboard to dict."""
        with self._lock:
            return {
                "name": self.name,
                "panels": [p.to_dict() for p in self.panels],
            }


# ---------------------------------------------------------------------------
# Alerting
# ---------------------------------------------------------------------------


@dataclass
class Alert:
    """A fired alert instance."""

    rule_name: str
    metric_name: str
    severity: AlertSeverity
    value: float
    threshold: float
    state: AlertState
    timestamp: datetime = field(default_factory=datetime.utcnow)
    message: str = ""


class AlertRule:
    """A threshold-based alerting rule."""

    def __init__(
        self,
        name: str,
        metric_name: str,
        threshold: float,
        comparison: str,
        severity: AlertSeverity,
        description: str = "",
    ) -> None:
        self.name = name
        self.metric_name = metric_name
        self.threshold = threshold
        self.comparison = comparison
        self.severity = severity
        self.description = description
        self.enabled = True

    def evaluate(self, value: float) -> bool:
        """Check if the value triggers this rule."""
        if not self.enabled:
            return False
        match self.comparison:
            case "gt":
                return value > self.threshold
            case "gte":
                return value >= self.threshold
            case "lt":
                return value < self.threshold
            case "lte":
                return value <= self.threshold
            case "eq":
                return value == self.threshold
            case "neq":
                return value != self.threshold
            case _:
                raise ValueError(f"Invalid comparison operator: {self.comparison}")

    def enable(self) -> None:
        self.enabled = True

    def disable(self) -> None:
        self.enabled = False


class AlertManager:
    """Manages alert rules and tracks firing/resolved alerts."""

    def __init__(self) -> None:
        self.rules: list[AlertRule] = []
        self._rule_map: dict[str, AlertRule] = {}
        self._firing: dict[str, Alert] = {}
        self._lock = threading.Lock()

    def add_rule(self, rule: AlertRule) -> None:
        """Add an alert rule."""
        with self._lock:
            if rule.name in self._rule_map:
                raise ValueError(f"Rule '{rule.name}' already exists")
            self.rules.append(rule)
            self._rule_map[rule.name] = rule

    def remove_rule(self, name: str) -> None:
        """Remove an alert rule."""
        with self._lock:
            if name not in self._rule_map:
                raise KeyError(f"Rule '{name}' not found")
            rule = self._rule_map.pop(name)
            self.rules.remove(rule)

    def evaluate_all(self, metric_values: dict[str, float]) -> list[Alert]:
        """Evaluate all rules against current metric values."""
        alerts: list[Alert] = []
        with self._lock:
            for rule in self.rules:
                if not rule.enabled:
                    continue
                value = metric_values.get(rule.metric_name)
                if value is None:
                    continue
                if rule.evaluate(value):
                    alert = Alert(
                        rule_name=rule.name,
                        metric_name=rule.metric_name,
                        severity=rule.severity,
                        value=value,
                        threshold=rule.threshold,
                        state=AlertState.FIRING,
                    )
                    self._firing[rule.name] = alert
                    alerts.append(alert)
                else:
                    # Rule no longer firing — remove from firing if present
                    self._firing.pop(rule.name, None)
        return alerts

    @property
    def firing_alerts(self) -> dict[str, Alert]:
        """Return currently firing alerts."""
        with self._lock:
            return dict(self._firing)

    def get_firing_alerts(self) -> list[Alert]:
        """Return list of currently firing alerts."""
        with self._lock:
            return list(self._firing.values())

    def clear_firing_alerts(self) -> None:
        """Clear all firing alerts."""
        with self._lock:
            self._firing.clear()


# ---------------------------------------------------------------------------
# SLO Monitoring
# ---------------------------------------------------------------------------


@dataclass
class SLO:
    """A Service Level Objective definition."""

    name: str
    target: float  # target percentage (e.g. 99.9)
    window_seconds: int = 86400  # default 24h
    description: str = ""


@dataclass
class SLOReport:
    """A report on SLO status."""

    name: str
    target: float
    good_count: int
    bad_count: int
    availability_pct: float
    error_budget_remaining_pct: float
    status: SLOStatus
    window_seconds: int = 86400
    timestamp: datetime = field(default_factory=datetime.utcnow)


class SLAMonitor:
    """Monitors SLOs by recording good/bad events."""

    def __init__(self) -> None:
        self.slos: list[SLO] = []
        self._slo_map: dict[str, SLO] = {}
        self._good_counts: dict[str, int] = {}
        self._bad_counts: dict[str, int] = {}
        self._lock = threading.Lock()

    def add_slo(self, slo: SLO) -> None:
        """Register an SLO."""
        with self._lock:
            if slo.name in self._slo_map:
                raise ValueError(f"SLO '{slo.name}' already exists")
            self.slos.append(slo)
            self._slo_map[slo.name] = slo
            self._good_counts[slo.name] = 0
            self._bad_counts[slo.name] = 0

    def remove_slo(self, name: str) -> None:
        """Remove an SLO."""
        with self._lock:
            if name not in self._slo_map:
                raise KeyError(f"SLO '{name}' not found")
            slo = self._slo_map.pop(name)
            self.slos.remove(slo)
            self._good_counts.pop(name, None)
            self._bad_counts.pop(name, None)

    def record(self, slo_name: str, good: bool, latency_ms: float | None = None) -> None:
        """Record a good or bad event for an SLO."""
        with self._lock:
            if slo_name not in self._slo_map:
                raise KeyError(f"SLO '{slo_name}' not found")
            if good:
                self._good_counts[slo_name] += 1
            else:
                self._bad_counts[slo_name] += 1

    def get_slo_report(self, name: str) -> SLOReport:
        """Generate a report for a specific SLO."""
        with self._lock:
            if name not in self._slo_map:
                raise KeyError(f"SLO '{name}' not found")
            slo = self._slo_map[name]
            good = self._good_counts.get(name, 0)
            bad = self._bad_counts.get(name, 0)
            total = good + bad

            if total == 0:
                availability = 0.0
                status = SLOStatus.UNKNOWN
                error_budget = 0.0
            else:
                availability = (good / total) * 100.0
                error_rate = (bad / total) * 100.0
                budget = 100.0 - slo.target
                error_budget = budget - error_rate
                if availability >= slo.target:
                    status = SLOStatus.MET
                else:
                    status = SLOStatus.BREACHED

            return SLOReport(
                name=name,
                target=slo.target,
                good_count=good,
                bad_count=bad,
                availability_pct=availability,
                error_budget_remaining_pct=error_budget,
                status=status,
                window_seconds=slo.window_seconds,
            )

    def get_all_reports(self) -> list[SLOReport]:
        """Generate reports for all SLOs."""
        with self._lock:
            reports: list[SLOReport] = []
            for slo in self.slos:
                good = self._good_counts.get(slo.name, 0)
                bad = self._bad_counts.get(slo.name, 0)
                total = good + bad

                if total == 0:
                    availability = 0.0
                    status = SLOStatus.UNKNOWN
                    error_budget = 0.0
                else:
                    availability = (good / total) * 100.0
                    error_rate = (bad / total) * 100.0
                    budget = 100.0 - slo.target
                    error_budget = budget - error_rate
                    if availability >= slo.target:
                        status = SLOStatus.MET
                    else:
                        status = SLOStatus.BREACHED

                reports.append(
                    SLOReport(
                        name=slo.name,
                        target=slo.target,
                        good_count=good,
                        bad_count=bad,
                        availability_pct=availability,
                        error_budget_remaining_pct=error_budget,
                        status=status,
                        window_seconds=slo.window_seconds,
                    )
                )
            return reports

    def clear(self, name: str) -> None:
        """Reset counters for an SLO."""
        with self._lock:
            if name not in self._slo_map:
                raise KeyError(f"SLO '{name}' not found")
            self._good_counts[name] = 0
            self._bad_counts[name] = 0
