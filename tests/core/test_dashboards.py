"""Tests for APEX-OS Dashboards, Alerting, and SLA Monitoring — TDD."""
from __future__ import annotations

import time
import pytest

from src.core.dashboards import (
    Alert,
    AlertManager,
    AlertRule,
    AlertSeverity,
    AlertState,
    Dashboard,
    DashboardPanel,
    MetricType,
    SLAMonitor,
    SLO,
    SLOStatus,
    TimeSeries,
)


# ---------------------------------------------------------------------------
# TimeSeries tests
# ---------------------------------------------------------------------------


class TestTimeSeries:
    def test_create_time_series(self):
        ts = TimeSeries("cpu_usage", max_points=100)
        assert ts.name == "cpu_usage"
        assert ts.max_points == 100
        assert len(ts) == 0

    def test_append_increases_length(self):
        ts = TimeSeries("latency", max_points=10)
        ts.append(1.0)
        ts.append(2.0)
        assert len(ts) == 2

    def test_append_respects_max_points(self):
        ts = TimeSeries("latency", max_points=3)
        for i in range(10):
            ts.append(float(i))
        assert len(ts) == 3
        # Should keep the most recent values
        values = ts.values()
        assert values == [7.0, 8.0, 9.0]

    def test_values_returns_all_points(self):
        ts = TimeSeries("temp", max_points=50)
        ts.append(10.0)
        ts.append(20.0)
        ts.append(30.0)
        assert ts.values() == [10.0, 20.0, 30.0]

    def test_latest_returns_most_recent(self):
        ts = TimeSeries("temp", max_points=50)
        ts.append(1.0)
        ts.append(2.0)
        ts.append(3.0)
        assert ts.latest() == 3.0

    def test_latest_empty_returns_none(self):
        ts = TimeSeries("temp", max_points=50)
        assert ts.latest() is None

    def test_mean_calculation(self):
        ts = TimeSeries("temp", max_points=50)
        ts.append(10.0)
        ts.append(20.0)
        ts.append(30.0)
        assert ts.mean() == pytest.approx(20.0)

    def test_mean_empty_returns_zero(self):
        ts = TimeSeries("temp", max_points=50)
        assert ts.mean() == 0.0

    def test_max_returns_highest(self):
        ts = TimeSeries("temp", max_points=50)
        ts.append(5.0)
        ts.append(99.0)
        ts.append(42.0)
        assert ts.max() == 99.0

    def test_min_returns_lowest(self):
        ts = TimeSeries("temp", max_points=50)
        ts.append(5.0)
        ts.append(99.0)
        ts.append(42.0)
        assert ts.min() == 5.0

    def test_clear_removes_all_points(self):
        ts = TimeSeries("temp", max_points=50)
        ts.append(1.0)
        ts.append(2.0)
        ts.clear()
        assert len(ts) == 0


# ---------------------------------------------------------------------------
# Dashboard tests
# ---------------------------------------------------------------------------


