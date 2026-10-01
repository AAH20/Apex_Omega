"""Tests for MiFID II RTS 22 Regulatory Reporting — TDD: written before implementation.

Covers RTS 22 transaction records, RTS 22 report generation, and audit evidence.
"""
import json
import pytest
from datetime import datetime, timedelta
from pathlib import Path

from src.security.regulatory import (
    AuditEvidence,
    AuditEvidenceCollector,
    BuySellIndicator,
    RTS22Reporter,
    TradingCapacity,
    TransactionRecord,
    TransactionReport,
)


# ---------------------------------------------------------------------------
# Enum tests
# ---------------------------------------------------------------------------


class TestEnums:
    def test_buy_sell_indicator_values(self):
        assert BuySellIndicator.BUY.value == "B"
        assert BuySellIndicator.SELL.value == "S"

    def test_trading_capacity_values(self):
        assert TradingCapacity.DEALING_ON_OWN_ACCOUNT.value == "DEAL"
        assert TradingCapacity.DEALING_ON_BEHALF_OF_CLIENT.value == "AOTC"
        assert TradingCapacity.ANY_OTHER_CLIENT_TRANSACTION.value == "AOTC"


# ---------------------------------------------------------------------------
# TransactionRecord tests
# ---------------------------------------------------------------------------


class TestTransactionRecord:
    def test_create_transaction_record(self):
        record = TransactionRecord(
            transaction_id="txn-001",
            timestamp=datetime(2026, 10, 1, 12, 0, 0),
            instrument_id="US0378331005",
            instrument_type="EQUITY",
            price=150.0,
            quantity=100.0,
            venue="XNAS",
            buy_sell=BuySellIndicator.BUY,
            trading_capacity=TradingCapacity.DEALING_ON_OWN_ACCOUNT,
            client_id="client-001",
            algorithm_id="algo-001",
            investment_decision_maker="trader-001",
            counterparty="counterparty-001",
        )
        assert record.transaction_id == "txn-001"
        assert record.instrument_id == "US0378331005"
        assert record.price == 150.0
        assert record.quantity == 100.0
        assert record.venue == "XNAS"
        assert record.buy_sell == BuySellIndicator.BUY
        assert record.trading_capacity == TradingCapacity.DEALING_ON_OWN_ACCOUNT

    def test_record_metadata_defaults_to_empty_dict(self):
        record = TransactionRecord(
            transaction_id="txn-002",
            timestamp=datetime(2026, 10, 1, 12, 0, 0),
            instrument_id="US0378331005",
            instrument_type="EQUITY",
            price=150.0,
            quantity=100.0,
            venue="XNAS",
            buy_sell=BuySellIndicator.SELL,
            trading_capacity=TradingCapacity.DEALING_ON_OWN_ACCOUNT,
            client_id="client-001",
            algorithm_id="algo-001",
            investment_decision_maker="trader-001",
            counterparty="counterparty-001",
        )
        assert record.metadata == {}


# ---------------------------------------------------------------------------
# TransactionReport tests
# ---------------------------------------------------------------------------


