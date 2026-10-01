"""APEX-OS Core Orchestrator — subsystem lifecycle, DI, health, shutdown."""

from __future__ import annotations

import asyncio
import logging
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class SubsystemState(Enum):
    CREATED = "created"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"
    ERROR = "error"


class HealthStatus(Enum):
    UNKNOWN = "unknown"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class DependencyError(Exception):
    """Raised when subsystem dependencies cannot be resolved."""


class LifecycleError(Exception):
    """Raised when an invalid lifecycle transition is attempted."""


class ShutdownError(Exception):
    """Raised when shutdown encounters an unrecoverable error."""


# ---------------------------------------------------------------------------
# Subsystem base class
# ---------------------------------------------------------------------------

class Subsystem:
    """Base class for all APEX-OS subsystems."""

    def __init__(self, name: str, dependencies: list[str] | None = None):
        self.name = name
        self.dependencies = dependencies or []
        self.state = SubsystemState.CREATED
        self.health = HealthStatus.UNKNOWN

    async def start(self) -> None:
        """Start the subsystem. Override in subclasses."""
        self.state = SubsystemState.RUNNING

    async def stop(self) -> None:
        """Stop the subsystem. Override in subclasses."""
        self.state = SubsystemState.STOPPED

    async def health_check(self) -> HealthStatus:
        """Return current health. Override in subclasses."""
        return self.health


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

class Orchestrator:
    """Manages subsystem lifecycle, dependency injection, health, shutdown."""

    def __init__(self):
        self.subsystems: dict[str, Subsystem] = {}
        self._started = False
        self._stopped = True
        self._health_check_interval: float = 30.0
        self._health_task: asyncio.Task | None = None

    # -- Registration -------------------------------------------------------

    def register(self, subsystem: Subsystem) -> None:
        if subsystem.name in self.subsystems:
            raise ValueError(f"Subsystem '{subsystem.name}' already registered")
        self.subsystems[subsystem.name] = subsystem
        logger.debug("Registered subsystem: %s", subsystem.name)

    def unregister(self, name: str) -> None:
        if name not in self.subsystems:
            raise KeyError(f"Subsystem '{name}' not found")
        del self.subsystems[name]
        logger.debug("Unregistered subsystem: %s", name)

    def get(self, name: str) -> Subsystem:
        if name not in self.subsystems:
            raise KeyError(f"Subsystem '{name}' not found")
        return self.subsystems[name]

    # -- Dependency resolution ----------------------------------------------

    def _resolve_start_order(self) -> list[str]:
        """Topological sort of subsystems by dependency graph."""
        visited: set[str] = set()
        order: list[str] = []
        visiting: set[str] = set()

        def visit(name: str) -> None:
            if name in visiting:
                raise DependencyError(f"Circular dependency detected involving '{name}'")
            if name in visited:
                return
            visiting.add(name)
            sub = self.subsystems.get(name)
            if sub is None:
                raise DependencyError(f"Dependency '{name}' not found")
            for dep in sub.dependencies:
                if dep not in self.subsystems:
                    raise DependencyError(
                        f"Subsystem '{name}' depends on unknown '{dep}'"
                    )
                visit(dep)
            visiting.discard(name)
            visited.add(name)
            order.append(name)

        for name in self.subsystems:
            visit(name)
        return order

    # -- Lifecycle ----------------------------------------------------------

    async def start(self) -> None:
        if self._started:
            raise LifecycleError("Orchestrator already started")
        self._started = True
        self._stopped = False

        order = self._resolve_start_order()
        logger.info("Starting %d subsystems in order: %s", len(order), order)

        for name in order:
            sub = self.subsystems[name]
            sub.state = SubsystemState.STARTING
            try:
                await sub.start()
                sub.state = SubsystemState.RUNNING
                logger.debug("Started subsystem: %s", name)
            except Exception as exc:
                sub.state = SubsystemState.ERROR
                logger.error("Failed to start subsystem %s: %s", name, exc)
                # Continue starting others — partial startup is allowed

        self._start_health_monitor()
        logger.info("Orchestrator started")

    async def stop(self, timeout: float = 30.0) -> None:
        if self._stopped:
            return  # idempotent
        self._stopped = True
        self._started = False

        self._stop_health_monitor()

        order = self._resolve_start_order()
        stop_order = list(reversed(order))
        logger.info("Stopping %d subsystems in order: %s", len(stop_order), stop_order)

        for name in stop_order:
            sub = self.subsystems[name]
            sub.state = SubsystemState.STOPPING
            try:
                await asyncio.wait_for(sub.stop(), timeout=timeout)
                sub.state = SubsystemState.STOPPED
                logger.debug("Stopped subsystem: %s", name)
            except asyncio.TimeoutError:
                sub.state = SubsystemState.ERROR
                logger.error("Timeout stopping subsystem %s", name)
            except Exception as exc:
                sub.state = SubsystemState.ERROR
                logger.error("Error stopping subsystem %s: %s", name, exc)

        logger.info("Orchestrator stopped")

    # -- Health monitoring --------------------------------------------------

    def _start_health_monitor(self) -> None:
        """Start periodic health checks in background."""
        if self._health_task is None or self._health_task.done():
            self._health_task = asyncio.create_task(self._health_loop())

    def _stop_health_monitor(self) -> None:
        """Stop the health monitor task."""
        if self._health_task and not self._health_task.done():
            self._health_task.cancel()

    async def _health_loop(self) -> None:
        """Periodically check health of all subsystems."""
        while not self._stopped:
            await asyncio.sleep(self._health_check_interval)
            if self._stopped:
                break
            try:
                await self.check_health()
            except Exception as exc:
                logger.error("Health check loop error: %s", exc)

    async def check_health(self) -> dict[str, HealthStatus]:
        """Check health of all subsystems. Returns name->status mapping."""
        results: dict[str, HealthStatus] = {}
        for name, sub in self.subsystems.items():
            try:
                sub.health = await sub.health_check()
            except Exception as exc:
                logger.error("Health check failed for %s: %s", name, exc)
                sub.health = HealthStatus.UNHEALTHY
            results[name] = sub.health
        return results

    @property
    def overall_health(self) -> HealthStatus:
        """Aggregate health across all subsystems."""
        if not self.subsystems:
            return HealthStatus.UNKNOWN
        statuses = [s.health for s in self.subsystems.values()]
        if any(s == HealthStatus.UNHEALTHY for s in statuses):
            return HealthStatus.UNHEALTHY
        if any(s == HealthStatus.DEGRADED for s in statuses):
            return HealthStatus.DEGRADED
        if all(s == HealthStatus.HEALTHY for s in statuses):
            return HealthStatus.HEALTHY
        return HealthStatus.UNKNOWN

    # -- Context manager ----------------------------------------------------

    async def __aenter__(self) -> Orchestrator:
        await self.start()
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.stop()