class TestDashboard:
    def test_create_dashboard(self):
        dash = Dashboard("system_overview")
        assert dash.name == "system_overview"
        assert len(dash.panels) == 0

    def test_add_panel(self):
        dash = Dashboard("test")
        panel = DashboardPanel("cpu", MetricType.GAUGE)
        dash.add_panel(panel)
        assert len(dash.panels) == 1
        assert dash.panels[0].name == "cpu"

    def test_add_multiple_panels(self):
        dash = Dashboard("test")
        dash.add_panel(DashboardPanel("cpu", MetricType.GAUGE))
        dash.add_panel(DashboardPanel("mem", MetricType.GAUGE))
        dash.add_panel(DashboardPanel("disk", MetricType.GAUGE))
        assert len(dash.panels) == 3

    def test_remove_panel(self):
        dash = Dashboard("test")
        dash.add_panel(DashboardPanel("cpu", MetricType.GAUGE))
        dash.remove_panel("cpu")
        assert len(dash.panels) == 0

    def test_remove_nonexistent_panel_raises(self):
        dash = Dashboard("test")
        with pytest.raises(KeyError):
            dash.remove_panel("nonexistent")

    def test_get_panel(self):
        dash = Dashboard("test")
        panel = DashboardPanel("cpu", MetricType.GAUGE)
        dash.add_panel(panel)
        assert dash.get_panel("cpu") is panel

    def test_get_nonexistent_panel_raises(self):
        dash = Dashboard("test")
        with pytest.raises(KeyError):
            dash.get_panel("nonexistent")

    def test_update_panel_value(self):
        dash = Dashboard("test")
        dash.add_panel(DashboardPanel("cpu", MetricType.GAUGE))
        dash.update_panel("cpu", 75.5)
        assert dash.get_panel("cpu").current_value == 75.5

    def test_update_nonexistent_panel_raises(self):
        dash = Dashboard("test")
        with pytest.raises(KeyError):
            dash.update_panel("nonexistent", 42.0)

    def test_panel_tracks_history(self):
        dash = Dashboard("test")
        dash.add_panel(DashboardPanel("cpu", MetricType.GAUGE))
        for i in range(5):
            dash.update_panel("cpu", float(i))
        panel = dash.get_panel("cpu")
        assert len(panel.history) == 5
        assert panel.history.values() == [0.0, 1.0, 2.0, 3.0, 4.0]

    def test_to_dict_structure(self):
        dash = Dashboard("test")
        dash.add_panel(DashboardPanel("cpu", MetricType.GAUGE))
        dash.update_panel("cpu", 50.0)
        d = dash.to_dict()
        assert d["name"] == "test"
        assert len(d["panels"]) == 1
        assert d["panels"][0]["name"] == "cpu"
        assert d["panels"][0]["value"] == 50.0

    def test_panel_metric_type(self):
        panel = DashboardPanel("requests", MetricType.COUNTER)
        assert panel.metric_type == MetricType.COUNTER

    def test_panel_unit(self):
        panel = DashboardPanel("latency", MetricType.GAUGE, unit="ms")
        assert panel.unit == "ms"


# ---------------------------------------------------------------------------
# AlertRule tests
# ---------------------------------------------------------------------------


class TestAlertRule:
    def test_create_alert_rule(self):
        rule = AlertRule(
            name="high_cpu",
            metric_name="cpu_usage",
            threshold=90.0,
            comparison="gt",
            severity=AlertSeverity.WARNING,
        )
        assert rule.name == "high_cpu"
        assert rule.metric_name == "cpu_usage"
        assert rule.threshold == 90.0
        assert rule.comparison == "gt"
        assert rule.severity == AlertSeverity.WARNING
        assert rule.enabled is True

    def test_evaluate_gt_triggered(self):
        rule = AlertRule("r", "cpu", 90.0, "gt", AlertSeverity.WARNING)
        assert rule.evaluate(95.0) is True

    def test_evaluate_gt_not_triggered(self):
        rule = AlertRule("r", "cpu", 90.0, "gt", AlertSeverity.WARNING)
        assert rule.evaluate(85.0) is False

    def test_evaluate_lt_triggered(self):
        rule = AlertRule("r", "disk", 10.0, "lt", AlertSeverity.CRITICAL)
        assert rule.evaluate(5.0) is True

    def test_evaluate_lt_not_triggered(self):
        rule = AlertRule("r", "disk", 10.0, "lt", AlertSeverity.CRITICAL)
        assert rule.evaluate(15.0) is False

    def test_evaluate_eq_triggered(self):
        rule = AlertRule("r", "status", 0.0, "eq", AlertSeverity.CRITICAL)
        assert rule.evaluate(0.0) is True

    def test_evaluate_eq_not_triggered(self):
        rule = AlertRule("r", "status", 0.0, "eq", AlertSeverity.CRITICAL)
        assert rule.evaluate(1.0) is False

    def test_evaluate_gte_triggered(self):
        rule = AlertRule("r", "cpu", 90.0, "gte", AlertSeverity.WARNING)
        assert rule.evaluate(90.0) is True

    def test_evaluate_lte_triggered(self):
        rule = AlertRule("r", "disk", 10.0, "lte", AlertSeverity.CRITICAL)
        assert rule.evaluate(10.0) is True

    def test_evaluate_invalid_comparison_raises(self):
        rule = AlertRule("r", "x", 1.0, "invalid", AlertSeverity.WARNING)
        with pytest.raises(ValueError):
            rule.evaluate(1.0)

    def test_rule_disable(self):
        rule = AlertRule("r", "cpu", 90.0, "gt", AlertSeverity.WARNING)
        rule.disable()
        assert rule.enabled is False

    def test_rule_enable(self):
        rule = AlertRule("r", "cpu", 90.0, "gt", AlertSeverity.WARNING)
        rule.disable()
        rule.enable()
        assert rule.enabled is True

    def test_disabled_rule_does_not_trigger(self):
        rule = AlertRule("r", "cpu", 90.0, "gt", AlertSeverity.WARNING)
        rule.disable()
        assert rule.evaluate(95.0) is False