class TestTransactionReport:
    def _make_record(self):
        return TransactionRecord(
            transaction_id="txn-001",
            timestamp=datetime(2026, 10, 1, 12, 0, 0),
            instrument_id="US0378331005",
            instrument_type="EQUITY",
            price=150.0,
            quantity=100.0,
            venue="XNAS",
            buy_sell=BuySellIndicator.BUY,
            trading_capacity=TradingCapacity.DEALING_ON_OWN_ACCOUNT,
            client_id="client-001",
            algorithm_id="algo-001",
            investment_decision_maker="trader-001",
            counterparty="counterparty-001",
        )

    def test_create_report(self):
        reporter = RTS22Reporter()
        record = self._make_record()
        report = reporter.create_report(record)
        assert report.report_id is not None
        assert report.transaction_id == "txn-001"
        assert report.instrument_id == "US0378331005"
        assert report.price == 150.0
        assert report.quantity == 100.0

    def test_report_has_hash(self):
        reporter = RTS22Reporter()
        record = self._make_record()
        report = reporter.create_report(record)
        assert report.report_hash is not None
        assert len(report.report_hash) == 64  # SHA-256 hex

    def test_report_to_dict(self):
        reporter = RTS22Reporter()
        record = self._make_record()
        report = reporter.create_report(record)
        d = report.to_dict()
        assert d["transaction_id"] == "txn-001"
        assert d["instrument_id"] == "US0378331005"
        assert d["price"] == 150.0
        assert d["quantity"] == 100.0
        assert d["venue"] == "XNAS"
        assert d["buy_sell"] == "B"
        assert d["trading_capacity"] == "DEAL"

    def test_report_to_json(self):
        reporter = RTS22Reporter()
        record = self._make_record()
        report = reporter.create_report(record)
        j = report.to_json()
        data = json.loads(j)
        assert data["transaction_id"] == "txn-001"
        assert data["instrument_id"] == "US0378331005"

    def test_report_to_csv_row(self):
        reporter = RTS22Reporter()
        record = self._make_record()
        report = reporter.create_report(record)
        row = report.to_csv_row()
        assert row["transaction_id"] == "txn-001"
        assert row["instrument_id"] == "US0378331005"
        assert row["price"] == "150.0"
        assert row["quantity"] == "100.0"

    def test_multiple_reports_have_unique_ids(self):
        reporter = RTS22Reporter()
        record = self._make_record()
        r1 = reporter.create_report(record)
        r2 = reporter.create_report(record)
        assert r1.report_id != r2.report_id

    def test_multiple_reports_have_different_hashes(self):
        reporter = RTS22Reporter()
        record = self._make_record()
        r1 = reporter.create_report(record)
        r2 = reporter.create_report(record)
        # Same transaction data but different report_id → different hash
        assert r1.report_hash != r2.report_hash

    def test_reporter_get_reports(self):
        reporter = RTS22Reporter()
        record = self._make_record()
        reporter.create_report(record)
        reporter.create_report(record)
        reports = reporter.get_reports()
        assert len(reports) == 2

    def test_reporter_export_csv(self):
        reporter = RTS22Reporter()
        record = self._make_record()
        reporter.create_report(record)
        csv_output = reporter.export_csv()
        assert "transaction_id" in csv_output
        assert "txn-001" in csv_output

    def test_reporter_export_json(self):
        reporter = RTS22Reporter()
        record = self._make_record()
        reporter.create_report(record)
        json_output = reporter.export_json()
        data = json.loads(json_output)
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["transaction_id"] == "txn-001"

    def test_reporter_export_csv_empty(self):
        reporter = RTS22Reporter()
        assert reporter.export_csv() == ""

    def test_reporter_export_json_empty(self):
        reporter = RTS22Reporter()
        data = json.loads(reporter.export_json())
        assert data == []

    def test_report_dataclass_fields(self):
        report = TransactionReport(
            report_id="rpt-001",
            transaction_id="txn-001",
            timestamp=datetime(2026, 10, 1, 12, 0, 0),
            instrument_id="US0378331005",
            instrument_type="EQUITY",
            price=150.0,
            quantity=100.0,
            venue="XNAS",
            buy_sell=BuySellIndicator.BUY,
            trading_capacity=TradingCapacity.DEALING_ON_OWN_ACCOUNT,
            client_id="client-001",
            algorithm_id="algo-001",
            investment_decision_maker="trader-001",
            counterparty="counterparty-001",
        )
        assert report.report_id == "rpt-001"
        assert report.transaction_id == "txn-001"
        assert report.metadata == {}
        assert report.report_hash == ""


# ---------------------------------------------------------------------------
# AuditEvidence tests
# ---------------------------------------------------------------------------


