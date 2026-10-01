"""MiFID II RTS 22 Regulatory Reporting, Transaction Reporting, and Audit Evidence.

Implements:
- RTS 22 transaction record creation and report generation
- Transaction reporting with hash-chained integrity
- Audit evidence collection with tamper-evident hash chain

References:
- MiFID II RTS 22 (Commission Delegated Regulation (EU) 2017/590)
- MiFID II RTS 6 (Algorithmic trading requirements)
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class BuySellIndicator(Enum):
    """Buy/Sell indicator per RTS 22 field 7."""
    BUY = "B"
    SELL = "S"


class TradingCapacity(Enum):
    """Trading capacity per RTS 22 field 10."""
    DEALING_ON_OWN_ACCOUNT = "DEAL"
    DEALING_ON_BEHALF_OF_CLIENT = "AOTC"
    ANY_OTHER_CLIENT_TRANSACTION = "AOTC"


# ---------------------------------------------------------------------------
# Transaction Record
# ---------------------------------------------------------------------------


@dataclass
class TransactionRecord:
    """A single transaction record per RTS 22.

    Attributes:
        transaction_id: Unique transaction identifier.
        timestamp: UTC timestamp of the transaction.
        instrument_id: ISIN or other instrument identifier.
        instrument_type: Type of financial instrument.
        price: Transaction price.
        quantity: Transaction quantity.
        venue: Trading venue (MIC code).
        buy_sell: Buy or sell indicator.
        trading_capacity: Trading capacity.
        client_id: Client identifier.
        algorithm_id: Algorithm identifier (if applicable).
        investment_decision_maker: Investment decision maker.
        counterparty: Counterparty identifier.
        metadata: Additional structured context.
    """

    transaction_id: str
    timestamp: datetime
    instrument_id: str
    instrument_type: str
    price: float
    quantity: float
    venue: str
    buy_sell: BuySellIndicator
    trading_capacity: TradingCapacity
    client_id: str
    algorithm_id: str
    investment_decision_maker: str
    counterparty: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.metadata is None:
            self.metadata = {}

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "transaction_id": self.transaction_id,
            "timestamp": self.timestamp.isoformat(),
            "instrument_id": self.instrument_id,
            "instrument_type": self.instrument_type,
            "price": self.price,
            "quantity": self.quantity,
            "venue": self.venue,
            "buy_sell": self.buy_sell.value,
            "trading_capacity": self.trading_capacity.value,
            "client_id": self.client_id,
            "algorithm_id": self.algorithm_id,
            "investment_decision_maker": self.investment_decision_maker,
            "counterparty": self.counterparty,
            "metadata": self.metadata,
        }


# ---------------------------------------------------------------------------
# Transaction Report
# ---------------------------------------------------------------------------


@dataclass
class TransactionReport:
    """An RTS 22 transaction report.

    Attributes:
        report_id: Unique report identifier.
        transaction_id: Reference to the original transaction.
        timestamp: Report generation timestamp.
        instrument_id: Instrument identifier.
        instrument_type: Type of financial instrument.
        price: Transaction price.
        quantity: Transaction quantity.
        venue: Trading venue.
        buy_sell: Buy or sell indicator.
        trading_capacity: Trading capacity.
        client_id: Client identifier.
        algorithm_id: Algorithm identifier.
        investment_decision_maker: Investment decision maker.
        counterparty: Counterparty identifier.
        metadata: Additional structured context.
        report_hash: SHA-256 hash for integrity verification.
    """

    report_id: str
    transaction_id: str
    timestamp: datetime
    instrument_id: str
    instrument_type: str
    price: float
    quantity: float
    venue: str
    buy_sell: BuySellIndicator
    trading_capacity: TradingCapacity
    client_id: str
    algorithm_id: str
    investment_decision_maker: str
    counterparty: str
    metadata: dict[str, Any] = field(default_factory=dict)
    report_hash: str = ""

    def __post_init__(self) -> None:
        if self.metadata is None:
            self.metadata = {}

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "report_id": self.report_id,
            "transaction_id": self.transaction_id,
            "timestamp": self.timestamp.isoformat(),
            "instrument_id": self.instrument_id,
            "instrument_type": self.instrument_type,
            "price": self.price,
            "quantity": self.quantity,
            "venue": self.venue,
            "buy_sell": self.buy_sell.value,
            "trading_capacity": self.trading_capacity.value,
            "client_id": self.client_id,
            "algorithm_id": self.algorithm_id,
            "investment_decision_maker": self.investment_decision_maker,
            "counterparty": self.counterparty,
            "metadata": self.metadata,
            "report_hash": self.report_hash,
        }

    def to_json(self) -> str:
        """Serialize to JSON string."""
        return json.dumps(self.to_dict(), indent=2)

    def to_csv_row(self) -> dict[str, str]:
        """Serialize to a flat dictionary suitable for CSV output."""
        return {
            "report_id": self.report_id,
            "transaction_id": self.transaction_id,
            "timestamp": self.timestamp.isoformat(),
            "instrument_id": self.instrument_id,
            "instrument_type": self.instrument_type,
            "price": str(self.price),
            "quantity": str(self.quantity),
            "venue": self.venue,
            "buy_sell": self.buy_sell.value,
            "trading_capacity": self.trading_capacity.value,
            "client_id": self.client_id,
            "algorithm_id": self.algorithm_id,
            "investment_decision_maker": self.investment_decision_maker,
            "counterparty": self.counterparty,
            "report_hash": self.report_hash,
        }


# ---------------------------------------------------------------------------
# RTS 22 Reporter
# ---------------------------------------------------------------------------


class RTS22Reporter:
    """Generates RTS 22 transaction reports.

    Creates hash-chained reports for regulatory submission.
    Each report includes a SHA-256 hash for integrity verification.
    """

    def __init__(self) -> None:
        self._reports: list[TransactionReport] = []

    def create_report(self, record: TransactionRecord) -> TransactionReport:
        """Create an RTS 22 report from a transaction record.

        Args:
            record: The transaction record to report.

        Returns:
            The created TransactionReport.
        """
        report = TransactionReport(
            report_id=str(uuid.uuid4()),
            transaction_id=record.transaction_id,
            timestamp=datetime.utcnow(),
            instrument_id=record.instrument_id,
            instrument_type=record.instrument_type,
            price=record.price,
            quantity=record.quantity,
            venue=record.venue,
            buy_sell=record.buy_sell,
            trading_capacity=record.trading_capacity,
            client_id=record.client_id,
            algorithm_id=record.algorithm_id,
            investment_decision_maker=record.investment_decision_maker,
            counterparty=record.counterparty,
            metadata=record.metadata,
        )
        report.report_hash = self._compute_hash(report)
        self._reports.append(report)
        return report

    def get_reports(self) -> list[TransactionReport]:
        """Get all generated reports."""
        return list(self._reports)

    def export_csv(self) -> str:
        """Export all reports as CSV.

        Returns:
            CSV string of all reports, or empty string if no reports.
        """
        if not self._reports:
            return ""
        output = io.StringIO()
        fieldnames = [
            "report_id",
            "transaction_id",
            "timestamp",
            "instrument_id",
            "instrument_type",
            "price",
            "quantity",
            "venue",
            "buy_sell",
            "trading_capacity",
            "client_id",
            "algorithm_id",
            "investment_decision_maker",
            "counterparty",
            "report_hash",
        ]
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        for report in self._reports:
            writer.writerow(report.to_csv_row())
        return output.getvalue()

    def export_json(self) -> str:
        """Export all reports as JSON.

        Returns:
            JSON string of all reports.
        """
        return json.dumps([r.to_dict() for r in self._reports], indent=2)

    def _compute_hash(self, report: TransactionReport) -> str:
        """Compute SHA-256 hash for a report.

        Args:
            report: The report to hash.

        Returns:
            Hex digest string.
        """
        hash_input = {
            "report_id": report.report_id,
            "transaction_id": report.transaction_id,
            "timestamp": report.timestamp.isoformat(),
            "instrument_id": report.instrument_id,
            "instrument_type": report.instrument_type,
            "price": report.price,
            "quantity": report.quantity,
            "venue": report.venue,
            "buy_sell": report.buy_sell.value,
            "trading_capacity": report.trading_capacity.value,
            "client_id": report.client_id,
            "algorithm_id": report.algorithm_id,
            "investment_decision_maker": report.investment_decision_maker,
            "counterparty": report.counterparty,
            "metadata": report.metadata,
        }
        canonical = json.dumps(hash_input, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Audit Evidence
# ---------------------------------------------------------------------------


@dataclass
class AuditEvidence:
    """A single audit evidence entry.

    Attributes:
        evidence_id: Unique evidence identifier.
        timestamp: UTC timestamp of the event.
        event_type: Type of event (e.g., TRANSACTION_REPORTED).
        description: Human-readable description.
        data: Additional structured context.
        evidence_hash: SHA-256 hash for tamper detection.
        prev_hash: Hash of the previous evidence entry (for chaining).
    """

    evidence_id: str
    timestamp: datetime
    event_type: str
    description: str
    data: dict[str, Any] = field(default_factory=dict)
    evidence_hash: str = ""
    prev_hash: str = ""

    def __post_init__(self) -> None:
        if self.data is None:
            self.data = {}

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "evidence_id": self.evidence_id,
            "timestamp": self.timestamp.isoformat(),
            "event_type": self.event_type,
            "description": self.description,
            "data": self.data,
            "evidence_hash": self.evidence_hash,
            "prev_hash": self.prev_hash,
        }


# ---------------------------------------------------------------------------
# Audit Evidence Collector
# ---------------------------------------------------------------------------


class AuditEvidenceCollector:
    """Collects and manages audit evidence with tamper-evident hash chain.

    Each evidence entry is cryptographically chained to the previous one,
    creating an immutable record for regulatory compliance.
    """

    def __init__(self) -> None:
        self._evidence: list[AuditEvidence] = []

    def collect(
        self,
        event_type: str,
        description: str,
        data: dict[str, Any] | None = None,
    ) -> AuditEvidence:
        """Collect audit evidence.

        Args:
            event_type: Type of event.
            description: Human-readable description.
            data: Additional structured context.

        Returns:
            The created AuditEvidence.
        """
        prev_hash = self._evidence[-1].evidence_hash if self._evidence else ""
        evidence = AuditEvidence(
            evidence_id=str(uuid.uuid4()),
            timestamp=datetime.utcnow(),
            event_type=event_type,
            description=description,
            data=data or {},
            prev_hash=prev_hash,
        )
        evidence.evidence_hash = self._compute_hash(evidence)
        self._evidence.append(evidence)
        return evidence

    def get_evidence(self) -> list[AuditEvidence]:
        """Get all evidence entries."""
        return list(self._evidence)

    def verify_integrity(self) -> bool:
        """Verify the hash chain integrity.

        Returns:
            True if the chain is intact, False if tampering detected.
        """
        for i, evidence in enumerate(self._evidence):
            expected_hash = self._compute_hash(evidence, i)
            if evidence.evidence_hash != expected_hash:
                return False
        return True

    def export_json(self) -> str:
        """Export all evidence as JSON.

        Returns:
            JSON string of all evidence entries.
        """
        return json.dumps([e.to_dict() for e in self._evidence], indent=2)

    def _compute_hash(self, evidence: AuditEvidence, index: int | None = None) -> str:
        """Compute SHA-256 hash for an evidence entry.

        The hash incorporates the previous entry's hash to create
        a tamper-evident chain.

        Args:
            evidence: The evidence entry to hash.
            index: Entry index (for previous hash lookup).

        Returns:
            Hex digest string.
        """
        prev_hash = ""
        if index is not None and index > 0 and index <= len(self._evidence):
            prev_hash = self._evidence[index - 1].evidence_hash
        elif index is None and self._evidence:
            prev_hash = self._evidence[-1].evidence_hash

        hash_input = {
            "evidence_id": evidence.evidence_id,
            "timestamp": evidence.timestamp.isoformat(),
            "event_type": evidence.event_type,
            "description": evidence.description,
            "data": evidence.data,
            "prev_hash": prev_hash,
        }
        canonical = json.dumps(hash_input, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()