# ---------------------------------------------------------------------------
# AlertManager tests
# ---------------------------------------------------------------------------


class TestAlertManager:
    def test_create_manager(self):
        mgr = AlertManager()
        assert len(mgr.rules) == 0

    def test_add_rule(self):
        mgr = AlertManager()
        rule = AlertRule("r1", "cpu", 90.0, "gt", AlertSeverity.WARNING)
        mgr.add_rule(rule)
        assert len(mgr.rules) == 1

    def test_remove_rule(self):
        mgr = AlertManager()
        rule = AlertRule("r1", "cpu", 90.0, "gt", AlertSeverity.WARNING)
        mgr.add_rule(rule)
        mgr.remove_rule("r1")
        assert len(mgr.rules) == 0

    def test_remove_nonexistent_rule_raises(self):
        mgr = AlertManager()
        with pytest.raises(KeyError):
            mgr.remove_rule("nonexistent")

    def test_evaluate_all_rules(self):
        mgr = AlertManager()
        mgr.add_rule(AlertRule("r1", "cpu", 90.0, "gt", AlertSeverity.WARNING))
        mgr.add_rule(AlertRule("r2", "disk", 10.0, "lt", AlertSeverity.CRITICAL))
        alerts = mgr.evaluate_all({"cpu": 95.0, "disk": 5.0})
        assert len(alerts) == 2
        assert all(a.state == AlertState.FIRING for a in alerts)

    def test_evaluate_no_trigger(self):
        mgr = AlertManager()
        mgr.add_rule(AlertRule("r1", "cpu", 90.0, "gt", AlertSeverity.WARNING))
        alerts = mgr.evaluate_all({"cpu": 50.0})
        assert len(alerts) == 0

    def test_evaluate_partial_trigger(self):
        mgr = AlertManager()
        mgr.add_rule(AlertRule("r1", "cpu", 90.0, "gt", AlertSeverity.WARNING))
        mgr.add_rule(AlertRule("r2", "disk", 10.0, "lt", AlertSeverity.CRITICAL))
        alerts = mgr.evaluate_all({"cpu": 95.0, "disk": 50.0})
        assert len(alerts) == 1
        assert alerts[0].rule_name == "r1"

    def test_alert_has_timestamp(self):
        mgr = AlertManager()
        mgr.add_rule(AlertRule("r1", "cpu", 90.0, "gt", AlertSeverity.WARNING))
        alerts = mgr.evaluate_all({"cpu": 95.0})
        assert alerts[0].timestamp is not None

    def test_alert_has_severity(self):
        mgr = AlertManager()
        mgr.add_rule(AlertRule("r1", "cpu", 90.0, "gt", AlertSeverity.CRITICAL))
        alerts = mgr.evaluate_all({"cpu": 95.0})
        assert alerts[0].severity == AlertSeverity.CRITICAL

    def test_alert_has_value(self):
        mgr = AlertManager()
        mgr.add_rule(AlertRule("r1", "cpu", 90.0, "gt", AlertSeverity.WARNING))
        alerts = mgr.evaluate_all({"cpu": 95.0})
        assert alerts[0].value == 95.0

    def test_disabled_rule_not_evaluated(self):
        mgr = AlertManager()
        rule = AlertRule("r1", "cpu", 90.0, "gt", AlertSeverity.WARNING)
        rule.disable()
        mgr.add_rule(rule)
        alerts = mgr.evaluate_all({"cpu": 95.0})
        assert len(alerts) == 0

    def test_firing_alerts_tracked(self):
        mgr = AlertManager()
        mgr.add_rule(AlertRule("r1", "cpu", 90.0, "gt", AlertSeverity.WARNING))
        mgr.evaluate_all({"cpu": 95.0})
        assert len(mgr.firing_alerts) == 1

    def test_resolved_alert_removed_from_firing(self):
        mgr = AlertManager()
        mgr.add_rule(AlertRule("r1", "cpu", 90.0, "gt", AlertSeverity.WARNING))
        mgr.evaluate_all({"cpu": 95.0})
        assert len(mgr.firing_alerts) == 1
        mgr.evaluate_all({"cpu": 50.0})
        assert len(mgr.firing_alerts) == 0

    def test_get_firing_alerts(self):
        mgr = AlertManager()
        mgr.add_rule(AlertRule("r1", "cpu", 90.0, "gt", AlertSeverity.WARNING))
        mgr.add_rule(AlertRule("r2", "disk", 10.0, "lt", AlertSeverity.CRITICAL))
        mgr.evaluate_all({"cpu": 95.0, "disk": 5.0})
        firing = mgr.get_firing_alerts()
        assert len(firing) == 2

    def test_clear_firing_alerts(self):
        mgr = AlertManager()
        mgr.add_rule(AlertRule("r1", "cpu", 90.0, "gt", AlertSeverity.WARNING))
        mgr.evaluate_all({"cpu": 95.0})
        mgr.clear_firing_alerts()
        assert len(mgr.firing_alerts) == 0


