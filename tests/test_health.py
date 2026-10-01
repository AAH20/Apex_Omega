"""Unit tests for APEX-OS Health Check System.

TDD: These tests were written BEFORE the implementation.
They define the expected behavior of the health check system.
"""

import time
import pytest
from datetime import datetime
from unittest.mock import MagicMock, patch

from src.core.health import (
    HealthStatus,
    HealthCheckResult,
    HealthReport,
    HealthCheck,
    DependencyMonitor,
    ReadinessProbe,
    LivenessProbe,
    HealthAggregator,
    HealthEndpoint,
)


# ---------------------------------------------------------------------------
# Test HealthStatus enum
# ---------------------------------------------------------------------------

class TestHealthStatus:
    def test_health_status_values(self):
        assert HealthStatus.HEALTHY.value == "healthy"
        assert HealthStatus.DEGRADED.value == "degraded"
        assert HealthStatus.UNHEALTHY.value == "unhealthy"

    def test_health_status_enum_members(self):
        assert len(HealthStatus) == 3
        assert HealthStatus.HEALTHY is not None
        assert HealthStatus.DEGRADED is not None
        assert HealthStatus.UNHEALTHY is not None


# ---------------------------------------------------------------------------
# Test HealthCheckResult dataclass
# ---------------------------------------------------------------------------

class TestHealthCheckResult:
    def test_create_result_with_required_fields(self):
        result = HealthCheckResult(
            name="db_check",
            status=HealthStatus.HEALTHY,
            response_time_ms=12.5,
        )
        assert result.name == "db_check"
        assert result.status == HealthStatus.HEALTHY
        assert result.response_time_ms == 12.5
        assert result.message == ""
        assert isinstance(result.metadata, dict)
        assert isinstance(result.timestamp, datetime)

    def test_create_result_with_all_fields(self):
        result = HealthCheckResult(
            name="cache_check",
            status=HealthStatus.DEGRADED,
            response_time_ms=100.0,
            message="High latency",
            metadata={"latency": 100},
        )
        assert result.name == "cache_check"
        assert result.status == HealthStatus.DEGRADED
        assert result.response_time_ms == 100.0
        assert result.message == "High latency"
        assert result.metadata == {"latency": 100}


# ---------------------------------------------------------------------------
# Test HealthReport dataclass
# ---------------------------------------------------------------------------

class TestHealthReport:
    def test_create_report(self):
        checks = [
            HealthCheckResult(name="db", status=HealthStatus.HEALTHY, response_time_ms=5.0),
            HealthCheckResult(name="cache", status=HealthStatus.DEGRADED, response_time_ms=50.0),
        ]
        report = HealthReport(
            status=HealthStatus.DEGRADED,
            version="1.0.0",
            uptime_seconds=3600.0,
            checks=checks,
        )
        assert report.status == HealthStatus.DEGRADED
        assert report.version == "1.0.0"
        assert report.uptime_seconds == 3600.0
        assert len(report.checks) == 2
        assert isinstance(report.timestamp, datetime)


# ---------------------------------------------------------------------------
# Test HealthCheck base class
# ---------------------------------------------------------------------------

class TestHealthCheck:
    def test_health_check_is_abstract(self):
        with pytest.raises(TypeError):
            HealthCheck(name="test")

    def test_concrete_health_check(self):
        class ConcreteCheck(HealthCheck):
            def check(self):
                return HealthCheckResult(
                    name=self.name,
                    status=HealthStatus.HEALTHY,
                    response_time_ms=1.0,
                )

        check = ConcreteCheck(name="test_check", timeout_seconds=3.0)
        assert check.name == "test_check"
        assert check.timeout_seconds == 3.0
        result = check.check()
        assert result.status == HealthStatus.HEALTHY
        assert result.name == "test_check"


# ---------------------------------------------------------------------------
# Test DependencyMonitor
# ---------------------------------------------------------------------------

