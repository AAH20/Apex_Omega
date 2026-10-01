"""Stress Testing, Monte Carlo VaR, and Scenario Analysis for Apex_Omega Risk Engine."""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


# ── Historical Stress Testing ───────────────────────────────────────────

@dataclass
class HistoricalScenario:
    """A historical stress scenario with asset shocks."""
    name: str
    shocks: Dict[str, float]
    description: str = ""
    volatility_multiplier: float = 1.0
    correlation_factor: float = 1.0


@dataclass
class StressTestResult:
    """Result of a stress test on a portfolio."""
    scenario_name: str
    portfolio_loss: float
    loss_pct: float
    shocked_values: Dict[str, float] = field(default_factory=dict)
    volatility_multiplier: float = 1.0


class StressTester:
    """Applies historical stress scenarios to portfolios."""

    def __init__(self) -> None:
        self._scenarios: List[HistoricalScenario] = []

    def add_scenario(self, scenario: HistoricalScenario) -> None:
        self._scenarios.append(scenario)

    def remove_scenario(self, name: str) -> None:
        self._scenarios = [s for s in self._scenarios if s.name != name]

    def clear_scenarios(self) -> None:
        self._scenarios.clear()

    def run_stress_test(self, portfolio: Dict[str, float]) -> StressTestResult:
        """Run the first scenario against the portfolio."""
        if not self._scenarios:
            return StressTestResult(
                scenario_name="",
                portfolio_loss=0.0,
                loss_pct=0.0,
            )
        return self._apply_scenario(self._scenarios[0], portfolio)

    def run_all_scenarios(self, portfolio: Dict[str, float]) -> List[StressTestResult]:
        """Run all scenarios against the portfolio."""
        return [self._apply_scenario(s, portfolio) for s in self._scenarios]

    def get_worst_scenario(self, results: List[StressTestResult]) -> Optional[StressTestResult]:
        """Return the scenario with the largest loss."""
        if not results:
            return None
        return min(results, key=lambda r: r.portfolio_loss)

    def _apply_scenario(
        self, scenario: HistoricalScenario, portfolio: Dict[str, float]
    ) -> StressTestResult:
        total_value = sum(portfolio.values())
        portfolio_loss = 0.0
        shocked_values: Dict[str, float] = {}

        for symbol, value in portfolio.items():
            shock = scenario.shocks.get(symbol, 0.0)
            # Apply correlation factor to amplify/reduce shock
            adjusted_shock = shock * scenario.correlation_factor
            loss = value * adjusted_shock
            portfolio_loss += loss
            shocked_values[symbol] = value + loss

        loss_pct = abs(portfolio_loss) / total_value if total_value > 0 else 0.0

        return StressTestResult(
            scenario_name=scenario.name,
            portfolio_loss=portfolio_loss,
            loss_pct=loss_pct,
            shocked_values=shocked_values,
            volatility_multiplier=scenario.volatility_multiplier,
        )


# ── Monte Carlo VaR ──────────────────────────────────────────────────────

@dataclass
class MonteCarloConfig:
    """Configuration for Monte Carlo VaR simulation."""
    portfolio_value: float
    expected_return: float
    volatility: float
    time_horizon: int
    num_simulations: int
    confidence_level: float
    asset_weights: Optional[Dict[str, float]] = None
    asset_volatilities: Optional[Dict[str, float]] = None
    correlation_matrix: Optional[Dict[str, Dict[str, float]]] = None


@dataclass
class MonteCarloResult:
    """Result of Monte Carlo VaR simulation."""
    var: float
    expected_shortfall: float
    var_pct: float
    confidence_level: float
    num_simulations: int


class MonteCarloVaR:
    """Monte Carlo Value-at-Risk calculator."""

    def __init__(self, seed: Optional[int] = None) -> None:
        self._rng = random.Random(seed)

    def calculate_var(self, config: MonteCarloConfig) -> MonteCarloResult:
        """Calculate VaR using Monte Carlo simulation."""
        if config.volatility == 0.0:
            return MonteCarloResult(
                var=0.0,
                expected_shortfall=0.0,
                var_pct=0.0,
                confidence_level=config.confidence_level,
                num_simulations=config.num_simulations,
            )

        # Generate simulated returns
        dt = config.time_horizon
        drift = config.expected_return * dt
        vol = config.volatility * math.sqrt(dt)

        simulated_returns: List[float] = []
        for _ in range(config.num_simulations):
            z = self._rng.gauss(0.0, 1.0)
            ret = drift + vol * z
            simulated_returns.append(ret)

        # Sort returns to find percentile
        simulated_returns.sort()

        # VaR is the loss at the confidence level
        var_index = int((1.0 - config.confidence_level) * config.num_simulations)
        var_index = max(0, min(var_index, config.num_simulations - 1))
        var_return = simulated_returns[var_index]
        var = abs(var_return) * config.portfolio_value

        # Expected shortfall: average of returns beyond VaR
        tail_returns = simulated_returns[: var_index + 1]
        if tail_returns:
            avg_tail = sum(tail_returns) / len(tail_returns)
            expected_shortfall = abs(avg_tail) * config.portfolio_value
        else:
            expected_shortfall = var

        var_pct = var / config.portfolio_value if config.portfolio_value > 0 else 0.0

        return MonteCarloResult(
            var=var,
            expected_shortfall=expected_shortfall,
            var_pct=var_pct,
            confidence_level=config.confidence_level,
            num_simulations=config.num_simulations,
        )


