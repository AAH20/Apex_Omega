"""Tests for APEX-OS Core Orchestrator — TDD: write tests first."""

from __future__ import annotations

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.core.orchestrator import (
    Orchestrator,
    Subsystem,
    SubsystemState,
    HealthStatus,
    DependencyError,
    LifecycleError,
    ShutdownError,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class DummySubsystem(Subsystem):
    """Minimal concrete subsystem for testing."""

    def __init__(self, name: str, dependencies: list[str] | None = None):
        super().__init__(name, dependencies or [])
        self.started = False
        self.stopped = False
        self.start_count = 0
        self.stop_count = 0

    async def start(self):
        self.started = True
        self.start_count += 1

    async def stop(self):
        self.stopped = True
        self.stop_count += 1

    async def health_check(self) -> HealthStatus:
        if self.state != SubsystemState.RUNNING:
            return HealthStatus.UNKNOWN
        return HealthStatus.HEALTHY


class FailingStartSubsystem(DummySubsystem):
    async def start(self):
        raise RuntimeError("start failed")


class FailingStopSubsystem(DummySubsystem):
    async def stop(self):
        raise RuntimeError("stop failed")


class FailingHealthSubsystem(DummySubsystem):
    async def health_check(self) -> HealthStatus:
        return HealthStatus.UNHEALTHY


class SlowSubsystem(DummySubsystem):
    def __init__(self, name: str, delay: float = 0.1, **kwargs):
        super().__init__(name, **kwargs)
        self.delay = delay

    async def start(self):
        await asyncio.sleep(self.delay)
        await super().start()

    async def stop(self):
        await asyncio.sleep(self.delay)
        await super().stop()


# ---------------------------------------------------------------------------
# Subsystem base class tests
# ---------------------------------------------------------------------------

class TestSubsystem:
    def test_subsystem_has_name(self):
        sub = DummySubsystem("test")
        assert sub.name == "test"

    def test_subsystem_default_state_is_created(self):
        sub = DummySubsystem("test")
        assert sub.state == SubsystemState.CREATED

    def test_subsystem_default_dependencies_empty(self):
        sub = DummySubsystem("test")
        assert sub.dependencies == []

    def test_subsystem_stores_dependencies(self):
        sub = DummySubsystem("test", ["a", "b"])
        assert sub.dependencies == ["a", "b"]

    def test_subsystem_default_health_is_unknown(self):
        sub = DummySubsystem("test")
        assert sub.health == HealthStatus.UNKNOWN


# ---------------------------------------------------------------------------
# Orchestrator registration tests
# ---------------------------------------------------------------------------

class TestOrchestratorRegistration:
    def test_register_subsystem(self):
        orch = Orchestrator()
        sub = DummySubsystem("test")
        orch.register(sub)
        assert "test" in orch.subsystems

    def test_register_duplicate_name_raises(self):
        orch = Orchestrator()
        orch.register(DummySubsystem("test"))
        with pytest.raises(ValueError, match="already registered"):
            orch.register(DummySubsystem("test"))

    def test_register_multiple_subsystems(self):
        orch = Orchestrator()
        orch.register(DummySubsystem("a"))
        orch.register(DummySubsystem("b"))
        orch.register(DummySubsystem("c"))
        assert len(orch.subsystems) == 3

    def test_unregister_subsystem(self):
        orch = Orchestrator()
        orch.register(DummySubsystem("test"))
        orch.unregister("test")
        assert "test" not in orch.subsystems

    def test_unregister_nonexistent_raises(self):
        orch = Orchestrator()
        with pytest.raises(KeyError):
            orch.unregister("nonexistent")


# ---------------------------------------------------------------------------
# Dependency injection / resolution tests
# ---------------------------------------------------------------------------

class TestDependencyResolution:
    def test_no_dependencies_starts_immediately(self):
        orch = Orchestrator()
        sub = DummySubsystem("solo")
        orch.register(sub)
        # Should not raise
        asyncio.run(orch.start())

    def test_single_dependency_resolved(self):
        orch = Orchestrator()
        orch.register(DummySubsystem("base"))
        orch.register(DummySubsystem("dependent", ["base"]))
        asyncio.run(orch.start())
        assert orch.get("base").started
        assert orch.get("dependent").started

    def test_dependency_order_respected(self):
        """Dependent must start after its dependency."""
        orch = Orchestrator()
        order = []

        class OrderTracker(DummySubsystem):
            async def start(self):
                order.append(self.name)
                await super().start()

        orch.register(OrderTracker("first"))
        orch.register(OrderTracker("second", ["first"]))
        orch.register(OrderTracker("third", ["second"]))
        asyncio.run(orch.start())
        assert order == ["first", "second", "third"]

    def test_missing_dependency_raises(self):
        orch = Orchestrator()
        orch.register(DummySubsystem("orphan", ["missing"]))
        with pytest.raises(DependencyError, match="missing"):
            asyncio.run(orch.start())

    def test_circular_dependency_raises(self):
        orch = Orchestrator()
        orch.register(DummySubsystem("a", ["b"]))
        orch.register(DummySubsystem("b", ["a"]))
        with pytest.raises(DependencyError, match="[Cc]ircular|cycle"):
            asyncio.run(orch.start())

    def test_diamond_dependency(self):
        """A -> B, A -> C, B -> D, C -> D — D must start first."""
        orch = Orchestrator()
        order = []

        class Diamond(DummySubsystem):
            async def start(self):
                order.append(self.name)
                await super().start()

        orch.register(Diamond("d"))
        orch.register(Diamond("b", ["d"]))
        orch.register(Diamond("c", ["d"]))
        orch.register(Diamond("a", ["b", "c"]))
        asyncio.run(orch.start())
        assert order[0] == "d"
        assert order[-1] == "a"


# ---------------------------------------------------------------------------
# Lifecycle state tests
# ---------------------------------------------------------------------------

class TestLifecycle:
    def test_state_transitions_on_start(self):
        orch = Orchestrator()
        sub = DummySubsystem("test")
        orch.register(sub)
        assert sub.state == SubsystemState.CREATED
        asyncio.run(orch.start())
        assert sub.state == SubsystemState.RUNNING

    def test_state_transitions_on_stop(self):
        orch = Orchestrator()
        sub = DummySubsystem("test")
        orch.register(sub)
        asyncio.run(orch.start())
        asyncio.run(orch.stop())
        assert sub.state == SubsystemState.STOPPED

    def test_start_already_started_raises(self):
        orch = Orchestrator()
        orch.register(DummySubsystem("test"))
        asyncio.run(orch.start())
        with pytest.raises(LifecycleError):
            asyncio.run(orch.start())

    def test_stop_already_stopped_is_idempotent(self):
        orch = Orchestrator()
        orch.register(DummySubsystem("test"))
        asyncio.run(orch.start())
        asyncio.run(orch.stop())
        asyncio.run(orch.stop())  # should not raise

    def test_failing_start_marks_unhealthy(self):
        orch = Orchestrator()
        sub = FailingStartSubsystem("bad")
        orch.register(sub)
        asyncio.run(orch.start())
        assert sub.state == SubsystemState.ERROR

    def test_failing_stop_marks_error(self):
        orch = Orchestrator()
        sub = FailingStopSubsystem("bad")
        orch.register(sub)
        asyncio.run(orch.start())
        asyncio.run(orch.stop())
        assert sub.state == SubsystemState.ERROR


# ---------------------------------------------------------------------------
# Health monitoring tests
# ---------------------------------------------------------------------------

class TestHealthMonitoring:
    def test_healthy_subsystem_reports_healthy(self):
        orch = Orchestrator()
        sub = DummySubsystem("ok")
        orch.register(sub)
        asyncio.run(orch.start())
        asyncio.run(orch.check_health())
        assert sub.health == HealthStatus.HEALTHY

    def test_unhealthy_subsystem_reports_unhealthy(self):
        orch = Orchestrator()
        sub = FailingHealthSubsystem("sick")
        orch.register(sub)
        asyncio.run(orch.start())
        asyncio.run(orch.check_health())
        assert sub.health == HealthStatus.UNHEALTHY

    def test_overall_health_aggregates(self):
        orch = Orchestrator()
        orch.register(DummySubsystem("ok"))
        orch.register(FailingHealthSubsystem("sick"))
        asyncio.run(orch.start())
        asyncio.run(orch.check_health())
        assert orch.overall_health == HealthStatus.UNHEALTHY

    def test_overall_health_all_healthy(self):
        orch = Orchestrator()
        orch.register(DummySubsystem("a"))
        orch.register(DummySubsystem("b"))
        asyncio.run(orch.start())
        asyncio.run(orch.check_health())
        assert orch.overall_health == HealthStatus.HEALTHY

    def test_health_check_before_start(self):
        orch = Orchestrator()
        sub = DummySubsystem("test")
        orch.register(sub)
        asyncio.run(orch.check_health())
        assert sub.health == HealthStatus.UNKNOWN


# ---------------------------------------------------------------------------
# Graceful shutdown tests
# ---------------------------------------------------------------------------

class TestGracefulShutdown:
    def test_shutdown_stops_all_subsystems(self):
        orch = Orchestrator()
        orch.register(DummySubsystem("a"))
        orch.register(DummySubsystem("b"))
        orch.register(DummySubsystem("c"))
        asyncio.run(orch.start())
        asyncio.run(orch.stop())
        for sub in orch.subsystems.values():
            assert sub.stopped

    def test_shutdown_reverse_order(self):
        """Subsystems must stop in reverse dependency order."""
        orch = Orchestrator()
        stop_order = []

        class OrderStop(DummySubsystem):
            async def stop(self):
                stop_order.append(self.name)
                await super().stop()

        orch.register(OrderStop("first"))
        orch.register(OrderStop("second", ["first"]))
        orch.register(OrderStop("third", ["second"]))
        asyncio.run(orch.start())
        asyncio.run(orch.stop())
        assert stop_order == ["third", "second", "first"]

    def test_shutdown_with_timeout(self):
        orch = Orchestrator()
        orch.register(SlowSubsystem("slow", delay=5.0))
        asyncio.run(orch.start())
        # Should not hang — timeout kicks in
        asyncio.run(orch.stop(timeout=0.1))

    def test_shutdown_idempotent(self):
        orch = Orchestrator()
        sub = DummySubsystem("test")
        orch.register(sub)
        asyncio.run(orch.start())
        asyncio.run(orch.stop())
        asyncio.run(orch.stop())  # second stop should be safe
        assert sub.stop_count == 1

    def test_shutdown_calls_cleanup_on_error(self):
        """Even if a subsystem fails to stop, others should still stop."""
        orch = Orchestrator()
        orch.register(FailingStopSubsystem("bad"))
        orch.register(DummySubsystem("good"))
        asyncio.run(orch.start())
        asyncio.run(orch.stop())
        assert orch.get("good").stopped


# ---------------------------------------------------------------------------
# Integration / edge case tests
# ---------------------------------------------------------------------------

class TestIntegration:
    def test_full_lifecycle(self):
        orch = Orchestrator()
        orch.register(DummySubsystem("db"))
        orch.register(DummySubsystem("cache", ["db"]))
        orch.register(DummySubsystem("api", ["cache", "db"]))

        asyncio.run(orch.start())
        assert orch.overall_health == HealthStatus.UNKNOWN
        asyncio.run(orch.check_health())
        assert orch.overall_health == HealthStatus.HEALTHY
        asyncio.run(orch.stop())

        for sub in orch.subsystems.values():
            assert sub.state == SubsystemState.STOPPED

    def test_get_nonexistent_subsystem(self):
        orch = Orchestrator()
        with pytest.raises(KeyError):
            orch.get("nonexistent")

    def test_concurrent_health_checks(self):
        orch = Orchestrator()
        for i in range(5):
            orch.register(DummySubsystem(f"sub{i}"))
        asyncio.run(orch.start())
        asyncio.run(orch.check_health())
        for sub in orch.subsystems.values():
            assert sub.health == HealthStatus.HEALTHY

    def test_empty_orchestrator_start_stop(self):
        orch = Orchestrator()
        asyncio.run(orch.start())
        asyncio.run(orch.stop())
        assert orch.overall_health == HealthStatus.UNKNOWN

    def test_restart_subsystem(self):
        orch = Orchestrator()
        sub = DummySubsystem("test")
        orch.register(sub)
        asyncio.run(orch.start())
        asyncio.run(orch.stop())
        asyncio.run(orch.start())
        assert sub.start_count == 2
        assert sub.state == SubsystemState.RUNNING