class TestDependencyMonitor:
    def test_register_dependency(self):
        monitor = DependencyMonitor()
        check = MagicMock(spec=HealthCheck)
        check.name = "db"
        monitor.register("db", check)
        assert monitor.get_dependency("db") is check

    def test_unregister_dependency(self):
        monitor = DependencyMonitor()
        check = MagicMock(spec=HealthCheck)
        check.name = "db"
        monitor.register("db", check)
        monitor.unregister("db")
        assert monitor.get_dependency("db") is None

    def test_get_nonexistent_dependency_returns_none(self):
        monitor = DependencyMonitor()
        assert monitor.get_dependency("nonexistent") is None

    def test_check_all_returns_results(self):
        monitor = DependencyMonitor()
        check1 = MagicMock(spec=HealthCheck)
        check1.name = "db"
        check1.check.return_value = HealthCheckResult(
            name="db", status=HealthStatus.HEALTHY, response_time_ms=5.0
        )
        check2 = MagicMock(spec=HealthCheck)
        check2.name = "cache"
        check2.check.return_value = HealthCheckResult(
            name="cache", status=HealthStatus.UNHEALTHY, response_time_ms=0.0, message="Connection refused"
        )
        monitor.register("db", check1)
        monitor.register("cache", check2)
        results = monitor.check_all()
        assert len(results) == 2
        assert results[0].status == HealthStatus.HEALTHY
        assert results[1].status == HealthStatus.UNHEALTHY

    def test_check_all_with_no_dependencies(self):
        monitor = DependencyMonitor()
        results = monitor.check_all()
        assert results == []

    def test_register_overwrites_existing(self):
        monitor = DependencyMonitor()
        check1 = MagicMock(spec=HealthCheck)
        check1.name = "db"
        check2 = MagicMock(spec=HealthCheck)
        check2.name = "db"
        monitor.register("db", check1)
        monitor.register("db", check2)
        assert monitor.get_dependency("db") is check2


# ---------------------------------------------------------------------------
# Test LivenessProbe
# ---------------------------------------------------------------------------

class TestLivenessProbe:
    def test_liveness_probe_is_alive(self):
        probe = LivenessProbe()
        assert probe.is_alive() is True

    def test_liveness_probe_uptime(self):
        probe = LivenessProbe()
        uptime = probe.get_uptime()
        assert uptime >= 0.0

    def test_liveness_probe_uptime_increases(self):
        probe = LivenessProbe()
        uptime1 = probe.get_uptime()
        time.sleep(0.01)
        uptime2 = probe.get_uptime()
        assert uptime2 > uptime1


# ---------------------------------------------------------------------------
# Test ReadinessProbe
# ---------------------------------------------------------------------------

class TestReadinessProbe:
    def test_readiness_probe_ready_when_healthy(self):
        aggregator = MagicMock(spec=HealthAggregator)
        report = MagicMock(spec=HealthReport)
        report.status = HealthStatus.HEALTHY
        aggregator.aggregate.return_value = report
        probe = ReadinessProbe(aggregator)
        assert probe.is_ready() is True

    def test_readiness_probe_not_ready_when_unhealthy(self):
        aggregator = MagicMock(spec=HealthAggregator)
        report = MagicMock(spec=HealthReport)
        report.status = HealthStatus.UNHEALTHY
        aggregator.aggregate.return_value = report
        probe = ReadinessProbe(aggregator)
        assert probe.is_ready() is False

    def test_readiness_probe_not_ready_when_degraded(self):
        aggregator = MagicMock(spec=HealthAggregator)
        report = MagicMock(spec=HealthReport)
        report.status = HealthStatus.DEGRADED
        aggregator.aggregate.return_value = report
        probe = ReadinessProbe(aggregator)
        assert probe.is_ready() is False


# ---------------------------------------------------------------------------
# Test HealthAggregator
# ---------------------------------------------------------------------------