class TestAuditEvidence:
    def test_create_evidence(self):
        evidence = AuditEvidence(
            evidence_id="ev-001",
            timestamp=datetime(2026, 10, 1, 12, 0, 0),
            event_type="TRANSACTION_REPORTED",
            description="Transaction txn-001 reported",
            data={"transaction_id": "txn-001"},
        )
        assert evidence.evidence_id == "ev-001"
        assert evidence.event_type == "TRANSACTION_REPORTED"
        assert evidence.data["transaction_id"] == "txn-001"

    def test_evidence_to_dict(self):
        evidence = AuditEvidence(
            evidence_id="ev-001",
            timestamp=datetime(2026, 10, 1, 12, 0, 0),
            event_type="TRANSACTION_REPORTED",
            description="Transaction txn-001 reported",
            data={"transaction_id": "txn-001"},
        )
        d = evidence.to_dict()
        assert d["evidence_id"] == "ev-001"
        assert d["event_type"] == "TRANSACTION_REPORTED"
        assert d["data"]["transaction_id"] == "txn-001"


# ---------------------------------------------------------------------------
# AuditEvidenceCollector tests
# ---------------------------------------------------------------------------


class TestAuditEvidenceCollector:
    def test_collector_initializes_empty(self):
        collector = AuditEvidenceCollector()
        assert collector.get_evidence() == []

    def test_collect_creates_evidence(self):
        collector = AuditEvidenceCollector()
        evidence = collector.collect(
            event_type="TRANSACTION_REPORTED",
            description="Transaction txn-001 reported",
            data={"transaction_id": "txn-001"},
        )
        assert evidence.evidence_id is not None
        assert evidence.event_type == "TRANSACTION_REPORTED"
        assert evidence.evidence_hash is not None
        assert len(evidence.evidence_hash) == 64

    def test_collect_increments_evidence(self):
        collector = AuditEvidenceCollector()
        collector.collect(event_type="E1", description="d1")
        collector.collect(event_type="E2", description="d2")
        assert len(collector.get_evidence()) == 2

    def test_evidence_chain_integrity(self):
        collector = AuditEvidenceCollector()
        collector.collect(event_type="E1", description="d1")
        collector.collect(event_type="E2", description="d2")
        collector.collect(event_type="E3", description="d3")
        assert collector.verify_integrity() is True

    def test_evidence_tamper_detection(self):
        collector = AuditEvidenceCollector()
        collector.collect(event_type="E1", description="d1")
        collector.collect(event_type="E2", description="d2")
        # Tamper with evidence
        collector._evidence[0].description = "HACKED"
        assert collector.verify_integrity() is False

    def test_evidence_tamper_detection_hash_modification(self):
        collector = AuditEvidenceCollector()
        collector.collect(event_type="E1", description="d1")
        collector.collect(event_type="E2", description="d2")
        # Tamper with hash
        collector._evidence[1].evidence_hash = "tampered"
        assert collector.verify_integrity() is False

    def test_evidence_export_json(self):
        collector = AuditEvidenceCollector()
        collector.collect(event_type="E1", description="d1")
        collector.collect(event_type="E2", description="d2")
        json_output = collector.export_json()
        data = json.loads(json_output)
        assert isinstance(data, list)
        assert len(data) == 2
        assert data[0]["event_type"] == "E1"
        assert data[1]["event_type"] == "E2"

    def test_evidence_chain_links(self):
        collector = AuditEvidenceCollector()
        e1 = collector.collect(event_type="E1", description="d1")
        e2 = collector.collect(event_type="E2", description="d2")
        # e2's prev_hash should be e1's hash
        assert e2.prev_hash == e1.evidence_hash

    def test_evidence_unique_ids(self):
        collector = AuditEvidenceCollector()
        e1 = collector.collect(event_type="E1", description="d1")
        e2 = collector.collect(event_type="E2", description="d2")
        assert e1.evidence_id != e2.evidence_id

    def test_evidence_empty_collector_integrity(self):
        collector = AuditEvidenceCollector()
        assert collector.verify_integrity() is True
