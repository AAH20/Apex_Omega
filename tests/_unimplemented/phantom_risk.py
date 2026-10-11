"""
Integration tests for the full Risk Pipeline.

Tests cover end-to-end workflows combining multiple risk modules:
    - RiskMonitor + VaR + CVaR + StressTest + Greeks + Drawdown + KillSwitch
    - Risk Appetite → Risk Budget → Risk Monitor pipeline
    - Stress Testing → Risk Report pipeline
    - Liquidity Risk → Risk Monitor pipeline
    - Risk Attribution → Risk Budget pipeline
    - Drawdown → Kill Switch pipeline
    - Risk Overlay → Risk Monitor pipeline
    - VaR Backtest → Risk Monitor pipeline
    - Copula Aggregation → Risk Report pipeline
    - Multi-factor Risk Pipeline (market + credit + liquidity)
    - Risk Budget → Stress Test → Kill Switch pipeline
    - Risk Appetite → Limit Breach → Alert pipeline
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import List

import numpy as np

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from risk.risk_monitor import (
    AlertSeverity,
    Position,
    RiskAlert,
    RiskMonitor,
    RiskThresholds,
    StressScenario,
    StressScenarioType,
    VaRMethod,
)
from risk.risk_appetite import (
    LimitBreach,
    LimitBreachSeverity,
    LimitStatus,
    LimitType,
    RiskAppetiteFramework,
    RiskAppetiteLevel,
    RiskAppetiteStatement,
    RiskLimit,
    RiskToleranceCategory,
)
from risk.risk_budgeting import (
    BudgetBreach,
    BudgetLevel,
    BudgetStatus,
    RiskBudget,
    RiskBudgetManager,
)
from risk.stress_testing import (
    ScenarioSeverity,
    ScenarioType,
    StressScenario as StressTestScenario,
    StressTestSuite,
    create_default_stress_suite,
)
from risk.liquidity_risk import (
    CashFlow,
    CashFlowType,
    HQLAAsset,
    HQLAType,
    InflowCategory,
    LCRCalculator,
    LiquidityRiskEngine,
    NSFRCalculator,
    OutflowCategory,
)
from risk.risk_attribution import (
    EulerRiskAttribution,
    RiskMeasure,
)
from risk.risk_aggregation import (
    CopulaRiskAggregator,
    CopulaType,
)
from risk.drawdown_manager import (
    DrawdownAction,
    DrawdownLimits,
    DrawdownManager,
    DrawdownState,
)
from risk.kill_switch import (
    AuditAction,
    KillSwitchController,
    KillSwitchState,
    RiskLimits,
    RiskSnapshot,
    VenueOrder,
)
from risk.expected_shortfall import (
    ESMethod,
    ExpectedShortfallCalculator,
)
from risk.var_backtest import (
    TestResult,
    VaRBacktester,
)
from risk.risk_overlay import (
    HedgeSignal,
    PortfolioGreeks,
    RiskOverlayConfig,
    RiskOverlayEngine,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class MockAlertHandler:
    """Mock alert handler for testing."""

    def __init__(self) -> None:
        self.alerts: List[RiskAlert] = []

    def on_alert(self, alert: RiskAlert) -> None:
        self.alerts.append(alert)


class MockVenueConnector:
    """Mock venue connector for kill switch testing."""

    def __init__(self, venue: str, pending_orders: int = 5) -> None:
        self.venue = venue
        self.pending_orders = pending_orders
        self.cancelled_count = 0

    def cancel_all_orders(self, venue: str) -> int:
        count = self.pending_orders
        self.cancelled_count += count
        self.pending_orders = 0
        return count

    def get_pending_orders(self, venue: str) -> List[VenueOrder]:
        return [
            VenueOrder(
                order_id=f"{self.venue}-order-{i}",
                venue=self.venue,
                instrument="BTC-PERP",
                quantity=1.0,
                price=50000.0,
            )
            for i in range(self.pending_orders)
        ]


def _generate_returns(n: int = 200, seed: int = 42, vol: float = 0.02) -> np.ndarray:
    """Generate synthetic returns for testing."""
    rng = np.random.default_rng(seed)
    return rng.standard_normal(n) * vol


def _generate_correlated_returns(
    n: int = 200, seed: int = 42
) -> dict[str, np.ndarray]:
    """Generate correlated factor returns for testing."""
    rng = np.random.default_rng(seed)
    corr = np.array([[1.0, 0.6], [0.6, 1.0]])
    L = np.linalg.cholesky(corr)
    z = rng.standard_normal((n, 2))
    correlated = z @ L.T
    return {
        "equity": correlated[:, 0] * 0.02,
        "rates": correlated[:, 1] * 0.01,
    }


def _make_positions() -> List[Position]:
    """Create a test portfolio."""
    return [
        Position(instrument="BTC-PERP", quantity=10.0, price=50000.0),
        Position(instrument="ETH-PERP", quantity=50.0, price=3000.0),
        Position(instrument="SOL-PERP", quantity=200.0, price=100.0),
    ]


def _make_option_positions() -> List[Position]:
    """Create a test portfolio with options."""
    return [
        Position(
            instrument="BTC-240125-50000-C",
            quantity=5.0,
            price=2000.0,
            is_option=True,
            delta=0.6,
            gamma=0.001,
            theta=-50.0,
            vega=100.0,
            rho=0.1,
        ),
        Position(
            instrument="BTC-240125-55000-P",
            quantity=-3.0,
            price=1500.0,
            is_option=True,
            delta=-0.4,
            gamma=0.0008,
            theta=-40.0,
            vega=80.0,
            rho=-0.05,
        ),
    ]


# ---------------------------------------------------------------------------
# Test 1: Full Risk Pipeline — RiskMonitor + VaR + CVaR + Stress + Greeks + Drawdown
# ---------------------------------------------------------------------------


class TestFullRiskPipeline(unittest.TestCase):
    """Test the complete risk monitoring pipeline end-to-end."""

    def test_full_risk_check_pipeline(self) -> None:
        """Test RiskMonitor orchestrating VaR, CVaR, stress, greeks, drawdown."""
        alert_handler = MockAlertHandler()
        monitor = RiskMonitor(
            thresholds=RiskThresholds(
                var_limit=500_000.0,
                cvar_limit=750_000.0,
                stress_loss_limit=1_000_000.0,
                delta_limit=10_000.0,
                gamma_limit=1_000.0,
                theta_limit=50_000.0,
                vega_limit=50_000.0,
                max_drawdown_pct=0.15,
                max_concentration_pct=0.60,
            ),
            alert_handlers=[alert_handler],
        )

        # Set up positions
        positions = _make_positions()
        monitor.update_positions(positions)

        # Update returns
        returns = _generate_returns(n=200, seed=42)
        monitor.update_returns(returns)

        # Add stress scenario
        monitor.add_stress_scenario(
            StressScenario(
                name="test_crash",
                scenario_type=StressScenarioType.HISTORICAL,
                shocks={"BTC-PERP": -0.15, "ETH-PERP": -0.20, "SOL-PERP": -0.25},
            )
        )

        # Run full risk check
        alerts = monitor.check_risk()

        # Verify VaR was calculated
        var_result = monitor.calculate_var()
        self.assertIsNotNone(var_result)
        self.assertGreater(var_result.var, 0.0)
        self.assertEqual(var_result.confidence, 0.95)

        # Verify CVaR was calculated
        cvar_result = monitor.calculate_cvar()
        self.assertIsNotNone(cvar_result)
        self.assertGreater(cvar_result.cvar, 0.0)
        self.assertGreaterEqual(cvar_result.cvar, var_result.var)

        # Verify stress test ran
        stress_results = monitor.run_stress_test()
        self.assertEqual(len(stress_results), 1)
        self.assertEqual(stress_results[0].scenario_name, "test_crash")
        self.assertLess(stress_results[0].portfolio_pnl, 0.0)

        # Verify Greeks were aggregated
        greeks = monitor.get_greeks()
        self.assertIsNotNone(greeks)

        # Verify report generation
        report = monitor.generate_report()
        self.assertIsNotNone(report)
        self.assertEqual(report.positions_count, 3)
        self.assertGreater(report.gross_exposure, 0.0)
        self.assertIsNotNone(report.var_result)
        self.assertIsNotNone(report.cvar_result)

        # Verify alerts were dispatched
        self.assertIsInstance(alert_handler.alerts, list)

    def test_risk_monitor_var_breach_alert(self) -> None:
        """Test that VaR breach generates CRITICAL alert."""
        alert_handler = MockAlertHandler()
        monitor = RiskMonitor(
            thresholds=RiskThresholds(var_limit=1.0),  # Very tight limit
            alert_handlers=[alert_handler],
        )

        positions = _make_positions()
        monitor.update_positions(positions)
        returns = _generate_returns(n=200, seed=42)
        monitor.update_returns(returns)

        alerts = monitor.check_risk()

        # Should have at least one VaR breach alert
        var_alerts = [a for a in alerts if a.alert_type == "VAR_BREACH"]
        self.assertGreater(len(var_alerts), 0)
        self.assertEqual(var_alerts[0].severity, AlertSeverity.CRITICAL)

    def test_risk_monitor_drawdown_breach(self) -> None:
        """Test drawdown detection in full pipeline."""
        alert_handler = MockAlertHandler()
        monitor = RiskMonitor(
            thresholds=RiskThresholds(
                var_limit=500_000.0,
                cvar_limit=750_000.0,
                stress_loss_limit=1_000_000.0,
                max_drawdown_pct=0.01,  # Very tight
                max_concentration_pct=0.60,
            ),
            alert_handlers=[alert_handler],
        )

        # Set high portfolio value first
        positions = [
            Position(instrument="BTC-PERP", quantity=100.0, price=50000.0),
        ]
        monitor.update_positions(positions)
        returns = _generate_returns(n=200, seed=42)
        monitor.update_returns(returns)

        # Now drop portfolio value significantly
        positions = [
            Position(instrument="BTC-PERP", quantity=10.0, price=50000.0),
        ]
        monitor.update_positions(positions)

        alerts = monitor.check_risk()
        drawdown_alerts = [a for a in alerts if a.alert_type == "DRAWDOWN_BREACH"]
        self.assertGreater(len(drawdown_alerts), 0)

    def test_risk_monitor_concentration_breach(self) -> None:
        """Test concentration limit detection."""
        alert_handler = MockAlertHandler()
        monitor = RiskMonitor(
            thresholds=RiskThresholds(
                var_limit=500_000.0,
                cvar_limit=750_000.0,
                stress_loss_limit=1_000_000.0,
                max_drawdown_pct=0.15,
                max_concentration_pct=0.30,  # Tight concentration limit
            ),
            alert_handlers=[alert_handler],
        )

        # Single position = 100% concentration
        positions = [
            Position(instrument="BTC-PERP", quantity=10.0, price=50000.0),
        ]
        monitor.update_positions(positions)
        returns = _generate_returns(n=200, seed=42)
        monitor.update_returns(returns)

        alerts = monitor.check_risk()
        conc_alerts = [a for a in alerts if a.alert_type == "CONCENTRATION_BREACH"]
        self.assertGreater(len(conc_alerts), 0)


# ---------------------------------------------------------------------------
# Test 2: Risk Appetite → Risk Budget → Risk Monitor Pipeline
# ---------------------------------------------------------------------------


class TestAppetiteBudgetMonitorPipeline(unittest.TestCase):
    """Test appetite statement flowing into budgets and monitoring."""

    def test_appetite_to_budget_to_monitor(self) -> None:
        """Test full chain: appetite → budget → utilization → alert."""
        # 1. Set risk appetite
        framework = RiskAppetiteFramework()
        statement = RiskAppetiteStatement(
            statement_id="RAS-001",
            appetite_level=RiskAppetiteLevel.MODERATE,
            max_portfolio_var=1_000_000.0,
            max_leverage_ratio=10.0,
            max_concentration_pct=25.0,
            max_daily_loss_pct=2.0,
            min_liquidity_ratio=1.5,
        )
        framework.set_appetite_statement(statement)

        # 2. Add limits from appetite
        framework.add_limit(
            RiskLimit(
                limit_id="LIM-VAR",
                category=RiskToleranceCategory.MARKET,
                limit_type=LimitType.HARD,
                threshold_value=1_000_000.0,
            )
        )
        framework.add_limit(
            RiskLimit(
                limit_id="LIM-CONC",
                category=RiskToleranceCategory.CONCENTRATION,
                limit_type=LimitType.HARD,
                threshold_value=25.0,
            )
        )

        # 3. Create risk budget aligned with appetite
        budget_manager = RiskBudgetManager()
        budget_manager.add_budget(
            RiskBudget(
                budget_id="firm-var",
                level=BudgetLevel.FIRM,
                allocated_var=1_000_000.0,
                allocated_exposure=10_000_000.0,
            )
        )

        # 4. Update utilization
        util = budget_manager.update_utilization(
            "firm-var", current_var=500_000.0, current_exposure=5_000_000.0
        )
        self.assertEqual(util.var_utilization_pct, 50.0)
        self.assertEqual(util.status, BudgetStatus.ACTIVE)

        # 5. Generate report
        report = budget_manager.generate_report()
        self.assertEqual(report.total_allocated_var, 1_000_000.0)
        self.assertEqual(report.total_current_var, 500_000.0)
        self.assertEqual(report.total_var_utilization_pct, 50.0)

        # 6. Verify appetite framework report
        appetite_report = framework.generate_report()
        self.assertEqual(appetite_report.total_limits, 2)
        self.assertEqual(appetite_report.breached_limits, 0)

    def test_budget_breach_triggers_alert(self) -> None:
        """Test budget breach detection and alerting."""
        breaches: List[BudgetBreach] = []

        class BreachHandler:
            def on_budget_breach(self, breach: BudgetBreach) -> None:
                breaches.append(breach)

        manager = RiskBudgetManager(alert_handlers=[BreachHandler()])
        manager.add_budget(
            RiskBudget(
                budget_id="test-budget",
                level=BudgetLevel.STRATEGY,
                allocated_var=100_000.0,
                breach_threshold_pct=100.0,
            )
        )

        # Exceed budget (110% utilization = BREACHED, not EXHAUSTED)
        util = manager.update_utilization("test-budget", current_var=110_000.0)
        self.assertEqual(util.status, BudgetStatus.BREACHED)
        self.assertEqual(len(breaches), 1)
        self.assertEqual(breaches[0].budget_id, "test-budget")


# ---------------------------------------------------------------------------
# Test 3: Stress Testing → Risk Report Pipeline
# ---------------------------------------------------------------------------


class TestStressReportPipeline(unittest.TestCase):
    """Test stress testing feeding into risk reporting."""

    def test_stress_suite_to_report(self) -> None:
        """Test running stress suite and generating summary."""
        suite = create_default_stress_suite()
        positions = {
            "equities": 1_000_000.0,
            "credit": 500_000.0,
            "rates": 300_000.0,
            "fx": 200_000.0,
            "commodities": 400_000.0,
            "volatility": 100_000.0,
            "liquidity": 150_000.0,
        }

        results = suite.run_all(positions)
        self.assertEqual(len(results), 4)  # 4 default scenarios

        summary = suite.summarize(results)
        self.assertEqual(summary.total_scenarios, 4)
        self.assertLess(summary.worst_pnl, 0.0)
        self.assertIn(summary.worst_scenario, [r.scenario_name for r in results])

    def test_stress_scenario_severity_filtering(self) -> None:
        """Test filtering stress scenarios by severity."""
        suite = create_default_stress_suite()
        positions = {"equities": 1_000_000.0, "credit": 500_000.0}

        severe_results = suite.run_by_severity(positions, ScenarioSeverity.SEVERE)
        self.assertGreaterEqual(len(severe_results), 2)

        extreme_results = suite.run_by_severity(positions, ScenarioSeverity.EXTREME)
        self.assertEqual(len(extreme_results), 2)

    def test_reverse_stress_test(self) -> None:
        """Test reverse stress test finding shock for target loss."""
        suite = StressTestSuite()
        positions = {"BTC-PERP": 1_000_000.0, "ETH-PERP": 500_000.0}

        result = suite.reverse_stress_test(positions, target_loss=100_000.0)
        self.assertIn("shock", result)
        self.assertIn("pnl", result)
        self.assertLess(result["shock"], 0.0)


# ---------------------------------------------------------------------------
# Test 4: Liquidity Risk → Risk Monitor Pipeline
# ---------------------------------------------------------------------------


class TestLiquidityRiskPipeline(unittest.TestCase):
    """Test liquidity risk integration with broader risk framework."""

    def test_liquidity_engine_lcr_nsfr(self) -> None:
        """Test LCR and NSFR calculation in liquidity engine."""
        engine = LiquidityRiskEngine()

        # Add HQLA assets
        engine.lcr_calculator.add_hqla_asset(
            HQLAAsset(
                asset_id="cash-1",
                hqla_type=HQLAType.LEVEL_1,
                market_value=1_000_000.0,
                haircut=0.0,
            )
        )
        engine.lcr_calculator.add_hqla_asset(
            HQLAAsset(
                asset_id="gov-bond-1",
                hqla_type=HQLAType.LEVEL_2A,
                market_value=500_000.0,
                haircut=0.15,
            )
        )

        # Add cash flows
        engine.lcr_calculator.add_cash_flow(
            CashFlow(
                flow_id="outflow-1",
                flow_type=CashFlowType.OUTFLOW,
                category=OutflowCategory.RETAIL_DEPOSITS,
                amount=200_000.0,
            )
        )
        engine.lcr_calculator.add_cash_flow(
            CashFlow(
                flow_id="inflow-1",
                flow_type=CashFlowType.INFLOW,
                category=InflowCategory.LOANS,
                amount=100_000.0,
            )
        )

        # Check liquidity
        alerts = engine.check_liquidity()
        self.assertIsInstance(alerts, list)

        # Generate report
        report = engine.generate_report()
        self.assertIsNotNone(report.lcr_result)
        self.assertIsNotNone(report.nsfr_result)
        self.assertGreater(report.total_assets, 0.0)

    def test_liquidity_critical_alert(self) -> None:
        """Test critical liquidity alert when LCR is very low."""
        engine = LiquidityRiskEngine(
            lcr_warning_threshold=100.0,
            lcr_critical_threshold=80.0,
        )

        # Minimal HQLA, large outflows
        engine.lcr_calculator.add_hqla_asset(
            HQLAAsset(
                asset_id="cash-1",
                hqla_type=HQLAType.LEVEL_1,
                market_value=10_000.0,
            )
        )
        engine.lcr_calculator.add_cash_flow(
            CashFlow(
                flow_id="outflow-1",
                flow_type=CashFlowType.OUTFLOW,
                category=OutflowCategory.DERIVATIVES,
                amount=1_000_000.0,
            )
        )

        alerts = engine.check_liquidity()
        critical_alerts = [a for a in alerts if a.level.name == "CRITICAL"]
        self.assertGreater(len(critical_alerts), 0)


# ---------------------------------------------------------------------------
# Test 5: Risk Attribution → Risk Budget Pipeline
# ---------------------------------------------------------------------------


class TestAttributionBudgetPipeline(unittest.TestCase):
    """Test risk attribution feeding into budget management."""

    def test_attribution_to_budget_allocation(self) -> None:
        """Test using attribution results to inform budget allocation."""
        # Generate correlated returns
        returns = _generate_correlated_returns(n=200, seed=42)

        # Perform attribution
        attributor = EulerRiskAttribution(risk_measure=RiskMeasure.VOLATILITY)
        attributor.set_returns(returns)
        result = attributor.attribute({"equity": 0.6, "rates": 0.4})

        self.assertIsNotNone(result)
        self.assertGreater(result.total_risk, 0.0)
        self.assertIn("equity", result.components)
        self.assertIn("rates", result.components)

        # Verify additivity
        self.assertAlmostEqual(
            result.sum_of_components, result.total_risk, places=5
        )

        # Use attribution to inform budget
        budget_manager = RiskBudgetManager()
        budget_manager.add_budget(
            RiskBudget(
                budget_id="equity-budget",
                level=BudgetLevel.STRATEGY,
                allocated_var=result.components["equity"].component_contribution * 1000,
            )
        )
        budget_manager.add_budget(
            RiskBudget(
                budget_id="rates-budget",
                level=BudgetLevel.STRATEGY,
                allocated_var=result.components["rates"].component_contribution * 1000,
            )
        )

        self.assertEqual(budget_manager.budget_count, 2)

    def test_var_attribution(self) -> None:
        """Test VaR-based risk attribution."""
        returns = _generate_correlated_returns(n=200, seed=42)
        attributor = EulerRiskAttribution(
            risk_measure=RiskMeasure.VAR, confidence=0.95
        )
        attributor.set_returns(returns)
        result = attributor.attribute({"equity": 0.5, "rates": 0.5})

        self.assertEqual(result.risk_measure, RiskMeasure.VAR)
        self.assertEqual(result.confidence, 0.95)
        self.assertGreater(result.total_risk, 0.0)


# ---------------------------------------------------------------------------
# Test 6: Drawdown → Kill Switch Pipeline
# ---------------------------------------------------------------------------


class TestDrawdownKillSwitchPipeline(unittest.TestCase):
    """Test drawdown triggering kill switch."""

    def test_drawdown_triggers_kill_switch(self) -> None:
        """Test that severe drawdown can trigger kill switch."""
        # Set up drawdown manager with tight limits
        dd_limits = DrawdownLimits(
            warn_threshold=0.02,
            reduce_threshold=0.05,
            halt_threshold=0.10,
            emergency_threshold=0.15,
            recovery_threshold=0.01,
            max_drawdown_limit=0.20,
        )
        dd_manager = DrawdownManager(limits=dd_limits)

        # Simulate equity curve: rise then crash
        dd_manager.update_equity(1_000_000.0, timestamp=1.0)
        dd_manager.update_equity(1_100_000.0, timestamp=2.0)  # New peak
        dd_manager.update_equity(900_000.0, timestamp=3.0)   # -18% drawdown

        snapshot = dd_manager.get_snapshot()
        self.assertGreater(snapshot.drawdown, 0.15)
        self.assertEqual(snapshot.action, DrawdownAction.EMERGENCY)
        self.assertEqual(snapshot.state, DrawdownState.HALTED)

        # Now test kill switch with corresponding risk snapshot
        kill_switch = KillSwitchController(
            risk_limits=RiskLimits(
                max_drawdown=100_000.0,  # Tight limit
            ),
            venues={"binance", "coinbase"},
            venue_connectors={
                "binance": MockVenueConnector("binance", pending_orders=10),
                "coinbase": MockVenueConnector("coinbase", pending_orders=5),
            },
        )

        risk_snapshot = RiskSnapshot(
            timestamp=3.0,
            net_position=100.0,
            net_exposure=5_000_000.0,
            gross_exposure=10_000_000.0,
            unrealized_pnl=-200_000.0,
            realized_pnl=0.0,
            drawdown=200_000.0,  # Exceeds limit
        )

        breached, reason = kill_switch.check_risk(risk_snapshot)
        self.assertTrue(breached)
        self.assertIsNotNone(reason)

        # Trigger halt
        halt_triggered = kill_switch.monitor_risk(risk_snapshot)
        self.assertTrue(halt_triggered)
        self.assertEqual(kill_switch.state, KillSwitchState.HALTED)
        self.assertEqual(kill_switch.orders_cancelled_count, 15)

    def test_kill_switch_audit_trail(self) -> None:
        """Test kill switch generates proper audit trail."""
        kill_switch = KillSwitchController(
            venues={"binance"},
            venue_connectors={
                "binance": MockVenueConnector("binance", pending_orders=3),
            },
        )

        snapshot = RiskSnapshot(
            timestamp=1.0,
            net_position=2_000_000.0,  # Exceeds default limit
            net_exposure=0.0,
            gross_exposure=0.0,
            unrealized_pnl=0.0,
            realized_pnl=0.0,
            drawdown=0.0,
        )

        kill_switch.monitor_risk(snapshot)

        # Verify audit trail
        self.assertTrue(kill_switch.verify_audit_trail())
        events = kill_switch.get_audit_trail()
        self.assertGreater(len(events), 0)

        # Check for expected actions
        actions = [e.action for e in events]
        self.assertIn(AuditAction.ARM, actions)
        self.assertIn(AuditAction.BREACH_DETECTED, actions)
        self.assertIn(AuditAction.HALT_COMPLETE, actions)

    def test_kill_switch_manual_override_and_reset(self) -> None:
        """Test manual override and reset of kill switch."""
        kill_switch = KillSwitchController(
            venues={"binance"},
            venue_connectors={
                "binance": MockVenueConnector("binance", pending_orders=3),
            },
        )

        # Trigger halt
        snapshot = RiskSnapshot(
            timestamp=1.0,
            net_position=2_000_000.0,
            net_exposure=0.0,
            gross_exposure=0.0,
            unrealized_pnl=0.0,
            realized_pnl=0.0,
            drawdown=0.0,
        )
        kill_switch.monitor_risk(snapshot)
        self.assertEqual(kill_switch.state, KillSwitchState.HALTED)

        # Manual override
        success = kill_switch.manual_override("Risk reviewed by CRO")
        self.assertTrue(success)
        self.assertEqual(kill_switch.state, KillSwitchState.OVERRIDE)

        # Manual reset
        success = kill_switch.manual_reset()
        self.assertTrue(success)
        self.assertEqual(kill_switch.state, KillSwitchState.ARMED)


# ---------------------------------------------------------------------------
# Test 7: Risk Overlay → Risk Monitor Pipeline
# ---------------------------------------------------------------------------


class TestOverlayMonitorPipeline(unittest.TestCase):
    """Test risk overlay integration with risk monitor."""

    def test_overlay_signals_feed_monitor(self) -> None:
        """Test overlay hedge signals informing risk monitor."""
        config = RiskOverlayConfig(
            mode="ACTIVE",
            delta_threshold=100.0,
            gamma_threshold=50.0,
            vega_threshold=30.0,
        )
        overlay = RiskOverlayEngine(config=config)

        # Update with Greeks that breach thresholds
        greeks = PortfolioGreeks(delta=500.0, gamma=200.0, vega=100.0)
        signals = overlay.update_greeks(greeks)

        self.assertGreater(len(signals), 0)
        self.assertEqual(overlay.status, "HEDGING")

        # Verify signal details
        for signal in signals:
            self.assertIsInstance(signal, HedgeSignal)
            self.assertIn(signal.direction, ["BUY", "SELL"])
            self.assertGreater(signal.notional, 0.0)

        # Execute hedge
        if signals:
            success = overlay.execute_hedge(signals[0])
            self.assertTrue(success)

    def test_overlay_passive_mode(self) -> None:
        """Test passive overlay mode generates no signals."""
        config = RiskOverlayConfig(mode="PASSIVE")
        overlay = RiskOverlayEngine(config=config)

        greeks = PortfolioGreeks(delta=500.0, gamma=200.0, vega=100.0)
        signals = overlay.update_greeks(greeks)

        self.assertEqual(len(signals), 0)
        self.assertEqual(overlay.status, "NORMAL")


# ---------------------------------------------------------------------------
# Test 8: VaR Backtest → Risk Monitor Pipeline
# ---------------------------------------------------------------------------


class TestBacktestMonitorPipeline(unittest.TestCase):
    """Test VaR backtesting informing risk monitor thresholds."""

    def test_backtest_informs_thresholds(self) -> None:
        """Test backtest results used to validate risk thresholds."""
        # Generate returns and VaR estimates
        rng = np.random.default_rng(42)
        returns = rng.standard_normal(500) * 0.02
        var_estimates = np.abs(rng.standard_normal(500) * 10_000.0)

        backtester = VaRBacktester(confidence=0.95)
        result = backtester.run(var_estimates, returns)

        self.assertEqual(result.n_observations, 500)
        self.assertGreaterEqual(result.n_exceptions, 0)
        self.assertIn(result.traffic_light, ["green", "yellow", "red"])

        # Use backtest result to inform risk monitor
        monitor = RiskMonitor(
            thresholds=RiskThresholds(
                var_limit=50_000.0,
                cvar_limit=75_000.0,
                stress_loss_limit=100_000.0,
                max_drawdown_pct=0.10,
                max_concentration_pct=0.30,
            )
        )

        positions = _make_positions()
        monitor.update_positions(positions)
        monitor.update_returns(returns.tolist())

        # If backtest shows issues, tighten thresholds
        if result.traffic_light == "red":
            monitor.update_thresholds(
                RiskThresholds(
                    var_limit=25_000.0,
                    cvar_limit=37_500.0,
                    stress_loss_limit=50_000.0,
                    max_drawdown_pct=0.05,
                    max_concentration_pct=0.15,
                )
            )

        report = monitor.generate_report()
        self.assertIsNotNone(report)

    def test_backtest_rolling_window(self) -> None:
        """Test rolling window backtest."""
        rng = np.random.default_rng(42)
        returns = rng.standard_normal(500) * 0.02
        var_estimates = np.abs(rng.standard_normal(500) * 10_000.0)

        backtester = VaRBacktester(confidence=0.95, min_observations=100)
        results = backtester.run_rolling(var_estimates, returns, window=250)

        self.assertEqual(len(results), 251)  # 500 - 250 + 1
        for result in results:
            self.assertEqual(result.n_observations, 250)


# ---------------------------------------------------------------------------
# Test 9: Copula Aggregation → Risk Report Pipeline
# ---------------------------------------------------------------------------


class TestCopulaReportPipeline(unittest.TestCase):
    """Test copula-based aggregation feeding into risk reports."""

    def test_copula_aggregation_to_report(self) -> None:
        """Test copula aggregation results used in risk reporting."""
        returns = _generate_correlated_returns(n=200, seed=42)

        # Test all copula types
        for copula_type in CopulaType:
            aggregator = CopulaRiskAggregator(
                copula_type=copula_type, n_scenarios=1000, random_seed=42
            )
            aggregator.fit(returns)
            result = aggregator.aggregate({"equity": 0.6, "rates": 0.4})

            self.assertIsNotNone(result)
            self.assertGreater(result.portfolio_var, 0.0)
            self.assertGreaterEqual(result.portfolio_cvar, result.portfolio_var)
            self.assertIn("equity", result.component_vars)
            self.assertIn("rates", result.component_vars)
            self.assertEqual(result.copula_type, copula_type)

    def test_copula_diversification_benefit(self) -> None:
        """Test diversification benefit calculation."""
        returns = _generate_correlated_returns(n=200, seed=42)
        aggregator = CopulaRiskAggregator(
            copula_type=CopulaType.GAUSSIAN, n_scenarios=1000
        )
        aggregator.fit(returns)
        result = aggregator.aggregate({"equity": 0.5, "rates": 0.5})

        self.assertIsNotNone(result.diversification_benefit)
        # Diversification benefit should be between 0 and 1 for correlated assets
        self.assertGreaterEqual(result.diversification_benefit, 0.0)
        self.assertLessEqual(result.diversification_benefit, 1.0)


# ---------------------------------------------------------------------------
# Test 10: Multi-Factor Risk Pipeline (Market + Credit + Liquidity)
# ---------------------------------------------------------------------------


class TestMultiFactorRiskPipeline(unittest.TestCase):
    """Test combining market, credit, and liquidity risk."""

    def test_multi_factor_risk_aggregation(self) -> None:
        """Test aggregating risk across multiple risk factors."""
        # Market risk (VaR)
        monitor = RiskMonitor(
            thresholds=RiskThresholds(
                var_limit=500_000.0,
                cvar_limit=750_000.0,
                stress_loss_limit=1_000_000.0,
                max_drawdown_pct=0.10,
                max_concentration_pct=0.30,
            )
        )
        positions = _make_positions()
        monitor.update_positions(positions)
        returns = _generate_returns(n=200, seed=42)
        monitor.update_returns(returns)

        var_result = monitor.calculate_var()
        self.assertIsNotNone(var_result)

        # Credit risk (Liquidity)
        liq_engine = LiquidityRiskEngine()
        liq_engine.lcr_calculator.add_hqla_asset(
            HQLAAsset(
                asset_id="cash",
                hqla_type=HQLAType.LEVEL_1,
                market_value=2_000_000.0,
            )
        )
        liq_engine.lcr_calculator.add_cash_flow(
            CashFlow(
                flow_id="outflow",
                flow_type=CashFlowType.OUTFLOW,
                category=OutflowCategory.WHOLESALE_DEPOSITS,
                amount=500_000.0,
            )
        )
        liq_alerts = liq_engine.check_liquidity()

        # Stress risk
        suite = create_default_stress_suite()
        stress_results = suite.run_all(
            {"equities": 1_000_000.0, "credit": 500_000.0}
        )
        stress_summary = suite.summarize(stress_results)

        # Verify all three risk types produced results
        self.assertIsNotNone(var_result)
        self.assertIsInstance(liq_alerts, list)
        self.assertEqual(stress_summary.total_scenarios, 4)

    def test_risk_budget_across_categories(self) -> None:
        """Test risk budgets across market, credit, and liquidity."""
        manager = RiskBudgetManager()

        # Market risk budget
        manager.add_budget(
            RiskBudget(
                budget_id="market-var",
                level=BudgetLevel.DESK,
                allocated_var=1_000_000.0,
            )
        )

        # Credit risk budget
        manager.add_budget(
            RiskBudget(
                budget_id="credit-var",
                level=BudgetLevel.DESK,
                allocated_var=500_000.0,
            )
        )

        # Liquidity risk budget
        manager.add_budget(
            RiskBudget(
                budget_id="liquidity",
                level=BudgetLevel.DESK,
                allocated_exposure=2_000_000.0,
            )
        )

        # Update utilizations
        manager.update_utilization("market-var", current_var=300_000.0)
        manager.update_utilization("credit-var", current_var=200_000.0)
        manager.update_utilization("liquidity", current_exposure=800_000.0)

        report = manager.generate_report()
        self.assertEqual(report.total_allocated_var, 1_500_000.0)
        self.assertEqual(report.total_current_var, 500_000.0)
        self.assertEqual(len(report.budgets), 3)


# ---------------------------------------------------------------------------
# Test 11: Risk Budget → Stress Test → Kill Switch Pipeline
# ---------------------------------------------------------------------------


class TestBudgetStressKillSwitchPipeline(unittest.TestCase):
    """Test full chain: budget breach → stress test → kill switch."""

    def test_breach_to_halt_chain(self) -> None:
        """Test budget breach leading to stress test and kill switch."""
        # 1. Set up budget
        manager = RiskBudgetManager()
        manager.add_budget(
            RiskBudget(
                budget_id="firm",
                level=BudgetLevel.FIRM,
                allocated_var=100_000.0,
                breach_threshold_pct=100.0,
            )
        )

        # 2. Breach budget (110% = BREACHED)
        util = manager.update_utilization("firm", current_var=110_000.0)
        self.assertEqual(util.status, BudgetStatus.BREACHED)

        # 3. Run stress test
        suite = create_default_stress_suite()
        positions = {"equities": 1_000_000.0, "credit": 500_000.0}
        stress_results = suite.run_all(positions)
        summary = suite.summarize(stress_results)

        # 4. If stress is severe, trigger kill switch
        if summary.worst_pnl < -200_000.0:
            kill_switch = KillSwitchController(
                risk_limits=RiskLimits(
                    max_net_position=100_000.0,
                    max_drawdown=100_000.0,
                ),
                venues={"binance"},
                venue_connectors={
                    "binance": MockVenueConnector("binance", pending_orders=5),
                },
            )
            snapshot = RiskSnapshot(
                timestamp=1.0,
                net_position=500_000.0,
                net_exposure=0.0,
                gross_exposure=0.0,
                unrealized_pnl=summary.worst_pnl,
                realized_pnl=0.0,
                drawdown=abs(summary.worst_pnl),
            )
            kill_switch.monitor_risk(snapshot)
            self.assertEqual(kill_switch.state, KillSwitchState.HALTED)


# ---------------------------------------------------------------------------
# Test 12: Risk Appetite → Limit Breach → Alert Pipeline
# ---------------------------------------------------------------------------


class TestAppetiteBreachAlertPipeline(unittest.TestCase):
    """Test appetite framework limit breach generating alerts."""

    def test_limit_breach_to_alert(self) -> None:
        """Test limit breach generating proper alerts."""
        breaches: List[LimitBreach] = []

        class BreachHandler:
            def on_limit_breach(self, breach: LimitBreach) -> None:
                breaches.append(breach)

        framework = RiskAppetiteFramework(alert_handlers=[BreachHandler()])
        framework.set_appetite_statement(
            RiskAppetiteStatement(
                statement_id="RAS-001",
                appetite_level=RiskAppetiteLevel.MODERATE,
                max_portfolio_var=1_000_000.0,
                max_leverage_ratio=10.0,
                max_concentration_pct=25.0,
                max_daily_loss_pct=2.0,
                min_liquidity_ratio=1.5,
            )
        )

        framework.add_limit(
            RiskLimit(
                limit_id="LIM-001",
                category=RiskToleranceCategory.MARKET,
                limit_type=LimitType.HARD,
                threshold_value=100_000.0,
            )
        )

        # Breach the limit (110% = BREACHED)
        util = framework.update_utilization("LIM-001", current_value=110_000.0)
        self.assertEqual(util.status, LimitStatus.BREACHED)
        self.assertEqual(len(breaches), 1)
        self.assertEqual(breaches[0].limit_id, "LIM-001")
        self.assertEqual(breaches[0].severity, LimitBreachSeverity.MEDIUM)

    def test_multiple_limit_breaches(self) -> None:
        """Test multiple limit breaches tracked correctly."""
        framework = RiskAppetiteFramework()
        framework.set_appetite_statement(
            RiskAppetiteStatement(
                statement_id="RAS-001",
                appetite_level=RiskAppetiteLevel.MODERATE,
                max_portfolio_var=1_000_000.0,
                max_leverage_ratio=10.0,
                max_concentration_pct=25.0,
                max_daily_loss_pct=2.0,
                min_liquidity_ratio=1.5,
            )
        )

        framework.add_limit(
            RiskLimit(
                limit_id="LIM-001",
                category=RiskToleranceCategory.MARKET,
                limit_type=LimitType.HARD,
                threshold_value=100_000.0,
            )
        )
        framework.add_limit(
            RiskLimit(
                limit_id="LIM-002",
                category=RiskToleranceCategory.CREDIT,
                limit_type=LimitType.HARD,
                threshold_value=200_000.0,
            )
        )

        framework.update_utilization("LIM-001", current_value=120_000.0)
        framework.update_utilization("LIM-002", current_value=250_000.0)

        breaches = framework.get_breaches()
        self.assertEqual(len(breaches), 2)

        report = framework.generate_report()
        self.assertEqual(report.breached_limits, 2)


# ---------------------------------------------------------------------------
# Test 13: Expected Shortfall → Risk Monitor Pipeline
# ---------------------------------------------------------------------------


class TestESMonitorPipeline(unittest.TestCase):
    """Test Expected Shortfall integration with risk monitor."""

    def test_es_informs_risk_thresholds(self) -> None:
        """Test ES calculation informing risk threshold setting."""
        returns = _generate_returns(n=200, seed=42)

        es_calc = ExpectedShortfallCalculator(confidence=0.975)
        es_calc.set_returns(returns)
        es_result = es_calc.calculate(portfolio_value=1_000_000.0)

        self.assertIsNotNone(es_result)
        self.assertGreater(es_result.expected_shortfall, 0.0)
        self.assertGreaterEqual(es_result.expected_shortfall, es_result.var)

        # Use ES to set CVaR limit in monitor
        monitor = RiskMonitor(
            thresholds=RiskThresholds(
                var_limit=es_result.var * 0.8,
                cvar_limit=es_result.expected_shortfall * 1.2,
                stress_loss_limit=es_result.expected_shortfall * 2.0,
                max_drawdown_pct=0.10,
                max_concentration_pct=0.30,
            )
        )

        positions = _make_positions()
        monitor.update_positions(positions)
        monitor.update_returns(returns.tolist())

        cvar_result = monitor.calculate_cvar()
        self.assertIsNotNone(cvar_result)


# ---------------------------------------------------------------------------
# Test 14: Greeks Monitoring → Risk Overlay Pipeline
# ---------------------------------------------------------------------------


class TestGreeksOverlayPipeline(unittest.TestCase):
    """Test Greeks monitoring feeding into risk overlay."""

    def test_greeks_to_overlay_signals(self) -> None:
        """Test portfolio Greeks triggering overlay hedge signals."""
        # Create monitor with option positions
        monitor = RiskMonitor(
            thresholds=RiskThresholds(
                var_limit=500_000.0,
                cvar_limit=750_000.0,
                stress_loss_limit=1_000_000.0,
                delta_limit=5.0,
                gamma_limit=0.01,
                theta_limit=500.0,
                vega_limit=500.0,
                max_drawdown_pct=0.10,
                max_concentration_pct=0.30,
            )
        )

        positions = _make_option_positions()
        monitor.update_positions(positions)
        returns = _generate_returns(n=200, seed=42)
        monitor.update_returns(returns)

        # Get aggregated Greeks
        greeks = monitor.get_greeks()
        self.assertIsNotNone(greeks)
        self.assertNotEqual(greeks.net_delta, 0.0)

        # Feed Greeks into overlay
        overlay = RiskOverlayEngine(
            config=RiskOverlayConfig(
                mode="ACTIVE",
                delta_threshold=1.0,
                gamma_threshold=0.005,
                vega_threshold=50.0,
            )
        )

        portfolio_greeks = PortfolioGreeks(
            delta=greeks.net_delta,
            gamma=greeks.net_gamma,
            vega=greeks.net_vega,
        )
        signals = overlay.update_greeks(portfolio_greeks)

        # Should generate hedge signals
        self.assertGreater(len(signals), 0)
        self.assertEqual(overlay.status, "HEDGING")


# ---------------------------------------------------------------------------
# Test 15: Complete Risk Report Generation
# ---------------------------------------------------------------------------


class TestCompleteRiskReport(unittest.TestCase):
    """Test comprehensive risk report generation across all modules."""

    def test_comprehensive_risk_report(self) -> None:
        """Test generating a complete risk report from all modules."""
        # Set up monitor
        alert_handler = MockAlertHandler()
        monitor = RiskMonitor(
            thresholds=RiskThresholds(
                var_limit=500_000.0,
                cvar_limit=750_000.0,
                stress_loss_limit=1_000_000.0,
                delta_limit=10_000.0,
                gamma_limit=1_000.0,
                theta_limit=50_000.0,
                vega_limit=50_000.0,
                max_drawdown_pct=0.10,
                max_concentration_pct=0.30,
            ),
            alert_handlers=[alert_handler],
        )

        positions = _make_positions() + _make_option_positions()
        monitor.update_positions(positions)
        returns = _generate_returns(n=200, seed=42)
        monitor.update_returns(returns)

        # Add stress scenarios
        monitor.add_stress_scenario(
            StressScenario(
                name="crash",
                scenario_type=StressScenarioType.HISTORICAL,
                shocks={"BTC-PERP": -0.15, "ETH-PERP": -0.20, "SOL-PERP": -0.25},
            )
        )

        # Run risk check
        alerts = monitor.check_risk()

        # Generate comprehensive report
        report = monitor.generate_report()

        # Verify report completeness
        self.assertIsNotNone(report.var_result)
        self.assertIsNotNone(report.cvar_result)
        self.assertIsNotNone(report.greeks_result)
        self.assertGreater(len(report.stress_results), 0)
        self.assertEqual(report.positions_count, 5)
        self.assertGreater(report.gross_exposure, 0.0)
        self.assertIsInstance(report.alerts, list)

        # Verify drawdown tracking
        drawdown = monitor.get_drawdown()
        self.assertGreaterEqual(drawdown, 0.0)

        # Verify exposure calculations
        gross = monitor.get_gross_exposure()
        net = monitor.get_net_exposure()
        self.assertGreater(gross, 0.0)
        self.assertIsNotNone(net)


if __name__ == "__main__":
    unittest.main()
