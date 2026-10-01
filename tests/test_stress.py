"""Tests for Stress Testing, Monte Carlo VaR, and Scenario Analysis."""
import math
import pytest
from src.risk.stress import (
    HistoricalScenario,
    StressTestResult,
    MonteCarloConfig,
    MonteCarloResult,
    ScenarioConfig,
    ScenarioResult,
    StressTester,
    MonteCarloVaR,
    ScenarioAnalyzer,
)


# ── Historical Stress Testing ───────────────────────────────────────────

class TestHistoricalStressTesting:
    """Tests for historical stress testing engine."""

    def test_stress_tester_initializes(self):
        tester = StressTester()
        assert tester is not None

    def test_single_scenario_applied_to_portfolio(self):
        tester = StressTester()
        scenario = HistoricalScenario(
            name="2008 Crisis",
            shocks={"AAPL": -0.40, "MSFT": -0.35},
        )
        tester.add_scenario(scenario)
        result = tester.run_stress_test({"AAPL": 1000.0, "MSFT": 500.0})
        assert isinstance(result, StressTestResult)
        assert result.scenario_name == "2008 Crisis"
        assert result.portfolio_loss == pytest.approx(-575.0)  # 1000*-0.4 + 500*-0.35

    def test_multiple_scenarios_all_executed(self):
        tester = StressTester()
        tester.add_scenario(HistoricalScenario(name="Crash1", shocks={"AAPL": -0.30}))
        tester.add_scenario(HistoricalScenario(name="Crash2", shocks={"AAPL": -0.50}))
        results = tester.run_all_scenarios({"AAPL": 1000.0})
        assert len(results) == 2
        names = {r.scenario_name for r in results}
        assert names == {"Crash1", "Crash2"}

    def test_scenario_with_no_matching_positions(self):
        tester = StressTester()
        tester.add_scenario(HistoricalScenario(name="Tech Crash", shocks={"AAPL": -0.50}))
        result = tester.run_stress_test({"GOOG": 1000.0})
        assert result.portfolio_loss == 0.0

    def test_empty_portfolio_no_loss(self):
        tester = StressTester()
        tester.add_scenario(HistoricalScenario(name="Crisis", shocks={"AAPL": -0.50}))
        result = tester.run_stress_test({})
        assert result.portfolio_loss == 0.0

    def test_partial_portfolio_match(self):
        tester = StressTester()
        tester.add_scenario(
            HistoricalScenario(name="Mixed", shocks={"AAPL": -0.20, "MSFT": -0.10})
        )
        result = tester.run_stress_test({"AAPL": 1000.0, "GOOG": 2000.0})
        assert result.portfolio_loss == pytest.approx(-200.0)  # only AAPL matches

    def test_scenario_with_volatility_shock(self):
        tester = StressTester()
        scenario = HistoricalScenario(
            name="Vol Spike",
            shocks={"AAPL": -0.10},
            volatility_multiplier=2.5,
        )
        tester.add_scenario(scenario)
        result = tester.run_stress_test({"AAPL": 1000.0})
        assert result.portfolio_loss == pytest.approx(-100.0)
        assert result.volatility_multiplier == 2.5

    def test_stress_result_contains_shocked_values(self):
        tester = StressTester()
        tester.add_scenario(HistoricalScenario(name="Test", shocks={"AAPL": -0.25}))
        result = tester.run_stress_test({"AAPL": 100.0})
        assert result.shocked_values["AAPL"] == pytest.approx(75.0)

    def test_stress_result_loss_pct(self):
        tester = StressTester()
        tester.add_scenario(HistoricalScenario(name="Test", shocks={"AAPL": -0.20}))
        result = tester.run_stress_test({"AAPL": 1000.0})
        assert result.loss_pct == pytest.approx(0.20)

    def test_stress_result_zero_portfolio_value(self):
        tester = StressTester()
        tester.add_scenario(HistoricalScenario(name="Test", shocks={"AAPL": -0.20}))
        result = tester.run_stress_test({"AAPL": 0.0})
        assert result.loss_pct == 0.0

    def test_scenario_with_correlation_adjustment(self):
        tester = StressTester()
        scenario = HistoricalScenario(
            name="Correlated",
            shocks={"AAPL": -0.30, "MSFT": -0.30},
            correlation_factor=1.2,
        )
        tester.add_scenario(scenario)
        result = tester.run_stress_test({"AAPL": 1000.0, "MSFT": 1000.0})
        # With correlation > 1, losses are amplified
        assert result.portfolio_loss < -600.0

    def test_remove_scenario(self):
        tester = StressTester()
        tester.add_scenario(HistoricalScenario(name="Test", shocks={"AAPL": -0.10}))
        tester.remove_scenario("Test")
        results = tester.run_all_scenarios({"AAPL": 100.0})
        assert len(results) == 0

    def test_clear_all_scenarios(self):
        tester = StressTester()
        tester.add_scenario(HistoricalScenario(name="S1", shocks={"AAPL": -0.10}))
        tester.add_scenario(HistoricalScenario(name="S2", shocks={"AAPL": -0.20}))
        tester.clear_scenarios()
        assert len(tester._scenarios) == 0

    def test_scenario_with_description(self):
        scenario = HistoricalScenario(
            name="COVID Crash",
            shocks={"SPY": -0.34},
            description="March 2020 COVID-19 market crash",
        )
        assert scenario.description == "March 2020 COVID-19 market crash"

    def test_worst_scenario_identified(self):
        tester = StressTester()
        tester.add_scenario(HistoricalScenario(name="Mild", shocks={"AAPL": -0.10}))
        tester.add_scenario(HistoricalScenario(name="Severe", shocks={"AAPL": -0.60}))
        tester.add_scenario(HistoricalScenario(name="Moderate", shocks={"AAPL": -0.30}))
        results = tester.run_all_scenarios({"AAPL": 1000.0})
        worst = tester.get_worst_scenario(results)
        assert worst.scenario_name == "Severe"
        assert worst.portfolio_loss == pytest.approx(-600.0)


