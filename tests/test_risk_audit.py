"""Tests for Risk Audit Trail — TDD: written before implementation.

Regulatory compliance logging for MiFID II RTS 6.
All risk decisions must be logged with tamper-evident hash chain.
"""
import json
import pytest
from datetime import datetime, timedelta
from pathlib import Path

from src.risk.audit import AuditEntry, RiskAuditTrail


# ---------------------------------------------------------------------------
# AuditEntry tests
# ---------------------------------------------------------------------------


class TestAuditEntry:
    def test_entry_has_required_fields(self):
        entry = AuditEntry(
            timestamp=datetime(2026, 10, 1, 12, 0, 0),
            decision_id="dec-001",
            actor="trader-1",
            action="KILL_SWITCH",
            reason="Anomalous drawdown detected",
            metadata={"venue": "BINANCE", "drawdown_pct": 15.2},
            entry_hash="abc123",
        )
        assert entry.decision_id == "dec-001"
        assert entry.actor == "trader-1"
        assert entry.action == "KILL_SWITCH"
        assert entry.reason == "Anomalous drawdown detected"
        assert entry.metadata["venue"] == "BINANCE"
        assert entry.entry_hash == "abc123"

    def test_entry_metadata_defaults_to_empty_dict(self):
        entry = AuditEntry(
            timestamp=datetime(2026, 10, 1, 12, 0, 0),
            decision_id="dec-002",
            actor="system",
            action="PRE_TRADE_CHECK",
            reason="Order within limits",
            metadata=None,
            entry_hash="def456",
        )
        assert entry.metadata == {}

    def test_entry_to_dict(self):
        entry = AuditEntry(
            timestamp=datetime(2026, 10, 1, 12, 0, 0),
            decision_id="dec-003",
            actor="risk-engine",
            action="OTR_ALERT",
            reason="OTR at 80% of threshold",
            metadata={"symbol": "BTCUSDT", "otr": 8000, "threshold": 10000},
            entry_hash="ghi789",
        )
        d = entry.to_dict()
        assert d["decision_id"] == "dec-003"
        assert d["actor"] == "risk-engine"
        assert d["action"] == "OTR_ALERT"
        assert d["metadata"]["symbol"] == "BTCUSDT"

    def test_entry_to_dict_serializes_timestamp(self):
        entry = AuditEntry(
            timestamp=datetime(2026, 10, 1, 12, 0, 0),
            decision_id="dec-004",
            actor="system",
            action="LOG",
            reason="test",
            metadata={},
            entry_hash="jkl012",
        )
        d = entry.to_dict()
        assert isinstance(d["timestamp"], str)
        assert "2026-10-01" in d["timestamp"]


# ---------------------------------------------------------------------------
# RiskAuditTrail — basic logging
# ---------------------------------------------------------------------------


class TestRiskAuditTrailBasic:
    def test_trail_initializes_empty(self):
        trail = RiskAuditTrail()
        assert trail.get_entries() == []

    def test_log_decision_creates_entry(self):
        trail = RiskAuditTrail()
        entry = trail.log_decision(
            actor="trader-1",
            action="ORDER_REJECT",
            reason="Price collar breached",
            metadata={"symbol": "AAPL", "price": 200.0, "collar": 195.0},
        )
        assert entry.decision_id is not None
        assert entry.actor == "trader-1"
        assert entry.action == "ORDER_REJECT"
        assert entry.entry_hash is not None

    def test_log_decision_increments_entries(self):
        trail = RiskAuditTrail()
        trail.log_decision(actor="t1", action="A1", reason="r1")
        trail.log_decision(actor="t2", action="A2", reason="r2")
        assert len(trail.get_entries()) == 2

    def test_entries_have_unique_decision_ids(self):
        trail = RiskAuditTrail()
        e1 = trail.log_decision(actor="t1", action="A1", reason="r1")
        e2 = trail.log_decision(actor="t2", action="A2", reason="r2")
        assert e1.decision_id != e2.decision_id

    def test_entries_have_sequential_hashes(self):
        trail = RiskAuditTrail()
        e1 = trail.log_decision(actor="t1", action="A1", reason="r1")
        e2 = trail.log_decision(actor="t2", action="A2", reason="r2")
        # Hash chain: e2's hash should incorporate e1's hash
        assert e1.entry_hash != e2.entry_hash