# ── Scenario Analysis ────────────────────────────────────────────────────

@dataclass
class ScenarioConfig:
    """Configuration for scenario analysis."""
    name: str
    factor_shocks: Dict[str, float]
    factor_sensitivities: Dict[str, float]
    description: str = ""
    time_horizon: int = 1
    decay_factor: float = 1.0
    recovery_rate: float = 0.0
    correlation_matrix: Optional[Dict[str, Dict[str, float]]] = None
    volatility_regime: str = "normal"
    liquidity_factor: float = 1.0
    confidence_level: float = 0.95


@dataclass
class ScenarioResult:
    """Result of scenario analysis."""
    scenario_name: str
    portfolio_impact: float
    impact_pct: float
    asset_impacts: Dict[str, float] = field(default_factory=dict)
    recovery_estimate: Optional[float] = None
    tail_risk: Optional[float] = None
    confidence_interval: Optional[Tuple[float, float]] = None


class ScenarioAnalyzer:
    """Analyzes portfolio impact under various scenarios."""

    def analyze(self, config: ScenarioConfig, portfolio: Dict[str, float]) -> ScenarioResult:
        """Analyze portfolio impact under a scenario."""
        total_value = sum(portfolio.values())
        asset_impacts: Dict[str, float] = {}
        portfolio_impact = 0.0

        # Calculate total factor shock
        total_shock = sum(config.factor_shocks.values())

        # Apply time decay if applicable
        if config.time_horizon > 1 and config.decay_factor < 1.0:
            total_shock *= config.decay_factor ** config.time_horizon

        # Calculate per-asset impact
        for symbol, value in portfolio.items():
            sensitivity = config.factor_sensitivities.get(symbol, 0.0)
            impact = value * sensitivity * total_shock
            asset_impacts[symbol] = impact
            portfolio_impact += impact

        # Apply volatility regime multiplier
        vol_multiplier = self._get_vol_multiplier(config.volatility_regime)
        portfolio_impact *= vol_multiplier

        # Apply liquidity factor
        if config.liquidity_factor < 1.0:
            portfolio_impact *= (2.0 - config.liquidity_factor)

        # Apply correlation amplification
        if config.correlation_matrix:
            avg_corr = self._avg_correlation(config.correlation_matrix)
            if avg_corr > 0:
                portfolio_impact *= (1.0 + avg_corr)

        impact_pct = abs(portfolio_impact) / total_value if total_value > 0 else 0.0

        # Recovery estimate
        recovery_estimate = None
        if config.recovery_rate > 0 and portfolio_impact < 0:
            recovery_estimate = abs(portfolio_impact) * config.recovery_rate

        # Tail risk
        tail_risk = None
        if portfolio_impact < 0:
            tail_risk = abs(portfolio_impact) * 1.5  # simplified tail risk

        # Confidence interval
        confidence_interval = None
        if config.confidence_level > 0:
            margin = abs(portfolio_impact) * 0.1  # simplified 10% margin
            confidence_interval = (portfolio_impact - margin, portfolio_impact + margin)

        return ScenarioResult(
            scenario_name=config.name,
            portfolio_impact=portfolio_impact,
            impact_pct=impact_pct,
            asset_impacts=asset_impacts,
            recovery_estimate=recovery_estimate,
            tail_risk=tail_risk,
            confidence_interval=confidence_interval,
        )

    def rank_scenarios(self, results: List[ScenarioResult]) -> List[ScenarioResult]:
        """Rank scenarios by impact (most negative first)."""
        return sorted(results, key=lambda r: r.portfolio_impact)

    def _get_vol_multiplier(self, regime: str) -> float:
        multipliers = {
            "low": 0.8,
            "normal": 1.0,
            "high": 1.5,
            "extreme": 2.0,
        }
        return multipliers.get(regime, 1.0)

    def _avg_correlation(self, corr_matrix: Dict[str, Dict[str, float]]) -> float:
        """Calculate average correlation from matrix."""
        values: List[float] = []
        for row in corr_matrix.values():
            for val in row.values():
                values.append(val)
        return sum(values) / len(values) if values else 0.0