# ── Monte Carlo VaR ─────────────────────────────────────────────────────

class TestMonteCarloVaR:
    """Tests for Monte Carlo Value-at-Risk calculator."""

    def test_monte_carlo_var_initializes(self):
        mc = MonteCarloVaR()
        assert mc is not None

    def test_basic_var_calculation(self):
        mc = MonteCarloVaR(seed=42)
        config = MonteCarloConfig(
            portfolio_value=1_000_000.0,
            expected_return=0.0005,
            volatility=0.02,
            time_horizon=1,
            num_simulations=10_000,
            confidence_level=0.95,
        )
        result = mc.calculate_var(config)
        assert isinstance(result, MonteCarloResult)
        assert result.var > 0
        assert result.confidence_level == 0.95

    def test_higher_confidence_higher_var(self):
        mc = MonteCarloVaR(seed=42)
        config_95 = MonteCarloConfig(
            portfolio_value=1_000_000.0,
            expected_return=0.0,
            volatility=0.02,
            time_horizon=1,
            num_simulations=10_000,
            confidence_level=0.95,
        )
        config_99 = MonteCarloConfig(
            portfolio_value=1_000_000.0,
            expected_return=0.0,
            volatility=0.02,
            time_horizon=1,
            num_simulations=10_000,
            confidence_level=0.99,
        )
        result_95 = mc.calculate_var(config_95)
        result_99 = mc.calculate_var(config_99)
        assert result_99.var > result_95.var

    def test_longer_horizon_higher_var(self):
        mc = MonteCarloVaR(seed=42)
        config_1d = MonteCarloConfig(
            portfolio_value=1_000_000.0,
            expected_return=0.0,
            volatility=0.02,
            time_horizon=1,
            num_simulations=10_000,
            confidence_level=0.95,
        )
        config_10d = MonteCarloConfig(
            portfolio_value=1_000_000.0,
            expected_return=0.0,
            volatility=0.02,
            time_horizon=10,
            num_simulations=10_000,
            confidence_level=0.95,
        )
        result_1d = mc.calculate_var(config_1d)
        result_10d = mc.calculate_var(config_10d)
        assert result_10d.var > result_1d.var

    def test_reproducibility_with_seed(self):
        mc1 = MonteCarloVaR(seed=123)
        mc2 = MonteCarloVaR(seed=123)
        config = MonteCarloConfig(
            portfolio_value=1_000_000.0,
            expected_return=0.001,
            volatility=0.015,
            time_horizon=1,
            num_simulations=5_000,
            confidence_level=0.95,
        )
        result1 = mc1.calculate_var(config)
        result2 = mc2.calculate_var(config)
        assert result1.var == pytest.approx(result2.var)

    def test_zero_volatility_zero_var(self):
        mc = MonteCarloVaR(seed=42)
        config = MonteCarloConfig(
            portfolio_value=1_000_000.0,
            expected_return=0.001,
            volatility=0.0,
            time_horizon=1,
            num_simulations=1_000,
            confidence_level=0.95,
        )
        result = mc.calculate_var(config)
        assert result.var == 0.0

    def test_negative_expected_return(self):
        mc = MonteCarloVaR(seed=42)
        config = MonteCarloConfig(
            portfolio_value=1_000_000.0,
            expected_return=-0.002,
            volatility=0.01,
            time_horizon=1,
            num_simulations=5_000,
            confidence_level=0.95,
        )
        result = mc.calculate_var(config)
        assert result.var > 0

    def test_var_scales_with_portfolio_value(self):
        mc = MonteCarloVaR(seed=42)
        config_small = MonteCarloConfig(
            portfolio_value=100_000.0,
            expected_return=0.0,
            volatility=0.02,
            time_horizon=1,
            num_simulations=5_000,
            confidence_level=0.95,
        )
        config_large = MonteCarloConfig(
            portfolio_value=1_000_000.0,
            expected_return=0.0,
            volatility=0.02,
            time_horizon=1,
            num_simulations=5_000,
            confidence_level=0.95,
        )
        result_small = mc.calculate_var(config_small)
        result_large = mc.calculate_var(config_large)
        assert result_large.var == pytest.approx(result_small.var * 10, rel=0.05)

    def test_expected_shortfall_calculated(self):
        mc = MonteCarloVaR(seed=42)
        config = MonteCarloConfig(
            portfolio_value=1_000_000.0,
            expected_return=0.0,
            volatility=0.02,
            time_horizon=1,
            num_simulations=10_000,
            confidence_level=0.95,
        )
        result = mc.calculate_var(config)
        assert result.expected_shortfall > result.var

    def test_result_contains_simulation_count(self):
        mc = MonteCarloVaR(seed=42)
        config = MonteCarloConfig(
            portfolio_value=1_000_000.0,
            expected_return=0.0,
            volatility=0.02,
            time_horizon=1,
            num_simulations=7_500,
            confidence_level=0.95,
        )
        result = mc.calculate_var(config)
        assert result.num_simulations == 7_500

    def test_multi_asset_portfolio_var(self):
        mc = MonteCarloVaR(seed=42)
        config = MonteCarloConfig(
            portfolio_value=1_000_000.0,
            expected_return=0.0,
            volatility=0.02,
            time_horizon=1,
            num_simulations=5_000,
            confidence_level=0.95,
            asset_weights={"AAPL": 0.4, "MSFT": 0.3, "GOOG": 0.3},
            asset_volatilities={"AAPL": 0.025, "MSFT": 0.02, "GOOG": 0.03},
            correlation_matrix=None,
        )
        result = mc.calculate_var(config)
        assert result.var > 0

    def test_var_as_percentage(self):
        mc = MonteCarloVaR(seed=42)
        config = MonteCarloConfig(
            portfolio_value=1_000_000.0,
            expected_return=0.0,
            volatility=0.02,
            time_horizon=1,
            num_simulations=5_000,
            confidence_level=0.95,
        )
        result = mc.calculate_var(config)
        assert result.var_pct > 0
        assert result.var_pct < 1.0


