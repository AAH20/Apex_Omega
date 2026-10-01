"""APEX-OS Health Check System.

Provides health endpoints for all subsystems, dependency monitoring,
readiness/liveness probes, and health aggregation.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class HealthStatus(Enum):
    """Health status enumeration."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


@dataclass
class HealthCheckResult:
    """Result of a single health check."""

    name: str
    status: HealthStatus
    response_time_ms: float
    message: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.utcnow)


@dataclass
class HealthReport:
    """Aggregated health report."""

    status: HealthStatus
    version: str
    uptime_seconds: float
    checks: list[HealthCheckResult] = field(default_factory=list)
    timestamp: datetime = field(default_factory=datetime.utcnow)


class HealthCheck(ABC):
    """Abstract base class for health checks."""

    def __init__(self, name: str, timeout_seconds: float = 5.0) -> None:
        self.name = name
        self.timeout_seconds = timeout_seconds

    @abstractmethod
    def check(self) -> HealthCheckResult:
        """Execute the health check and return the result."""
        ...


class DependencyMonitor:
    """Monitors dependencies and their health status."""

    def __init__(self) -> None:
        self._dependencies: dict[str, HealthCheck] = {}

    def register(self, name: str, check: HealthCheck) -> None:
        """Register a dependency health check."""
        self._dependencies[name] = check

    def unregister(self, name: str) -> None:
        """Unregister a dependency health check."""
        self._dependencies.pop(name, None)

    def get_dependency(self, name: str) -> HealthCheck | None:
        """Get a registered dependency by name."""
        return self._dependencies.get(name)

    def check_all(self) -> list[HealthCheckResult]:
        """Run all registered dependency checks."""
        return [check.check() for check in self._dependencies.values()]


class LivenessProbe:
    """Liveness probe — indicates whether the process is running."""

    def __init__(self) -> None:
        self._start_time = time.monotonic()

    def is_alive(self) -> bool:
        """Return True if the process is alive."""
        return True

    def get_uptime(self) -> float:
        """Return uptime in seconds."""
        return time.monotonic() - self._start_time


class ReadinessProbe:
    """Readiness probe — indicates whether the service is ready to accept traffic."""

    def __init__(self, aggregator: HealthAggregator) -> None:
        self._aggregator = aggregator

    def is_ready(self) -> bool:
        """Return True if the service is ready (all checks healthy)."""
        report = self._aggregator.aggregate()
        return report.status == HealthStatus.HEALTHY


class HealthAggregator:
    """Aggregates health checks into a unified report."""

    def __init__(self, version: str = "1.0.0") -> None:
        self._version = version
        self._checks: dict[str, HealthCheck] = {}
        self._start_time = time.monotonic()

    def add_check(self, check: HealthCheck) -> None:
        """Add a health check."""
        self._checks[check.name] = check

    def remove_check(self, name: str) -> None:
        """Remove a health check by name."""
        self._checks.pop(name, None)

    def aggregate(self) -> HealthReport:
        """Run all checks and produce an aggregated report."""
        results = [check.check() for check in self._checks.values()]
        status = self._compute_overall_status(results)
        return HealthReport(
            status=status,
            version=self._version,
            uptime_seconds=time.monotonic() - self._start_time,
            checks=results,
        )

    @staticmethod
    def _compute_overall_status(results: list[HealthCheckResult]) -> HealthStatus:
        """Compute overall status from individual check results."""
        if not results:
            return HealthStatus.HEALTHY
        statuses = {r.status for r in results}
        if HealthStatus.UNHEALTHY in statuses:
            return HealthStatus.UNHEALTHY
        if HealthStatus.DEGRADED in statuses:
            return HealthStatus.DEGRADED
        return HealthStatus.HEALTHY


class HealthEndpoint:
    """HTTP-facing health endpoint."""

    def __init__(
        self,
        aggregator: HealthAggregator,
        readiness: ReadinessProbe,
        liveness: LivenessProbe,
    ) -> None:
        self._aggregator = aggregator
        self._readiness = readiness
        self._liveness = liveness

    def health(self) -> dict[str, Any]:
        """Return full health report as a dict."""
        report = self._aggregator.aggregate()
        return {
            "status": report.status.value,
            "version": report.version,
            "uptime_seconds": report.uptime_seconds,
            "checks": [
                {
                    "name": c.name,
                    "status": c.status.value,
                    "response_time_ms": c.response_time_ms,
                    "message": c.message,
                }
                for c in report.checks
            ],
        }

    def readiness(self) -> dict[str, Any]:
        """Return readiness status as a dict."""
        return {"ready": self._readiness.is_ready()}

    def liveness(self) -> dict[str, Any]:
        """Return liveness status as a dict."""
        return {
            "alive": self._liveness.is_alive(),
            "uptime_seconds": self._liveness.get_uptime(),
        }