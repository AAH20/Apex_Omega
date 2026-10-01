"""Unit tests for PositionLimitEnforcer — per symbol, venue, and account limits.

TDD: These tests define the contract for src/risk/position_limit.py.
"""

from __future__ import annotations

import pytest

from src.risk.position_limit import (
    EnforcementAction,
    EnforcementDecision,
    LimitBreach,
    LimitUtilizationReporter,
    PositionLimit,
    PositionLimitEnforcer,
    PositionTracker,
    UtilizationReport,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _default_limits() -> PositionLimit:
    return PositionLimit(
        max_position=1_000.0,
        max_exposure=100_000.0,
        max_venue_position=500.0,
        max_venue_exposure=50_000.0,
        max_gross_position=2_000.0,
        max_gross_exposure=200_000.0,
    )


def _conservative_limits() -> PositionLimit:
    return PositionLimit(
        max_position=100.0,
        max_exposure=10_000.0,
        max_venue_position=50.0,
        max_venue_exposure=5_000.0,
        max_gross_position=200.0,
        max_gross_exposure=20_000.0,
    )


# ---------------------------------------------------------------------------
# Test PositionLimit dataclass
# ---------------------------------------------------------------------------

class TestPositionLimit:
    def test_default_thresholds(self):
        lim = PositionLimit(max_position=100, max_exposure=1000)
        assert lim.warn_threshold_pct == 80.0
        assert lim.block_threshold_pct == 100.0
        assert lim.halt_threshold_pct == 120.0

    def test_custom_thresholds(self):
        lim = PositionLimit(
            max_position=100,
            max_exposure=1000,
            warn_threshold_pct=75.0,
            block_threshold_pct=95.0,
            halt_threshold_pct=110.0,
        )
        assert lim.warn_threshold_pct == 75.0
        assert lim.block_threshold_pct == 95.0
        assert lim.halt_threshold_pct == 110.0

    def test_zero_limit_disables_check(self):
        lim = PositionLimit(max_position=0, max_exposure=0)
        assert lim.is_disabled("max_position")
        assert lim.is_disabled("max_exposure")

    def test_nonzero_limit_is_active(self):
        lim = PositionLimit(max_position=100, max_exposure=1000)
        assert not lim.is_disabled("max_position")
        assert not lim.is_disabled("max_exposure")


# ---------------------------------------------------------------------------
# Test PositionLimitEnforcer — PASS cases
# ---------------------------------------------------------------------------

class TestEnforcerPass:
    def test_pass_when_under_all_limits(self):
        enforcer = PositionLimitEnforcer(default_limits=_default_limits())
        decision = enforcer.check_order(
            symbol="BTC-USD",
            venue="binance",
            account="acct-1",
            quantity=10.0,
            price=1.0,
        )
        assert decision.action == EnforcementAction.PASS
        assert decision.breaches == []

    def test_pass_with_zero_quantity(self):
        enforcer = PositionLimitEnforcer(default_limits=_default_limits())
        decision = enforcer.check_order(
            symbol="BTC-USD",
            venue="binance",
            account="acct-1",
            quantity=0.0,
            price=1.0,
        )
        assert decision.action == EnforcementAction.PASS

    def test_pass_with_negative_quantity_under_limit(self):
        enforcer = PositionLimitEnforcer(default_limits=_default_limits())
        decision = enforcer.check_order(
            symbol="BTC-USD",
            venue="binance",
            account="acct-1",
            quantity=-100.0,
            price=1.0,
        )
        assert decision.action == EnforcementAction.PASS


# ---------------------------------------------------------------------------
# Test PositionLimitEnforcer — WARN cases
# ---------------------------------------------------------------------------

class TestEnforcerWarn:
    def test_warn_at_80pct_position(self):
        enforcer = PositionLimitEnforcer(default_limits=_default_limits())
        # 80% of max_venue_position=500 → 400
        decision = enforcer.check_order(
            symbol="BTC-USD",
            venue="binance",
            account="acct-1",
            quantity=400.0,
            price=1.0,
        )
        assert decision.action == EnforcementAction.WARN
        assert len(decision.breaches) >= 1
        assert any(b.limit_type == "max_venue_position" for b in decision.breaches)

    def test_warn_at_custom_threshold(self):
        lim = PositionLimit(
            max_position=1000,
            max_exposure=100_000,
            max_venue_position=500,
            max_venue_exposure=50_000,
            warn_threshold_pct=50.0,
        )
        enforcer = PositionLimitEnforcer(default_limits=lim)
        decision = enforcer.check_order(
            symbol="BTC-USD",
            venue="binance",
            account="acct-1",
            quantity=250.0,
            price=1.0,
        )
        assert decision.action == EnforcementAction.WARN


# ---------------------------------------------------------------------------
# Test PositionLimitEnforcer — BLOCK cases
# ---------------------------------------------------------------------------

class TestEnforcerBlock:
    def test_block_at_100pct_position(self):
        enforcer = PositionLimitEnforcer(default_limits=_default_limits())
        # max_venue_position=500 → 501 blocks
        decision = enforcer.check_order(
            symbol="BTC-USD",
            venue="binance",
            account="acct-1",
            quantity=501.0,
            price=1.0,
        )
        assert decision.action == EnforcementAction.BLOCK
        assert any(b.limit_type == "max_venue_position" for b in decision.breaches)

    def test_block_at_100pct_exposure(self):
        enforcer = PositionLimitEnforcer(default_limits=_default_limits())
        # max_venue_exposure=50_000, price=1000 → qty=51 gives exposure=51_000
        decision = enforcer.check_order(
            symbol="BTC-USD",
            venue="binance",
            account="acct-1",
            quantity=51.0,
            price=1000.0,
        )
        assert decision.action == EnforcementAction.BLOCK
        assert any(b.limit_type == "max_venue_exposure" for b in decision.breaches)

    def test_block_venue_position(self):
        enforcer = PositionLimitEnforcer(default_limits=_default_limits())
        # max_venue_position=500
        decision = enforcer.check_order(
            symbol="BTC-USD",
            venue="binance",
            account="acct-1",
            quantity=501.0,
            price=1.0,
        )
        assert decision.action == EnforcementAction.BLOCK
        assert any(b.limit_type == "max_venue_position" for b in decision.breaches)

    def test_block_venue_exposure(self):
        enforcer = PositionLimitEnforcer(default_limits=_default_limits())
        # max_venue_exposure=50_000, price=1000 → qty=51 → 51_000
        decision = enforcer.check_order(
            symbol="BTC-USD",
            venue="binance",
            account="acct-1",
            quantity=51.0,
            price=1000.0,
        )
        assert decision.action == EnforcementAction.BLOCK
        assert any(b.limit_type == "max_venue_exposure" for b in decision.breaches)

    def test_block_gross_position(self):
        enforcer = PositionLimitEnforcer(default_limits=_default_limits())
        # Set high per-symbol limits so only gross limit triggers
        high_limits = PositionLimit(
            max_position=10_000.0,
            max_exposure=1_000_000.0,
            max_venue_position=10_000.0,
            max_venue_exposure=1_000_000.0,
            max_gross_position=2_000.0,
            max_gross_exposure=200_000.0,
        )
        enforcer.update_default_limits(high_limits)
        # max_gross_position=2000, two symbols each 1001
        enforcer.update_position("ETH-USD", "coinbase", "acct-1", 1001.0, 1.0)
        decision = enforcer.check_order(
            symbol="BTC-USD",
            venue="binance",
            account="acct-1",
            quantity=1001.0,
            price=1.0,
        )
        assert decision.action == EnforcementAction.BLOCK
        assert any(b.limit_type == "max_gross_position" for b in decision.breaches)

    def test_block_gross_exposure(self):
        enforcer = PositionLimitEnforcer(default_limits=_default_limits())
        # Set high per-symbol limits so only gross limit triggers
        high_limits = PositionLimit(
            max_position=10_000.0,
            max_exposure=1_000_000.0,
            max_venue_position=10_000.0,
            max_venue_exposure=1_000_000.0,
            max_gross_position=2_000.0,
            max_gross_exposure=200_000.0,
        )
        enforcer.update_default_limits(high_limits)
        # max_gross_exposure=200_000, two symbols each 101_000
        enforcer.update_position("ETH-USD", "coinbase", "acct-1", 101.0, 1000.0)
        decision = enforcer.check_order(
            symbol="BTC-USD",
            venue="binance",
            account="acct-1",
            quantity=101.0,
            price=1000.0,
        )
        assert decision.action == EnforcementAction.BLOCK
        assert any(b.limit_type == "max_gross_exposure" for b in decision.breaches)


# ---------------------------------------------------------------------------
# Test PositionLimitEnforcer — HALT cases
# ---------------------------------------------------------------------------

class TestEnforcerHalt:
    def test_halt_at_120pct_position(self):
        enforcer = PositionLimitEnforcer(default_limits=_default_limits())
        # 120% of max_venue_position=500 = 600
        decision = enforcer.check_order(
            symbol="BTC-USD",
            venue="binance",
            account="acct-1",
            quantity=601.0,
            price=1.0,
        )
        assert decision.action == EnforcementAction.HALT
        assert any(b.limit_type == "max_venue_position" for b in decision.breaches)

    def test_halt_takes_precedence_over_block(self):
        enforcer = PositionLimitEnforcer(default_limits=_default_limits())
        # quantity=601 exceeds both block (100%) and halt (120%)
        decision = enforcer.check_order(
            symbol="BTC-USD",
            venue="binance",
            account="acct-1",
            quantity=601.0,
            price=1.0,
        )
        assert decision.action == EnforcementAction.HALT


# ---------------------------------------------------------------------------
# Test per-symbol, per-venue, per-account limits
# ---------------------------------------------------------------------------

class TestPerScopeLimits:
    def test_symbol_limit_overrides_default(self):
        enforcer = PositionLimitEnforcer(default_limits=_default_limits())
        enforcer.set_symbol_limit("BTC-USD", _conservative_limits())
        # BTC-USD has max_venue_position=50, so 51 should block
        decision = enforcer.check_order(
            symbol="BTC-USD",
            venue="binance",
            account="acct-1",
            quantity=51.0,
            price=1.0,
        )
        assert decision.action == EnforcementAction.BLOCK

    def test_symbol_limit_does_not_affect_other_symbols(self):
        enforcer = PositionLimitEnforcer(default_limits=_default_limits())
        enforcer.set_symbol_limit("BTC-USD", _conservative_limits())
        # ETH-USD still uses default max_venue_position=500
        decision = enforcer.check_order(
            symbol="ETH-USD",
            venue="binance",
            account="acct-1",
            quantity=300.0,
            price=1.0,
        )
        assert decision.action == EnforcementAction.PASS

    def test_venue_limit_overrides_default(self):
        enforcer = PositionLimitEnforcer(default_limits=_default_limits())
        enforcer.set_venue_limit("binance", _conservative_limits())
        # binance has max_venue_position=50
        decision = enforcer.check_order(
            symbol="BTC-USD",
            venue="binance",
            account="acct-1",
            quantity=51.0,
            price=1.0,
        )
        assert decision.action == EnforcementAction.BLOCK

    def test_venue_limit_does_not_affect_other_venues(self):
        enforcer = PositionLimitEnforcer(default_limits=_default_limits())
        enforcer.set_venue_limit("binance", _conservative_limits())
        # coinbase still uses default
        decision = enforcer.check_order(
            symbol="BTC-USD",
            venue="coinbase",
            account="acct-1",
            quantity=300.0,
            price=1.0,
        )
        assert decision.action == EnforcementAction.PASS

    def test_account_limit_overrides_default(self):
        enforcer = PositionLimitEnforcer(default_limits=_default_limits())
        enforcer.set_account_limit("acct-1", _conservative_limits())
        decision = enforcer.check_order(
            symbol="BTC-USD",
            venue="binance",
            account="acct-1",
            quantity=51.0,
            price=1.0,
        )
        assert decision.action == EnforcementAction.BLOCK

    def test_account_limit_does_not_affect_other_accounts(self):
        enforcer = PositionLimitEnforcer(default_limits=_default_limits())
        enforcer.set_account_limit("acct-1", _conservative_limits())
        decision = enforcer.check_order(
            symbol="BTC-USD",
            venue="binance",
            account="acct-2",
            quantity=300.0,
            price=1.0,
        )
        assert decision.action == EnforcementAction.PASS

    def test_symbol_limit_takes_priority_over_venue(self):
        enforcer = PositionLimitEnforcer(default_limits=_default_limits())
        enforcer.set_symbol_limit("BTC-USD", _default_limits())
        enforcer.set_venue_limit("binance", _conservative_limits())
        # BTC-USD symbol limit (max_venue_position=500) should win over venue (max_venue_position=50)
        decision = enforcer.check_order(
            symbol="BTC-USD",
            venue="binance",
            account="acct-1",
            quantity=300.0,
            price=1.0,
        )
        assert decision.action == EnforcementAction.PASS

    def test_venue_limit_takes_priority_over_account(self):
        enforcer = PositionLimitEnforcer(default_limits=_default_limits())
        enforcer.set_venue_limit("binance", _default_limits())
        enforcer.set_account_limit("acct-1", _conservative_limits())
        # binance venue limit (max_venue_position=500) should win over account (max_venue_position=50)
        decision = enforcer.check_order(
            symbol="BTC-USD",
            venue="binance",
            account="acct-1",
            quantity=300.0,
            price=1.0,
        )
        assert decision.action == EnforcementAction.PASS


# ---------------------------------------------------------------------------
# Test PositionTracker
# ---------------------------------------------------------------------------

class TestPositionTracker:
    def test_update_and_get_position(self):
        tracker = PositionTracker()
        tracker.update("BTC-USD", "binance", "acct-1", 10.0, 50_000.0)
        pos = tracker.get_position("BTC-USD", "binance", "acct-1")
        assert pos == 10.0

    def test_update_accumulates(self):
        tracker = PositionTracker()
        tracker.update("BTC-USD", "binance", "acct-1", 10.0, 50_000.0)
        tracker.update("BTC-USD", "binance", "acct-1", 5.0, 50_000.0)
        pos = tracker.get_position("BTC-USD", "binance", "acct-1")
        assert pos == 15.0

    def test_get_position_default_zero(self):
        tracker = PositionTracker()
        pos = tracker.get_position("BTC-USD", "binance", "acct-1")
        assert pos == 0.0

    def test_get_exposure(self):
        tracker = PositionTracker()
        tracker.update("BTC-USD", "binance", "acct-1", 10.0, 50_000.0)
        exp = tracker.get_exposure("BTC-USD", "binance", "acct-1")
        assert exp == 500_000.0

    def test_get_gross_position(self):
        tracker = PositionTracker()
        tracker.update("BTC-USD", "binance", "acct-1", 10.0, 50_000.0)
        tracker.update("ETH-USD", "binance", "acct-1", -5.0, 3_000.0)
        gross = tracker.get_gross_position("acct-1")
        assert gross == 15.0

    def test_get_gross_exposure(self):
        tracker = PositionTracker()
        tracker.update("BTC-USD", "binance", "acct-1", 10.0, 50_000.0)
        tracker.update("ETH-USD", "binance", "acct-1", -5.0, 3_000.0)
        gross_exp = tracker.get_gross_exposure("acct-1")
        assert gross_exp == 515_000.0

    def test_get_net_position(self):
        tracker = PositionTracker()
        tracker.update("BTC-USD", "binance", "acct-1", 10.0, 50_000.0)
        tracker.update("ETH-USD", "binance", "acct-1", -5.0, 3_000.0)
        net = tracker.get_net_position("acct-1")
        assert net == 5.0

    def test_get_venue_position(self):
        tracker = PositionTracker()
        tracker.update("BTC-USD", "binance", "acct-1", 10.0, 50_000.0)
        tracker.update("BTC-USD", "coinbase", "acct-1", 5.0, 50_000.0)
        binance_pos = tracker.get_venue_position("binance", "acct-1")
        coinbase_pos = tracker.get_venue_position("coinbase", "acct-1")
        assert binance_pos == 10.0
        assert coinbase_pos == 5.0

    def test_reset(self):
        tracker = PositionTracker()
        tracker.update("BTC-USD", "binance", "acct-1", 10.0, 50_000.0)
        tracker.reset()
        pos = tracker.get_position("BTC-USD", "binance", "acct-1")
        assert pos == 0.0


# ---------------------------------------------------------------------------
# Test LimitUtilizationReporter
# ---------------------------------------------------------------------------

class TestLimitUtilizationReporter:
    def test_generate_report(self):
        enforcer = PositionLimitEnforcer(default_limits=_default_limits())
        enforcer.update_position("BTC-USD", "binance", "acct-1", 500.0, 50_000.0)
        reporter = LimitUtilizationReporter(enforcer)
        report = reporter.generate_report()
        assert isinstance(report, UtilizationReport)
        assert "BTC-USD" in report.symbol_utilization
        assert "binance" in report.venue_utilization

    def test_utilization_pct(self):
        enforcer = PositionLimitEnforcer(default_limits=_default_limits())
        enforcer.update_position("BTC-USD", "binance", "acct-1", 500.0, 50_000.0)
        reporter = LimitUtilizationReporter(enforcer)
        report = reporter.generate_report()
        sym_util = report.symbol_utilization["BTC-USD"]
        assert sym_util["position_utilization_pct"] == 50.0  # 500/1000


# ---------------------------------------------------------------------------
# Test EnforcementDecision and LimitBreach
# ---------------------------------------------------------------------------

class TestEnforcementDecision:
    def test_decision_contains_symbol_venue_account(self):
        enforcer = PositionLimitEnforcer(default_limits=_default_limits())
        decision = enforcer.check_order(
            symbol="BTC-USD",
            venue="binance",
            account="acct-1",
            quantity=10.0,
            price=1.0,
        )
        assert decision.symbol == "BTC-USD"
        assert decision.venue == "binance"
        assert decision.account == "acct-1"

    def test_breach_contains_limit_type_and_values(self):
        enforcer = PositionLimitEnforcer(default_limits=_default_limits())
        decision = enforcer.check_order(
            symbol="BTC-USD",
            venue="binance",
            account="acct-1",
            quantity=501.0,
            price=1.0,
        )
        assert len(decision.breaches) > 0
        breach = decision.breaches[0]
        assert isinstance(breach, LimitBreach)
        assert breach.limit_type == "max_venue_position"
        assert breach.current_value == 501.0
        assert breach.limit_value == 500.0
        assert breach.utilization_pct == 100.2


# ---------------------------------------------------------------------------
# Test dynamic limit updates
# ---------------------------------------------------------------------------

class TestDynamicLimitUpdates:
    def test_update_default_limits(self):
        enforcer = PositionLimitEnforcer(default_limits=_default_limits())
        enforcer.update_default_limits(_conservative_limits())
        decision = enforcer.check_order(
            symbol="BTC-USD",
            venue="binance",
            account="acct-1",
            quantity=51.0,
            price=1.0,
        )
        assert decision.action == EnforcementAction.BLOCK

    def test_remove_symbol_limit(self):
        enforcer = PositionLimitEnforcer(default_limits=_default_limits())
        enforcer.set_symbol_limit("BTC-USD", _conservative_limits())
        enforcer.remove_symbol_limit("BTC-USD")
        # Should fall back to default (max_venue_position=500)
        decision = enforcer.check_order(
            symbol="BTC-USD",
            venue="binance",
            account="acct-1",
            quantity=300.0,
            price=1.0,
        )
        assert decision.action == EnforcementAction.PASS

    def test_remove_venue_limit(self):
        enforcer = PositionLimitEnforcer(default_limits=_default_limits())
        enforcer.set_venue_limit("binance", _conservative_limits())
        enforcer.remove_venue_limit("binance")
        decision = enforcer.check_order(
            symbol="BTC-USD",
            venue="binance",
            account="acct-1",
            quantity=300.0,
            price=1.0,
        )
        assert decision.action == EnforcementAction.PASS

    def test_remove_account_limit(self):
        enforcer = PositionLimitEnforcer(default_limits=_default_limits())
        enforcer.set_account_limit("acct-1", _conservative_limits())
        enforcer.remove_account_limit("acct-1")
        decision = enforcer.check_order(
            symbol="BTC-USD",
            venue="binance",
            account="acct-1",
            quantity=300.0,
            price=1.0,
        )
        assert decision.action == EnforcementAction.PASS


# ---------------------------------------------------------------------------
# Test multiple symbols and venues
# ---------------------------------------------------------------------------

class TestMultipleSymbolsAndVenues:
    def test_independent_symbol_tracking(self):
        enforcer = PositionLimitEnforcer(default_limits=_default_limits())
        enforcer.update_position("BTC-USD", "binance", "acct-1", 100.0, 100.0)
        enforcer.update_position("ETH-USD", "binance", "acct-1", 200.0, 100.0)
        # BTC-USD at 100, ETH-USD at 200 — both under default max_venue_position=500
        decision = enforcer.check_order(
            symbol="BTC-USD",
            venue="binance",
            account="acct-1",
            quantity=50.0,
            price=1.0,
        )
        assert decision.action == EnforcementAction.PASS

    def test_venue_aggregation(self):
        enforcer = PositionLimitEnforcer(default_limits=_default_limits())
        enforcer.update_position("BTC-USD", "binance", "acct-1", 200.0, 100.0)
        enforcer.update_position("BTC-USD", "coinbase", "acct-1", 200.0, 100.0)
        # Each venue at 200, but gross = 400 — still under max_gross_position=2000
        decision = enforcer.check_order(
            symbol="BTC-USD",
            venue="binance",
            account="acct-1",
            quantity=100.0,
            price=1.0,
        )
        assert decision.action == EnforcementAction.PASS


# ---------------------------------------------------------------------------
# Test edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_negative_position_within_limit(self):
        enforcer = PositionLimitEnforcer(default_limits=_default_limits())
        decision = enforcer.check_order(
            symbol="BTC-USD",
            venue="binance",
            account="acct-1",
            quantity=-300.0,
            price=1.0,
        )
        assert decision.action == EnforcementAction.PASS

    def test_negative_position_breach(self):
        enforcer = PositionLimitEnforcer(default_limits=_default_limits())
        decision = enforcer.check_order(
            symbol="BTC-USD",
            venue="binance",
            account="acct-1",
            quantity=-501.0,
            price=1.0,
        )
        assert decision.action == EnforcementAction.BLOCK

    def test_very_small_quantity(self):
        enforcer = PositionLimitEnforcer(default_limits=_default_limits())
        decision = enforcer.check_order(
            symbol="BTC-USD",
            venue="binance",
            account="acct-1",
            quantity=0.001,
            price=1.0,
        )
        assert decision.action == EnforcementAction.PASS

    def test_exactly_at_limit(self):
        enforcer = PositionLimitEnforcer(default_limits=_default_limits())
        # Exactly at max_venue_position=500 → utilization=100% → BLOCK
        decision = enforcer.check_order(
            symbol="BTC-USD",
            venue="binance",
            account="acct-1",
            quantity=500.0,
            price=1.0,
        )
        assert decision.action == EnforcementAction.BLOCK

    def test_exactly_at_warn_threshold(self):
        enforcer = PositionLimitEnforcer(default_limits=_default_limits())
        # Exactly 80% of max_venue_position=500 = 400 → WARN
        decision = enforcer.check_order(
            symbol="BTC-USD",
            venue="binance",
            account="acct-1",
            quantity=400.0,
            price=1.0,
        )
        assert decision.action == EnforcementAction.WARN

    def test_exactly_at_halt_threshold(self):
        enforcer = PositionLimitEnforcer(default_limits=_default_limits())
        # Exactly 120% of max_venue_position=500 = 600 → HALT
        decision = enforcer.check_order(
            symbol="BTC-USD",
            venue="binance",
            account="acct-1",
            quantity=600.0,
            price=1.0,
        )
        assert decision.action == EnforcementAction.HALT