# ── Scenario Analysis ───────────────────────────────────────────────────

class TestScenarioAnalysis:
    """Tests for scenario analysis engine."""

    def test_scenario_analyzer_initializes(self):
        analyzer = ScenarioAnalyzer()
        assert analyzer is not None

    def test_single_factor_shock(self):
        analyzer = ScenarioAnalyzer()
        config = ScenarioConfig(
            name="Rate Hike",
            factor_shocks={"interest_rate": 0.02},
            factor_sensitivities={"AAPL": -0.5, "MSFT": -0.3},
        )
        result = analyzer.analyze(config, {"AAPL": 1000.0, "MSFT": 500.0})
        assert isinstance(result, ScenarioResult)
        assert result.scenario_name == "Rate Hike"
        # AAPL: 1000 * -0.5 * 0.02 = -10, MSFT: 500 * -0.3 * 0.02 = -3
        assert result.portfolio_impact == pytest.approx(-13.0)

    def test_multiple_factor_shocks(self):
        analyzer = ScenarioAnalyzer()
        config = ScenarioConfig(
            name="Stagflation",
            factor_shocks={"interest_rate": 0.03, "inflation": 0.02},
            factor_sensitivities={"AAPL": -0.4, "MSFT": -0.2},
        )
        result = analyzer.analyze(config, {"AAPL": 1000.0})
        # AAPL: 1000 * (-0.4) * (0.03 + 0.02) = -20
        assert result.portfolio_impact == pytest.approx(-20.0)

    def test_scenario_with_no_matching_assets(self):
        analyzer = ScenarioAnalyzer()
        config = ScenarioConfig(
            name="Tech Specific",
            factor_shocks={"tech_sector": -0.10},
            factor_sensitivities={"AAPL": -1.0},
        )
        result = analyzer.analyze(config, {"GOOG": 1000.0})
        assert result.portfolio_impact == 0.0

    def test_empty_portfolio_zero_impact(self):
        analyzer = ScenarioAnalyzer()
        config = ScenarioConfig(
            name="Any",
            factor_shocks={"rate": 0.01},
            factor_sensitivities={"AAPL": -1.0},
        )
        result = analyzer.analyze(config, {})
        assert result.portfolio_impact == 0.0

    def test_scenario_result_contains_asset_impacts(self):
        analyzer = ScenarioAnalyzer()
        config = ScenarioConfig(
            name="Test",
            factor_shocks={"rate": 0.01},
            factor_sensitivities={"AAPL": -0.5, "MSFT": -0.3},
        )
        result = analyzer.analyze(config, {"AAPL": 1000.0, "MSFT": 500.0})
        assert "AAPL" in result.asset_impacts
        assert "MSFT" in result.asset_impacts
        assert result.asset_impacts["AAPL"] == pytest.approx(-5.0)

    def test_scenario_impact_percentage(self):
        analyzer = ScenarioAnalyzer()
        config = ScenarioConfig(
            name="Test",
            factor_shocks={"rate": 0.01},
            factor_sensitivities={"AAPL": -0.5},
        )
        result = analyzer.analyze(config, {"AAPL": 1000.0})
        assert result.impact_pct == pytest.approx(0.005)  # 5/1000

    def test_positive_shock_positive_impact(self):
        analyzer = ScenarioAnalyzer()
        config = ScenarioConfig(
            name="Rate Cut",
            factor_shocks={"interest_rate": -0.02},
            factor_sensitivities={"AAPL": -0.5},
        )
        result = analyzer.analyze(config, {"AAPL": 1000.0})
        assert result.portfolio_impact > 0

    def test_scenario_with_zero_sensitivity(self):
        analyzer = ScenarioAnalyzer()
        config = ScenarioConfig(
            name="Neutral",
            factor_shocks={"rate": 0.05},
            factor_sensitivities={"AAPL": 0.0},
        )
        result = analyzer.analyze(config, {"AAPL": 1000.0})
        assert result.portfolio_impact == 0.0

    def test_multiple_scenarios_ranked(self):
        analyzer = ScenarioAnalyzer()
        configs = [
            ScenarioConfig(
                name="Mild",
                factor_shocks={"rate": 0.01},
                factor_sensitivities={"AAPL": -0.5},
            ),
            ScenarioConfig(
                name="Severe",
                factor_shocks={"rate": 0.05},
                factor_sensitivities={"AAPL": -0.5},
            ),
            ScenarioConfig(
                name="Moderate",
                factor_shocks={"rate": 0.03},
                factor_sensitivities={"AAPL": -0.5},
            ),
        ]
        results = [analyzer.analyze(c, {"AAPL": 1000.0}) for c in configs]
        ranked = analyzer.rank_scenarios(results)
        assert ranked[0].scenario_name == "Severe"
        assert ranked[-1].scenario_name == "Mild"

    def test_scenario_with_custom_description(self):
        config = ScenarioConfig(
            name="Custom",
            factor_shocks={"rate": 0.01},
            factor_sensitivities={"AAPL": -0.5},
            description="Custom scenario description",
        )
        assert config.description == "Custom scenario description"

    def test_scenario_aggregation_portfolio_level(self):
        analyzer = ScenarioAnalyzer()
        config = ScenarioConfig(
            name="Portfolio Shock",
            factor_shocks={"market": 0.10},
            factor_sensitivities={"AAPL": -1.0, "MSFT": -0.8, "GOOG": -0.6},
        )
        result = analyzer.analyze(config, {"AAPL": 5000.0, "MSFT": 3000.0, "GOOG": 2000.0})
        # AAPL: 5000 * -1.0 * 0.10 = -500
        # MSFT: 3000 * -0.8 * 0.10 = -240
        # GOOG: 2000 * -0.6 * 0.10 = -120
        assert result.portfolio_impact == pytest.approx(-860.0)

    def test_scenario_with_time_decay(self):
        analyzer = ScenarioAnalyzer()
        config = ScenarioConfig(
            name="Decaying Shock",
            factor_shocks={"rate": 0.02},
            factor_sensitivities={"AAPL": -0.5},
            time_horizon=10,
            decay_factor=0.95,
        )
        result = analyzer.analyze(config, {"AAPL": 1000.0})
        # With decay, impact is reduced over time
        assert result.portfolio_impact > -10.0  # less than instantaneous -10

    def test_scenario_recovery_analysis(self):
        analyzer = ScenarioAnalyzer()
        config = ScenarioConfig(
            name="Crash & Recovery",
            factor_shocks={"market": 0.30},
            factor_sensitivities={"AAPL": -1.0},
            recovery_rate=0.05,
        )
        result = analyzer.analyze(config, {"AAPL": 1000.0})
        assert result.portfolio_impact == pytest.approx(-300.0)
        assert result.recovery_estimate is not None
        assert result.recovery_estimate > 0

    def test_scenario_with_correlation_matrix(self):
        analyzer = ScenarioAnalyzer()
        config = ScenarioConfig(
            name="Correlated Shock",
            factor_shocks={"market": 0.10},
            factor_sensitivities={"AAPL": -1.0, "MSFT": -0.8},
            correlation_matrix={"AAPL": {"MSFT": 0.8}, "MSFT": {"AAPL": 0.8}},
        )
        result = analyzer.analyze(config, {"AAPL": 1000.0, "MSFT": 1000.0})
        # Correlation amplifies the impact
        assert result.portfolio_impact < -180.0  # more than -100 + -80

    def test_scenario_with_volatility_regime(self):
        analyzer = ScenarioAnalyzer()
        config = ScenarioConfig(
            name="High Vol Regime",
            factor_shocks={"market": 0.05},
            factor_sensitivities={"AAPL": -1.0},
            volatility_regime="high",
        )
        result = analyzer.analyze(config, {"AAPL": 1000.0})
        assert result.portfolio_impact < -50.0  # amplified by high vol

    def test_scenario_with_liquidity_adjustment(self):
        analyzer = ScenarioAnalyzer()
        config = ScenarioConfig(
            name="Illiquid Market",
            factor_shocks={"market": 0.10},
            factor_sensitivities={"AAPL": -1.0},
            liquidity_factor=0.7,
        )
        result = analyzer.analyze(config, {"AAPL": 1000.0})
        # Illiquidity amplifies losses
        assert result.portfolio_impact < -100.0

    def test_scenario_stress_combination(self):
        """Test combining stress test with scenario analysis."""
        tester = StressTester()
        tester.add_scenario(HistoricalScenario(name="Base", shocks={"AAPL": -0.20}))
        analyzer = ScenarioAnalyzer()
        config = ScenarioConfig(
            name="Overlay",
            factor_shocks={"rate": 0.01},
            factor_sensitivities={"AAPL": -0.5},
        )
        stress_result = tester.run_stress_test({"AAPL": 1000.0})
        scenario_result = analyzer.analyze(config, {"AAPL": 1000.0})
        combined = stress_result.portfolio_loss + scenario_result.portfolio_impact
        assert combined == pytest.approx(-205.0)  # -200 + -5

    def test_scenario_with_tail_risk_metric(self):
        analyzer = ScenarioAnalyzer()
        config = ScenarioConfig(
            name="Tail Risk",
            factor_shocks={"market": 0.20},
            factor_sensitivities={"AAPL": -1.0},
        )
        result = analyzer.analyze(config, {"AAPL": 1000.0})
        assert result.tail_risk is not None
        assert result.tail_risk > 0

    def test_scenario_with_confidence_interval(self):
        analyzer = ScenarioAnalyzer()
        config = ScenarioConfig(
            name="CI Test",
            factor_shocks={"market": -0.10},
            factor_sensitivities={"AAPL": -1.0},
            confidence_level=0.95,
        )
        result = analyzer.analyze(config, {"AAPL": 1000.0})
        assert result.confidence_interval is not None
        lower, upper = result.confidence_interval
        assert lower < upper
        assert lower <= result.portfolio_impact <= upper