# ---------------------------------------------------------------------------
# SLO / SLAMonitor tests
# ---------------------------------------------------------------------------


class TestSLAMonitor:
    def test_create_slo(self):
        slo = SLO("availability", target=99.9, window_seconds=86400)
        assert slo.name == "availability"
        assert slo.target == 99.9
        assert slo.window_seconds == 86400

    def test_create_monitor(self):
        mon = SLAMonitor()
        assert len(mon.slos) == 0

    def test_add_slo(self):
        mon = SLAMonitor()
        slo = SLO("availability", target=99.9)
        mon.add_slo(slo)
        assert len(mon.slos) == 1

    def test_remove_slo(self):
        mon = SLAMonitor()
        mon.add_slo(SLO("availability", target=99.9))
        mon.remove_slo("availability")
        assert len(mon.slos) == 0

    def test_remove_nonexistent_slo_raises(self):
        mon = SLAMonitor()
        with pytest.raises(KeyError):
            mon.remove_slo("nonexistent")

    def test_record_success(self):
        mon = SLAMonitor()
        mon.add_slo(SLO("availability", target=99.9))
        mon.record("availability", True)
        report = mon.get_slo_report("availability")
        assert report.good_count == 1
        assert report.bad_count == 0

    def test_record_failure(self):
        mon = SLAMonitor()
        mon.add_slo(SLO("availability", target=99.9))
        mon.record("availability", False)
        report = mon.get_slo_report("availability")
        assert report.good_count == 0
        assert report.bad_count == 1

    def test_availability_calculation(self):
        mon = SLAMonitor()
        mon.add_slo(SLO("availability", target=99.9))
        for _ in range(99):
            mon.record("availability", True)
        mon.record("availability", False)
        report = mon.get_slo_report("availability")
        assert report.availability_pct == pytest.approx(99.0)

    def test_slo_status_met(self):
        mon = SLAMonitor()
        mon.add_slo(SLO("availability", target=99.0))
        for _ in range(100):
            mon.record("availability", True)
        report = mon.get_slo_report("availability")
        assert report.status == SLOStatus.MET

    def test_slo_status_breached(self):
        mon = SLAMonitor()
        mon.add_slo(SLO("availability", target=99.9))
        for _ in range(99):
            mon.record("availability", True)
        mon.record("availability", False)
        report = mon.get_slo_report("availability")
        assert report.status == SLOStatus.BREACHED

    def test_slo_status_unknown_no_data(self):
        mon = SLAMonitor()
        mon.add_slo(SLO("availability", target=99.9))
        report = mon.get_slo_report("availability")
        assert report.status == SLOStatus.UNKNOWN

    def test_error_budget_calculation(self):
        mon = SLAMonitor()
        mon.add_slo(SLO("availability", target=99.9))
        for _ in range(99):
            mon.record("availability", True)
        mon.record("availability", False)
        report = mon.get_slo_report("availability")
        # 1 bad out of 100 = 1% error rate, budget is 0.1%
        assert report.error_budget_remaining_pct == pytest.approx(-0.9, abs=0.1)

    def test_latency_slo(self):
        mon = SLAMonitor()
        mon.add_slo(SLO("latency_p99", target=100.0, window_seconds=3600))
        mon.record("latency_p99", True, latency_ms=50.0)
        mon.record("latency_p99", True, latency_ms=80.0)
        mon.record("latency_p99", False, latency_ms=150.0)
        report = mon.get_slo_report("latency_p99")
        assert report.good_count == 2
        assert report.bad_count == 1

    def test_get_all_reports(self):
        mon = SLAMonitor()
        mon.add_slo(SLO("availability", target=99.9))
        mon.add_slo(SLO("latency", target=100.0))
        mon.record("availability", True)
        mon.record("latency", True)
        reports = mon.get_all_reports()
        assert len(reports) == 2

    def test_clear_slo_data(self):
        mon = SLAMonitor()
        mon.add_slo(SLO("availability", target=99.9))
        mon.record("availability", True)
        mon.record("availability", False)
        mon.clear("availability")
        report = mon.get_slo_report("availability")
        assert report.good_count == 0
        assert report.bad_count == 0

    def test_slo_report_has_name(self):
        mon = SLAMonitor()
        mon.add_slo(SLO("availability", target=99.9))
        report = mon.get_slo_report("availability")
        assert report.name == "availability"

    def test_slo_report_has_target(self):
        mon = SLAMonitor()
        mon.add_slo(SLO("availability", target=99.9))
        report = mon.get_slo_report("availability")
        assert report.target == 99.9


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------