# ---------------------------------------------------------------------------
# RiskAuditTrail — kill switch logging
# ---------------------------------------------------------------------------


class TestKillSwitchLogging:
    def test_log_kill_switch(self):
        trail = RiskAuditTrail()
        entry = trail.log_kill_switch(
            actor="risk-manager-1",
            reason="Manual kill — anomalous behaviour detected",
            venues=["BINANCE", "COINBASE", "KRAKEN"],
        )
        assert entry.action == "KILL_SWITCH"
        assert entry.actor == "risk-manager-1"
        assert "Manual kill" in entry.reason
        assert entry.metadata["venues"] == ["BINANCE", "COINBASE", "KRAKEN"]
        assert entry.metadata["trigger_type"] == "manual"

    def test_log_kill_switch_automatic(self):
        trail = RiskAuditTrail()
        entry = trail.log_kill_switch(
            actor="system",
            reason="Automatic kill — drawdown limit breached",
            venues=["BINANCE"],
            trigger_type="automatic",
        )
        assert entry.metadata["trigger_type"] == "automatic"
        assert entry.metadata["venues"] == ["BINANCE"]

    def test_kill_switch_entries_are_in_trail(self):
        trail = RiskAuditTrail()
        trail.log_kill_switch(actor="rm-1", reason="test", venues=["V1"])
        entries = trail.get_entries()
        assert len(entries) == 1
        assert entries[0].action == "KILL_SWITCH"


# ---------------------------------------------------------------------------
# RiskAuditTrail — pre-trade check logging
# ---------------------------------------------------------------------------


class TestPreTradeCheckLogging:
    def test_log_pre_trade_check_pass(self):
        trail = RiskAuditTrail()
        entry = trail.log_pre_trade_check(
            order_id="ord-001",
            decision="PASS",
            checks={"price_collar": "PASS", "max_order_value": "PASS", "message_limit": "PASS"},
        )
        assert entry.action == "PRE_TRADE_CHECK"
        assert entry.metadata["order_id"] == "ord-001"
        assert entry.metadata["decision"] == "PASS"
        assert entry.metadata["checks"]["price_collar"] == "PASS"

    def test_log_pre_trade_check_fail(self):
        trail = RiskAuditTrail()
        entry = trail.log_pre_trade_check(
            order_id="ord-002",
            decision="FAIL",
            checks={"price_collar": "FAIL", "max_order_value": "PASS"},
        )
        assert entry.metadata["decision"] == "FAIL"
        assert entry.metadata["checks"]["price_collar"] == "FAIL"

    def test_pre_trade_check_entries_are_in_trail(self):
        trail = RiskAuditTrail()
        trail.log_pre_trade_check(order_id="ord-003", decision="PASS", checks={})
        entries = trail.get_entries()
        assert len(entries) == 1
        assert entries[0].action == "PRE_TRADE_CHECK"


# ---------------------------------------------------------------------------
# RiskAuditTrail — OTR alert logging
# ---------------------------------------------------------------------------


class TestOTRAlertLogging:
    def test_log_otr_alert(self):
        trail = RiskAuditTrail()
        entry = trail.log_otr_alert(
            venue="BINANCE",
            symbol="BTCUSDT",
            otr_value=8500,
            threshold=10000,
        )
        assert entry.action == "OTR_ALERT"
        assert entry.metadata["venue"] == "BINANCE"
        assert entry.metadata["symbol"] == "BTCUSDT"
        assert entry.metadata["otr_value"] == 8500
        assert entry.metadata["threshold"] == 10000
        assert entry.metadata["utilization_pct"] == 85.0

    def test_log_otr_alert_entries_are_in_trail(self):
        trail = RiskAuditTrail()
        trail.log_otr_alert(venue="KRAKEN", symbol="ETHUSD", otr_value=500, threshold=2000)
        entries = trail.get_entries()
        assert len(entries) == 1
        assert entries[0].action == "OTR_ALERT"


# ---------------------------------------------------------------------------
# RiskAuditTrail — query and filter
# ---------------------------------------------------------------------------