class TestHealthAggregator:
    def test_add_check(self):
        aggregator = HealthAggregator(version="1.0.0")
        check = MagicMock(spec=HealthCheck)
        check.name = "db"
        aggregator.add_check(check)
        report = aggregator.aggregate()
        assert len(report.checks) == 1

    def test_remove_check(self):
        aggregator = HealthAggregator(version="1.0.0")
        check = MagicMock(spec=HealthCheck)
        check.name = "db"
        aggregator.add_check(check)
        aggregator.remove_check("db")
        report = aggregator.aggregate()
        assert len(report.checks) == 0

    def test_aggregate_all_healthy(self):
        aggregator = HealthAggregator(version="1.0.0")
        check1 = MagicMock(spec=HealthCheck)
        check1.name = "db"
        check1.check.return_value = HealthCheckResult(
            name="db", status=HealthStatus.HEALTHY, response_time_ms=5.0
        )
        check2 = MagicMock(spec=HealthCheck)
        check2.name = "cache"
        check2.check.return_value = HealthCheckResult(
            name="cache", status=HealthStatus.HEALTHY, response_time_ms=2.0
        )
        aggregator.add_check(check1)
        aggregator.add_check(check2)
        report = aggregator.aggregate()
        assert report.status == HealthStatus.HEALTHY
        assert len(report.checks) == 2

    def test_aggregate_with_degraded(self):
        aggregator = HealthAggregator(version="1.0.0")
        check1 = MagicMock(spec=HealthCheck)
        check1.name = "db"
        check1.check.return_value = HealthCheckResult(
            name="db", status=HealthStatus.HEALTHY, response_time_ms=5.0
        )
        check2 = MagicMock(spec=HealthCheck)
        check2.name = "cache"
        check2.check.return_value = HealthCheckResult(
            name="cache", status=HealthStatus.DEGRADED, response_time_ms=100.0
        )
        aggregator.add_check(check1)
        aggregator.add_check(check2)
        report = aggregator.aggregate()
        assert report.status == HealthStatus.DEGRADED

    def test_aggregate_with_unhealthy(self):
        aggregator = HealthAggregator(version="1.0.0")
        check1 = MagicMock(spec=HealthCheck)
        check1.name = "db"
        check1.check.return_value = HealthCheckResult(
            name="db", status=HealthStatus.UNHEALTHY, response_time_ms=0.0, message="Connection refused"
        )
        check2 = MagicMock(spec=HealthCheck)
        check2.name = "cache"
        check2.check.return_value = HealthCheckResult(
            name="cache", status=HealthStatus.HEALTHY, response_time_ms=2.0
        )
        aggregator.add_check(check1)
        aggregator.add_check(check2)
        report = aggregator.aggregate()
        assert report.status == HealthStatus.UNHEALTHY

    def test_aggregate_no_checks_returns_healthy(self):
        aggregator = HealthAggregator(version="1.0.0")
        report = aggregator.aggregate()
        assert report.status == HealthStatus.HEALTHY
        assert len(report.checks) == 0

    def test_aggregate_includes_version(self):
        aggregator = HealthAggregator(version="2.5.0")
        report = aggregator.aggregate()
        assert report.version == "2.5.0"

    def test_aggregate_includes_uptime(self):
        aggregator = HealthAggregator(version="1.0.0")
        report = aggregator.aggregate()
        assert report.uptime_seconds >= 0.0


# ---------------------------------------------------------------------------
# Test HealthEndpoint
# ---------------------------------------------------------------------------

