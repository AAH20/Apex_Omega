"""Tests for Defense C2 F2T2EA Kill Chain Core.

Covers: Find-Fix-Track-Target-Engage-Assess phases, sensor-to-shooter
latency optimization, and human governance controls.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum, auto
from typing import Optional

import pytest

from src.c2.f2t2ea import (
    AssessmentResult,
    EngagementOutcome,
    EngagementResult,
    F2T2EAChain,
    F2T2EAConfig,
    F2T2EAError,
    F2T2EAPhase,
    F2T2EAState,
    HumanDecision,
    HumanGovernance,
    HumanGovernanceError,
    KillChainStatus,
    LatencyBudget,
    LatencyOptimizer,
    SensorReading,
    SensorToShooterLink,
    Shooter,
    Target,
    ThreatLevel,
    Track,
)


# ---------------------------------------------------------------------------
# Phase Enum & State Machine Tests
# ---------------------------------------------------------------------------


class TestF2T2EAPhases:
    def test_phase_ordering(self):
        phases = list(F2T2EAPhase)
        assert phases == [
            F2T2EAPhase.FIND,
            F2T2EAPhase.FIX,
            F2T2EAPhase.TRACK,
            F2T2EAPhase.TARGET,
            F2T2EAPhase.ENGAGE,
            F2T2EAPhase.ASSESS,
        ]

    def test_phase_transitions_valid(self):
        assert F2T2EAPhase.FIND.next() == F2T2EAPhase.FIX
        assert F2T2EAPhase.FIX.next() == F2T2EAPhase.TRACK
        assert F2T2EAPhase.TRACK.next() == F2T2EAPhase.TARGET
        assert F2T2EAPhase.TARGET.next() == F2T2EAPhase.ENGAGE
        assert F2T2EAPhase.ENGAGE.next() == F2T2EAPhase.ASSESS

    def test_phase_last_has_no_next(self):
        assert F2T2EAPhase.ASSESS.next() is None

    def test_phase_from_string(self):
        assert F2T2EAPhase("find") == F2T2EAPhase.FIND
        assert F2T2EAPhase("engage") == F2T2EAPhase.ENGAGE


# ---------------------------------------------------------------------------
# Find Phase Tests
# ---------------------------------------------------------------------------


class TestFindPhase:
    def test_find_detects_threat(self):
        chain = F2T2EAChain()
        reading = SensorReading(
            sensor_id="radar-01",
            timestamp=datetime.now(timezone.utc),
            location=(34.05, -118.25),
            confidence=0.85,
            classification="hostile-aircraft",
        )
        chain.submit_sensor_reading(reading)
        assert chain.state.current_phase == F2T2EAPhase.FIND
        assert chain.state.threat_level == ThreatLevel.HIGH

    def test_find_ignores_low_confidence(self):
        chain = F2T2EAChain()
        reading = SensorReading(
            sensor_id="radar-01",
            timestamp=datetime.now(timezone.utc),
            location=(34.05, -118.25),
            confidence=0.3,
            classification="unknown",
        )
        chain.submit_sensor_reading(reading)
        assert chain.state.threat_level == ThreatLevel.LOW

    def test_find_escalates_threat_level(self):
        chain = F2T2EAChain()
        for i in range(5):
            reading = SensorReading(
                sensor_id=f"radar-{i}",
                timestamp=datetime.now(timezone.utc),
                location=(34.05 + i * 0.01, -118.25),
                confidence=0.9,
                classification="hostile-aircraft",
            )
            chain.submit_sensor_reading(reading)
        assert chain.state.threat_level == ThreatLevel.CRITICAL

    def test_find_advances_to_fix_when_confirmed(self):
        chain = F2T2EAChain()
        reading = SensorReading(
            sensor_id="radar-01",
            timestamp=datetime.now(timezone.utc),
            location=(34.05, -118.25),
            confidence=0.95,
            classification="hostile-aircraft",
        )
        chain.submit_sensor_reading(reading)
        chain.confirm_find()
        assert chain.state.current_phase == F2T2EAPhase.FIX


# ---------------------------------------------------------------------------
# Fix Phase Tests
# ---------------------------------------------------------------------------


class TestFixPhase:
    def test_fix_creates_target(self):
        chain = F2T2EAChain()
        chain.advance_to(F2T2EAPhase.FIX)
        target = chain.fix_target(
            location=(34.05, -118.25),
            target_id="TGT-001",
            classification="hostile-aircraft",
        )
        assert target.target_id == "TGT-001"
        assert target.location == (34.05, -118.25)
        assert chain.state.current_phase == F2T2EAPhase.FIX

    def test_fix_requires_coordinates(self):
        chain = F2T2EAChain()
        chain.advance_to(F2T2EAPhase.FIX)
        with pytest.raises(F2T2EAError):
            chain.fix_target(
                location=None,
                target_id="TGT-001",
                classification="hostile-aircraft",
            )

    def test_fix_advances_to_track(self):
        chain = F2T2EAChain()
        chain.advance_to(F2T2EAPhase.FIX)
        chain.fix_target(
            location=(34.05, -118.25),
            target_id="TGT-001",
            classification="hostile-aircraft",
        )
        chain.confirm_fix()
        assert chain.state.current_phase == F2T2EAPhase.TRACK


# ---------------------------------------------------------------------------
# Track Phase Tests
# ---------------------------------------------------------------------------


class TestTrackPhase:
    def test_track_creates_track(self):
        chain = F2T2EAChain()
        chain.advance_to(F2T2EAPhase.TRACK)
        track = chain.start_tracking(
            target_id="TGT-001",
            track_id="TRK-001",
        )
        assert track.track_id == "TRK-001"
        assert track.target_id == "TGT-001"

    def test_track_updates_position(self):
        chain = F2T2EAChain()
        chain.advance_to(F2T2EAPhase.TRACK)
        chain.start_tracking(target_id="TGT-001", track_id="TRK-001")
        chain.update_track("TRK-001", (34.06, -118.26))
        track = chain.get_track("TRK-001")
        assert track.latest_position == (34.06, -118.26)

    def test_track_degrades_after_timeout(self):
        chain = F2T2EAChain()
        chain.advance_to(F2T2EAPhase.TRACK)
        chain.start_tracking(target_id="TGT-001", track_id="TRK-001")
        # Simulate stale track by setting last update to past
        chain._tracks["TRK-001"].last_update = datetime.now(timezone.utc) - timedelta(seconds=30)
        assert chain.get_track("TRK-001").is_stale(timeout_seconds=10)

    def test_track_advances_to_target(self):
        chain = F2T2EAChain()
        chain.advance_to(F2T2EAPhase.TRACK)
        chain.start_tracking(target_id="TGT-001", track_id="TRK-001")
        chain.confirm_track()
        assert chain.state.current_phase == F2T2EAPhase.TARGET


# ---------------------------------------------------------------------------
# Target Phase Tests
# ---------------------------------------------------------------------------


class TestTargetPhase:
    def test_target_prioritizes_by_threat(self):
        chain = F2T2EAChain()
        chain.advance_to(F2T2EAPhase.TARGET)
        chain.add_target(Target(target_id="TGT-001", location=(34.0, -118.0), threat_level=ThreatLevel.HIGH))
        chain.add_target(Target(target_id="TGT-002", location=(35.0, -119.0), threat_level=ThreatLevel.CRITICAL))
        chain.add_target(Target(target_id="TGT-003", location=(36.0, -120.0), threat_level=ThreatLevel.LOW))
        prioritized = chain.prioritize_targets()
        assert prioritized[0].target_id == "TGT-002"
        assert prioritized[1].target_id == "TGT-001"
        assert prioritized[2].target_id == "TGT-003"

    def test_target_selects_engagement(self):
        chain = F2T2EAChain()
        chain.advance_to(F2T2EAPhase.TARGET)
        chain.add_target(Target(target_id="TGT-001", location=(34.0, -118.0), threat_level=ThreatLevel.HIGH))
        engagement = chain.select_engagement("TGT-001")
        assert engagement.target_id == "TGT-001"
        assert chain.state.current_phase == F2T2EAPhase.TARGET

    def test_target_advances_to_engage(self):
        chain = F2T2EAChain()
        chain.advance_to(F2T2EAPhase.TARGET)
        chain.add_target(Target(target_id="TGT-001", location=(34.0, -118.0), threat_level=ThreatLevel.HIGH))
        chain.select_engagement("TGT-001")
        chain.confirm_target()
        assert chain.state.current_phase == F2T2EAPhase.ENGAGE


# ---------------------------------------------------------------------------
# Engage Phase Tests
# ---------------------------------------------------------------------------


class TestEngagePhase:
    def test_engage_records_outcome(self):
        chain = F2T2EAChain()
        chain.advance_to(F2T2EAPhase.ENGAGE)
        chain.add_target(Target(target_id="TGT-001", location=(34.0, -118.0), threat_level=ThreatLevel.HIGH))
        result = chain.engage(
            target_id="TGT-001",
            shooter_id="SHK-001",
            outcome=EngagementOutcome.SUCCESS,
        )
        assert result.target_id == "TGT-001"
        assert result.outcome == EngagementOutcome.SUCCESS
        assert result.shooter_id == "SHK-001"

    def test_engage_marks_target_destroyed(self):
        chain = F2T2EAChain()
        chain.advance_to(F2T2EAPhase.ENGAGE)
        chain.add_target(Target(target_id="TGT-001", location=(34.0, -118.0), threat_level=ThreatLevel.HIGH))
        chain.engage(
            target_id="TGT-001",
            shooter_id="SHK-001",
            outcome=EngagementOutcome.SUCCESS,
        )
        assert chain.get_target("TGT-001").destroyed is True

    def test_engage_advances_to_assess(self):
        chain = F2T2EAChain()
        chain.advance_to(F2T2EAPhase.ENGAGE)
        chain.add_target(Target(target_id="TGT-001", location=(34.0, -118.0), threat_level=ThreatLevel.HIGH))
        chain.engage(
            target_id="TGT-001",
            shooter_id="SHK-001",
            outcome=EngagementOutcome.SUCCESS,
        )
        chain.confirm_engage()
        assert chain.state.current_phase == F2T2EAPhase.ASSESS


# ---------------------------------------------------------------------------
# Assess Phase Tests
# ---------------------------------------------------------------------------


class TestAssessPhase:
    def test_assess_records_result(self):
        chain = F2T2EAChain()
        chain.advance_to(F2T2EAPhase.ASSESS)
        result = chain.assess(
            target_id="TGT-001",
            effectiveness=0.9,
            collateral_damage=False,
        )
        assert result.target_id == "TGT-001"
        assert result.effectiveness == 0.9
        assert result.collateral_damage is False

    def test_assess_completes_kill_chain(self):
        chain = F2T2EAChain()
        chain.advance_to(F2T2EAPhase.ASSESS)
        chain.assess(target_id="TGT-001", effectiveness=0.9, collateral_damage=False)
        chain.confirm_assess()
        assert chain.state.status == KillChainStatus.COMPLETE

    def test_assess_detects_re_engagement_need(self):
        chain = F2T2EAChain()
        chain.advance_to(F2T2EAPhase.ASSESS)
        result = chain.assess(
            target_id="TGT-001",
            effectiveness=0.3,
            collateral_damage=False,
        )
        assert result.requires_re_engagement is True


# ---------------------------------------------------------------------------
# Human Governance Tests
# ---------------------------------------------------------------------------


class TestHumanGovernance:
    def test_governance_requires_authorization_for_engagement(self):
        gov = HumanGovernance()
        chain = F2T2EAChain(governance=gov)
        chain.advance_to(F2T2EAPhase.ENGAGE)
        with pytest.raises(HumanGovernanceError):
            chain.engage(
                target_id="TGT-001",
                shooter_id="SHK-001",
                outcome=EngagementOutcome.SUCCESS,
            )

    def test_governance_allows_engagement_with_authorization(self):
        gov = HumanGovernance()
        gov.authorize(
            decision_type=HumanDecision.ENGAGE,
            authorizer_id="commander-01",
            target_id="TGT-001",
        )
        chain = F2T2EAChain(governance=gov)
        chain.advance_to(F2T2EAPhase.ENGAGE)
        result = chain.engage(
            target_id="TGT-001",
            shooter_id="SHK-001",
            outcome=EngagementOutcome.SUCCESS,
        )
        assert result.outcome == EngagementOutcome.SUCCESS

    def test_governance_veto_blocks_engagement(self):
        gov = HumanGovernance()
        gov.veto(
            decision_type=HumanDecision.ENGAGE,
            vetoer_id="commander-01",
            target_id="TGT-001",
        )
        chain = F2T2EAChain(governance=gov)
        chain.advance_to(F2T2EAPhase.ENGAGE)
        with pytest.raises(HumanGovernanceError):
            chain.engage(
                target_id="TGT-001",
                shooter_id="SHK-001",
                outcome=EngagementOutcome.SUCCESS,
            )

    def test_governance_authorization_expires(self):
        gov = HumanGovernance()
        gov.authorize(
            decision_type=HumanDecision.ENGAGE,
            authorizer_id="commander-01",
            target_id="TGT-001",
            ttl_seconds=1,
        )
        time.sleep(1.1)
        assert not gov.is_authorized(HumanDecision.ENGAGE, "TGT-001")

    def test_governance_audit_trail(self):
        gov = HumanGovernance()
        gov.authorize(
            decision_type=HumanDecision.ENGAGE,
            authorizer_id="commander-01",
            target_id="TGT-001",
        )
        trail = gov.get_audit_trail()
        assert len(trail) == 1
        assert trail[0].decision_type == HumanDecision.ENGAGE
        assert trail[0].actor_id == "commander-01"

    def test_governance_requires_dual_authorization_for_critical(self):
        gov = HumanGovernance(require_dual_for_critical=True)
        gov.authorize(
            decision_type=HumanDecision.ENGAGE,
            authorizer_id="commander-01",
            target_id="TGT-001",
        )
        # Only one authorization — should not be authorized for critical target
        assert not gov.is_authorized(HumanDecision.ENGAGE, "TGT-001", threat_level=ThreatLevel.CRITICAL)

    def test_governance_dual_authorization_sufficient(self):
        gov = HumanGovernance(require_dual_for_critical=True)
        gov.authorize(
            decision_type=HumanDecision.ENGAGE,
            authorizer_id="commander-01",
            target_id="TGT-001",
        )
        gov.authorize(
            decision_type=HumanDecision.ENGAGE,
            authorizer_id="commander-02",
            target_id="TGT-001",
        )
        assert gov.is_authorized(HumanDecision.ENGAGE, "TGT-001", threat_level=ThreatLevel.CRITICAL)


# ---------------------------------------------------------------------------
# Sensor-to-Shooter Latency Optimization Tests
# ---------------------------------------------------------------------------


class TestLatencyOptimizer:
    def test_latency_budget_tracks_phases(self):
        budget = LatencyBudget()
        budget.record(F2T2EAPhase.FIND, 0.5)
        budget.record(F2T2EAPhase.FIX, 0.3)
        budget.record(F2T2EAPhase.TRACK, 0.2)
        assert budget.total() == pytest.approx(1.0)

    def test_latency_budget_exceeds_threshold(self):
        budget = LatencyBudget(threshold_ms=500)
        budget.record(F2T2EAPhase.FIND, 0.6)
        assert budget.is_exceeded() is True

    def test_latency_budget_within_threshold(self):
        budget = LatencyBudget(threshold_ms=500)
        budget.record(F2T2EAPhase.FIND, 0.3)
        assert budget.is_exceeded() is False

    def test_optimizer_selects_fastest_shooter(self):
        optimizer = LatencyOptimizer()
        optimizer.register_shooter(Shooter(shooter_id="SHK-001", latency_ms=100))
        optimizer.register_shooter(Shooter(shooter_id="SHK-002", latency_ms=50))
        optimizer.register_shooter(Shooter(shooter_id="SHK-003", latency_ms=200))
        best = optimizer.select_shooter()
        assert best.shooter_id == "SHK-002"

    def test_optimizer_filters_by_capability(self):
        optimizer = LatencyOptimizer()
        optimizer.register_shooter(
            Shooter(shooter_id="SHK-001", latency_ms=100, capabilities={"air"})
        )
        optimizer.register_shooter(
            Shooter(shooter_id="SHK-002", latency_ms=50, capabilities={"ground"})
        )
        best = optimizer.select_shooter(required_capability="air")
        assert best.shooter_id == "SHK-001"

    def test_optimizer_no_shooter_available(self):
        optimizer = LatencyOptimizer()
        with pytest.raises(F2T2EAError):
            optimizer.select_shooter()

    def test_sensor_to_shooter_link_creation(self):
        link = SensorToShooterLink(
            sensor_id="radar-01",
            shooter_id="SHK-001",
            latency_ms=75,
        )
        assert link.sensor_id == "radar-01"
        assert link.shooter_id == "SHK-001"
        assert link.latency_ms == 75

    def test_optimizer_updates_shooter_latency(self):
        optimizer = LatencyOptimizer()
        optimizer.register_shooter(Shooter(shooter_id="SHK-001", latency_ms=100))
        optimizer.update_latency("SHK-001", 45)
        assert optimizer.select_shooter().latency_ms == 45


# ---------------------------------------------------------------------------
# Full Kill Chain Integration Tests
# ---------------------------------------------------------------------------


class TestFullKillChain:
    def test_complete_kill_chain_flow(self):
        chain = F2T2EAChain()
        # Find
        chain.submit_sensor_reading(
            SensorReading(
                sensor_id="radar-01",
                timestamp=datetime.now(timezone.utc),
                location=(34.05, -118.25),
                confidence=0.95,
                classification="hostile-aircraft",
            )
        )
        chain.confirm_find()
        # Fix
        chain.fix_target(
            location=(34.05, -118.25),
            target_id="TGT-001",
            classification="hostile-aircraft",
        )
        chain.confirm_fix()
        # Track
        chain.start_tracking(target_id="TGT-001", track_id="TRK-001")
        chain.confirm_track()
        # Target
        chain.add_target(
            Target(target_id="TGT-001", location=(34.05, -118.25), threat_level=ThreatLevel.HIGH)
        )
        chain.select_engagement("TGT-001")
        chain.confirm_target()
        # Engage
        chain.engage(
            target_id="TGT-001",
            shooter_id="SHK-001",
            outcome=EngagementOutcome.SUCCESS,
        )
        chain.confirm_engage()
        # Assess
        chain.assess(target_id="TGT-001", effectiveness=0.9, collateral_damage=False)
        chain.confirm_assess()
        assert chain.state.status == KillChainStatus.COMPLETE

    def test_kill_chain_can_restart_after_assess(self):
        chain = F2T2EAChain()
        chain.advance_to(F2T2EAPhase.ASSESS)
        chain.assess(target_id="TGT-001", effectiveness=0.3, collateral_damage=False)
        chain.confirm_assess()
        assert chain.state.status == KillChainStatus.COMPLETE
        chain.restart()
        assert chain.state.current_phase == F2T2EAPhase.FIND
        assert chain.state.status == KillChainStatus.ACTIVE

    def test_kill_chain_cannot_skip_phases(self):
        chain = F2T2EAChain()
        with pytest.raises(F2T2EAError):
            chain.confirm_engage()

    def test_kill_chain_cannot_revisit_completed_phase(self):
        chain = F2T2EAChain()
        chain.advance_to(F2T2EAPhase.FIX)
        with pytest.raises(F2T2EAError):
            chain.advance_to(F2T2EAPhase.FIND)


# ---------------------------------------------------------------------------
# Configuration Tests
# ---------------------------------------------------------------------------


class TestF2T2EAConfig:
    def test_default_config(self):
        config = F2T2EAConfig()
        assert config.max_latency_ms == 5000
        assert config.require_human_authorization is True
        assert config.auto_advance is False

    def test_custom_config(self):
        config = F2T2EAConfig(
            max_latency_ms=1000,
            require_human_authorization=False,
            auto_advance=True,
        )
        assert config.max_latency_ms == 1000
        assert config.require_human_authorization is False
        assert config.auto_advance is True

    def test_config_validates_latency(self):
        with pytest.raises(ValueError):
            F2T2EAConfig(max_latency_ms=-1)


# ---------------------------------------------------------------------------
# State Query Tests
# ---------------------------------------------------------------------------


class TestF2T2EAState:
    def test_state_tracks_history(self):
        chain = F2T2EAChain()
        chain.advance_to(F2T2EAPhase.FIX)
        chain.advance_to(F2T2EAPhase.TRACK)
        assert len(chain.state.history) >= 2

    def test_state_get_elapsed_time(self):
        chain = F2T2EAChain()
        elapsed = chain.state.elapsed_seconds()
        assert elapsed >= 0

    def test_state_is_terminal(self):
        chain = F2T2EAChain()
        assert chain.state.is_terminal() is False
        chain._state.status = KillChainStatus.COMPLETE
        assert chain.state.is_terminal() is True


# ---------------------------------------------------------------------------
# Edge Case Tests
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_empty_sensor_reading_list(self):
        chain = F2T2EAChain()
        assert chain.state.threat_level == ThreatLevel.LOW

    def test_duplicate_target_id_raises(self):
        chain = F2T2EAChain()
        chain.advance_to(F2T2EAPhase.TARGET)
        chain.add_target(Target(target_id="TGT-001", location=(34.0, -118.0), threat_level=ThreatLevel.HIGH))
        with pytest.raises(F2T2EAError):
            chain.add_target(Target(target_id="TGT-001", location=(35.0, -119.0), threat_level=ThreatLevel.LOW))

    def test_engage_nonexistent_target_raises(self):
        chain = F2T2EAChain()
        chain.advance_to(F2T2EAPhase.ENGAGE)
        with pytest.raises(F2T2EAError):
            chain.engage(
                target_id="NONEXISTENT",
                shooter_id="SHK-001",
                outcome=EngagementOutcome.SUCCESS,
            )

    def test_assess_effectiveness_bounds(self):
        chain = F2T2EAChain()
        chain.advance_to(F2T2EAPhase.ASSESS)
        with pytest.raises(ValueError):
            chain.assess(target_id="TGT-001", effectiveness=1.5, collateral_damage=False)

    def test_track_update_nonexistent_raises(self):
        chain = F2T2EAChain()
        chain.advance_to(F2T2EAPhase.TRACK)
        with pytest.raises(F2T2EAError):
            chain.update_track("NONEXISTENT", (34.0, -118.0))

    def test_governance_veto_expires(self):
        gov = HumanGovernance()
        gov.veto(
            decision_type=HumanDecision.ENGAGE,
            vetoer_id="commander-01",
            target_id="TGT-001",
            ttl_seconds=1,
        )
        time.sleep(1.1)
        assert not gov.is_vetoed(HumanDecision.ENGAGE, "TGT-001")

    def test_multiple_sensor_fusion(self):
        chain = F2T2EAChain()
        for i in range(3):
            chain.submit_sensor_reading(
                SensorReading(
                    sensor_id=f"sensor-{i}",
                    timestamp=datetime.now(timezone.utc),
                    location=(34.0 + i * 0.01, -118.0),
                    confidence=0.7 + i * 0.1,
                    classification="hostile-aircraft",
                )
            )
        # Multiple readings should increase threat level
        assert chain.state.threat_level >= ThreatLevel.MEDIUM

    def test_kill_chain_abort(self):
        chain = F2T2EAChain()
        chain.advance_to(F2T2EAPhase.FIX)
        chain.abort()
        assert chain.state.status == KillChainStatus.ABORTED

    def test_kill_chain_abort_requires_reason(self):
        chain = F2T2EAChain()
        with pytest.raises(F2T2EAError):
            chain.abort()

    def test_latency_budget_phase_breakdown(self):
        budget = LatencyBudget()
        budget.record(F2T2EAPhase.FIND, 0.5)
        budget.record(F2T2EAPhase.FIX, 0.3)
        breakdown = budget.phase_breakdown()
        assert breakdown[F2T2EAPhase.FIND] == pytest.approx(0.5)
        assert breakdown[F2T2EAPhase.FIX] == pytest.approx(0.3)

    def test_optimizer_shooter_capability_match(self):
        optimizer = LatencyOptimizer()
        optimizer.register_shooter(
            Shooter(shooter_id="SHK-001", latency_ms=100, capabilities={"air", "sea"})
        )
        optimizer.register_shooter(
            Shooter(shooter_id="SHK-002", latency_ms=50, capabilities={"air"})
        )
        best = optimizer.select_shooter(required_capability="sea")
        assert best.shooter_id == "SHK-001"

    def test_human_governance_override_chain(self):
        gov = HumanGovernance()
        gov.authorize(
            decision_type=HumanDecision.ENGAGE,
            authorizer_id="commander-01",
            target_id="TGT-001",
        )
        chain = F2T2EAChain(governance=gov)
        chain.advance_to(F2T2EAPhase.ENGAGE)
        # Should not raise — authorization exists
        chain.engage(
            target_id="TGT-001",
            shooter_id="SHK-001",
            outcome=EngagementOutcome.SUCCESS,
        )
        assert chain.state.current_phase == F2T2EAPhase.ENGAGE