class TestRiskAuditTrailQuery:
    def test_filter_by_actor(self):
        trail = RiskAuditTrail()
        trail.log_decision(actor="trader-1", action="A1", reason="r1")
        trail.log_decision(actor="trader-2", action="A2", reason="r2")
        trail.log_decision(actor="trader-1", action="A3", reason="r3")
        entries = trail.get_entries(actor="trader-1")
        assert len(entries) == 2
        assert all(e.actor == "trader-1" for e in entries)

    def test_filter_by_action(self):
        trail = RiskAuditTrail()
        trail.log_decision(actor="t1", action="KILL_SWITCH", reason="r1")
        trail.log_decision(actor="t2", action="ORDER_REJECT", reason="r2")
        trail.log_decision(actor="t3", action="KILL_SWITCH", reason="r3")
        entries = trail.get_entries(action="KILL_SWITCH")
        assert len(entries) == 2
        assert all(e.action == "KILL_SWITCH" for e in entries)

    def test_filter_by_time_range(self):
        trail = RiskAuditTrail()
        # Manually create entries with specific timestamps
        now = datetime.utcnow()
        old = now - timedelta(hours=2)
        recent = now - timedelta(minutes=30)

        trail.log_decision(actor="t1", action="A1", reason="old")
        # Manually override timestamp for testing
        trail._entries[-1].timestamp = old

        trail.log_decision(actor="t2", action="A2", reason="recent")
        trail._entries[-1].timestamp = recent

        entries = trail.get_entries(start=now - timedelta(hours=1))
        assert len(entries) == 1
        assert entries[0].actor == "t2"

    def test_filter_by_time_range_end(self):
        trail = RiskAuditTrail()
        now = datetime.utcnow()
        old = now - timedelta(hours=2)

        trail.log_decision(actor="t1", action="A1", reason="old")
        trail._entries[-1].timestamp = old

        trail.log_decision(actor="t2", action="A2", reason="recent")

        entries = trail.get_entries(end=now - timedelta(hours=1))
        assert len(entries) == 1
        assert entries[0].actor == "t1"

    def test_no_filter_returns_all(self):
        trail = RiskAuditTrail()
        trail.log_decision(actor="t1", action="A1", reason="r1")
        trail.log_decision(actor="t2", action="A2", reason="r2")
        assert len(trail.get_entries()) == 2


# ---------------------------------------------------------------------------
# RiskAuditTrail — integrity verification
# ---------------------------------------------------------------------------


class TestRiskAuditTrailIntegrity:
    def test_verify_integrity_passes_on_clean_trail(self):
        trail = RiskAuditTrail()
        trail.log_decision(actor="t1", action="A1", reason="r1")
        trail.log_decision(actor="t2", action="A2", reason="r2")
        trail.log_decision(actor="t3", action="A3", reason="r3")
        assert trail.verify_integrity() is True

    def test_verify_integrity_detects_tampering(self):
        trail = RiskAuditTrail()
        trail.log_decision(actor="t1", action="A1", reason="r1")
        trail.log_decision(actor="t2", action="A2", reason="r2")
        # Tamper with an entry
        trail._entries[0].reason = "HACKED"
        assert trail.verify_integrity() is False

    def test_verify_integrity_detects_hash_modification(self):
        trail = RiskAuditTrail()
        trail.log_decision(actor="t1", action="A1", reason="r1")
        trail.log_decision(actor="t2", action="A2", reason="r2")
        # Tamper with hash
        trail._entries[1].entry_hash = "tampered_hash"
        assert trail.verify_integrity() is False

    def test_verify_integrity_empty_trail(self):
        trail = RiskAuditTrail()
        assert trail.verify_integrity() is True


# ---------------------------------------------------------------------------
# RiskAuditTrail — export
# ---------------------------------------------------------------------------