class TestHealthEndpoint:
    def test_health_endpoint_returns_full_report(self):
        aggregator = MagicMock(spec=HealthAggregator)
        report = MagicMock(spec=HealthReport)
        report.status = HealthStatus.HEALTHY
        report.version = "1.0.0"
        report.uptime_seconds = 100.0
        report.checks = [
            HealthCheckResult(name="db", status=HealthStatus.HEALTHY, response_time_ms=5.0)
        ]
        aggregator.aggregate.return_value = report
        readiness = MagicMock(spec=ReadinessProbe)
        liveness = MagicMock(spec=LivenessProbe)
        endpoint = HealthEndpoint(aggregator, readiness, liveness)
        result = endpoint.health()
        assert result["status"] == "healthy"
        assert result["version"] == "1.0.0"
        assert result["uptime_seconds"] == 100.0
        assert len(result["checks"]) == 1

    def test_readiness_endpoint_returns_ready(self):
        aggregator = MagicMock(spec=HealthAggregator)
        readiness = MagicMock(spec=ReadinessProbe)
        readiness.is_ready.return_value = True
        liveness = MagicMock(spec=LivenessProbe)
        endpoint = HealthEndpoint(aggregator, readiness, liveness)
        result = endpoint.readiness()
        assert result["ready"] is True

    def test_readiness_endpoint_returns_not_ready(self):
        aggregator = MagicMock(spec=HealthAggregator)
        readiness = MagicMock(spec=ReadinessProbe)
        readiness.is_ready.return_value = False
        liveness = MagicMock(spec=LivenessProbe)
        endpoint = HealthEndpoint(aggregator, readiness, liveness)
        result = endpoint.readiness()
        assert result["ready"] is False

    def test_liveness_endpoint_returns_alive(self):
        aggregator = MagicMock(spec=HealthAggregator)
        readiness = MagicMock(spec=ReadinessProbe)
        liveness = MagicMock(spec=LivenessProbe)
        liveness.is_alive.return_value = True
        liveness.get_uptime.return_value = 500.0
        endpoint = HealthEndpoint(aggregator, readiness, liveness)
        result = endpoint.liveness()
        assert result["alive"] is True
        assert result["uptime_seconds"] == 500.0


# ---------------------------------------------------------------------------
# Integration-style tests
# ---------------------------------------------------------------------------

class TestHealthSystemIntegration:
    def test_full_health_check_flow(self):
        """Test the complete health check flow from checks to endpoint."""
        # Create real checks
        class DBCheck(HealthCheck):
            def check(self):
                return HealthCheckResult(
                    name=self.name,
                    status=HealthStatus.HEALTHY,
                    response_time_ms=5.0,
                    message="Connection OK",
                )

        class CacheCheck(HealthCheck):
            def check(self):
                return HealthCheckResult(
                    name=self.name,
                    status=HealthStatus.DEGRADED,
                    response_time_ms=150.0,
                    message="High latency",
                )

        # Build the system
        aggregator = HealthAggregator(version="1.0.0")
        aggregator.add_check(DBCheck(name="database"))
        aggregator.add_check(CacheCheck(name="cache"))

        readiness = ReadinessProbe(aggregator)
        liveness = LivenessProbe()
        endpoint = HealthEndpoint(aggregator, readiness, liveness)

        # Test health endpoint
        health = endpoint.health()
        assert health["status"] == "degraded"
        assert len(health["checks"]) == 2

        # Test readiness endpoint
        ready = endpoint.readiness()
        assert ready["ready"] is False

        # Test liveness endpoint
        alive = endpoint.liveness()
        assert alive["alive"] is True
        assert alive["uptime_seconds"] >= 0.0

    def test_dependency_monitor_integration(self):
        """Test DependencyMonitor with real HealthCheck instances."""
        class FailingCheck(HealthCheck):
            def check(self):
                return HealthCheckResult(
                    name=self.name,
                    status=HealthStatus.UNHEALTHY,
                    response_time_ms=0.0,
                    message="Service unavailable",
                )

        monitor = DependencyMonitor()
        monitor.register("payment_service", FailingCheck(name="payment_service"))
        results = monitor.check_all()
        assert len(results) == 1
        assert results[0].status == HealthStatus.UNHEALTHY
        assert results[0].message == "Service unavailable"