class TestIntegration:
    def test_dashboard_with_alerting(self):
        """Dashboard panels feed into alert rules."""
        dash = Dashboard("prod")
        dash.add_panel(DashboardPanel("cpu", MetricType.GAUGE))
        dash.update_panel("cpu", 95.0)

        mgr = AlertManager()
        mgr.add_rule(AlertRule("high_cpu", "cpu", 90.0, "gt", AlertSeverity.WARNING))

        panel_values = {p.name: p.current_value for p in dash.panels}
        alerts = mgr.evaluate_all(panel_values)
        assert len(alerts) == 1
        assert alerts[0].rule_name == "high_cpu"

    def test_sla_with_dashboard(self):
        """SLO monitoring alongside dashboard."""
        dash = Dashboard("prod")
        dash.add_panel(DashboardPanel("requests", MetricType.COUNTER))
        dash.update_panel("requests", 1000)

        mon = SLAMonitor()
        mon.add_slo(SLO("availability", target=99.9))
        for _ in range(99):
            mon.record("availability", True)
        mon.record("availability", False)

        report = mon.get_slo_report("availability")
        assert report.status == SLOStatus.BREACHED
        assert dash.get_panel("requests").current_value == 1000

    def test_full_monitoring_stack(self):
        """Dashboard + Alerting + SLA working together."""
        dash = Dashboard("prod")
        dash.add_panel(DashboardPanel("cpu", MetricType.GAUGE))
        dash.add_panel(DashboardPanel("mem", MetricType.GAUGE))
        dash.update_panel("cpu", 95.0)
        dash.update_panel("mem", 60.0)

        mgr = AlertManager()
        mgr.add_rule(AlertRule("high_cpu", "cpu", 90.0, "gt", AlertSeverity.WARNING))
        mgr.add_rule(AlertRule("high_mem", "mem", 80.0, "gt", AlertSeverity.WARNING))

        mon = SLAMonitor()
        mon.add_slo(SLO("availability", target=99.9))
        for _ in range(100):
            mon.record("availability", True)

        panel_values = {p.name: p.current_value for p in dash.panels}
        alerts = mgr.evaluate_all(panel_values)
        assert len(alerts) == 1  # only cpu fires

        report = mon.get_slo_report("availability")
        assert report.status == SLOStatus.MET