class TestRiskAuditTrailExport:
    def test_export_for_regulator_returns_json(self):
        trail = RiskAuditTrail()
        trail.log_decision(actor="t1", action="KILL_SWITCH", reason="r1")
        now = datetime.utcnow()
        result = trail.export_for_regulator(
            start=now - timedelta(hours=1),
            end=now + timedelta(hours=1),
        )
        data = json.loads(result)
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["action"] == "KILL_SWITCH"

    def test_export_respects_time_range(self):
        trail = RiskAuditTrail()
        now = datetime.utcnow()
        old = now - timedelta(hours=3)

        trail.log_decision(actor="t1", action="A1", reason="old")
        trail._entries[-1].timestamp = old

        trail.log_decision(actor="t2", action="A2", reason="recent")

        result = trail.export_for_regulator(
            start=now - timedelta(hours=1),
            end=now + timedelta(hours=1),
        )
        data = json.loads(result)
        assert len(data) == 1
        assert data[0]["actor"] == "t2"

    def test_export_empty_trail(self):
        trail = RiskAuditTrail()
        now = datetime.utcnow()
        result = trail.export_for_regulator(
            start=now - timedelta(hours=1),
            end=now + timedelta(hours=1),
        )
        data = json.loads(result)
        assert data == []


# ---------------------------------------------------------------------------
# RiskAuditTrail — persistence
# ---------------------------------------------------------------------------


class TestRiskAuditTrailPersistence:
    def test_save_and_load(self, tmp_path):
        trail = RiskAuditTrail(storage_path=tmp_path / "audit.jsonl")
        trail.log_decision(actor="t1", action="A1", reason="r1")
        trail.log_decision(actor="t2", action="A2", reason="r2")
        trail.save()

        # Load into new trail
        trail2 = RiskAuditTrail(storage_path=tmp_path / "audit.jsonl")
        trail2.load()
        assert len(trail2.get_entries()) == 2
        assert trail2.verify_integrity() is True

    def test_save_creates_file(self, tmp_path):
        trail = RiskAuditTrail(storage_path=tmp_path / "audit.jsonl")
        trail.log_decision(actor="t1", action="A1", reason="r1")
        trail.save()
        assert (tmp_path / "audit.jsonl").exists()

    def test_load_nonexistent_file_is_noop(self, tmp_path):
        trail = RiskAuditTrail(storage_path=tmp_path / "nonexistent.jsonl")
        trail.load()  # Should not raise
        assert trail.get_entries() == []

    def test_preserved_entries_match_original(self, tmp_path):
        trail = RiskAuditTrail(storage_path=tmp_path / "audit.jsonl")
        trail.log_decision(actor="t1", action="KILL_SWITCH", reason="test kill")
        trail.save()

        trail2 = RiskAuditTrail(storage_path=tmp_path / "audit.jsonl")
        trail2.load()
        entries = trail2.get_entries()
        assert len(entries) == 1
        assert entries[0].action == "KILL_SWITCH"
        assert entries[0].actor == "t1"
        assert entries[0].reason == "test kill"


# ---------------------------------------------------------------------------
# RiskAuditTrail — edge cases
# ---------------------------------------------------------------------------


class TestRiskAuditTrailEdgeCases:
    def test_metadata_with_nested_structures(self):
        trail = RiskAuditTrail()
        nested = {"order": {"id": "ord-1", "legs": [{"side": "buy", "qty": 100}]}}
        entry = trail.log_decision(actor="t1", action="A1", reason="r1", metadata=nested)
        assert entry.metadata["order"]["legs"][0]["side"] == "buy"

    def test_very_long_reason(self):
        trail = RiskAuditTrail()
        long_reason = "x" * 10000
        entry = trail.log_decision(actor="t1", action="A1", reason=long_reason)
        assert entry.reason == long_reason

    def test_unicode_in_fields(self):
        trail = RiskAuditTrail()
        entry = trail.log_decision(
            actor="trader-ünïcödé",
            action="ORDER_REJECT",
            reason="Price collar breached — 价格超限",
            metadata={"symbol": "BTCUSDT", "note": "日本語メモ"},
        )
        assert "ünïcödé" in entry.actor
        assert "价格超限" in entry.reason

    def test_multiple_entries_maintain_order(self):
        trail = RiskAuditTrail()
        for i in range(10):
            trail.log_decision(actor=f"t{i}", action="A", reason=f"r{i}")
        entries = trail.get_entries()
        assert len(entries) == 10
        # Should be in insertion order
        for i, entry in enumerate(entries):
            assert entry.actor == f"t{i}"

    def test_decision_id_format(self):
        trail = RiskAuditTrail()
        entry = trail.log_decision(actor="t1", action="A1", reason="r1")
        # Should be a non-empty string
        assert isinstance(entry.decision_id, str)
        assert len(entry.decision_id) > 0
