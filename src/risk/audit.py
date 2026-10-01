"""Risk Audit Trail — regulatory compliance logging.

Implements tamper-evident audit logging for all risk decisions,
satisfying MiFID II RTS 6 record-keeping requirements.

Each entry is cryptographically chained to the previous one,
creating an immutable hash chain that detects any modification.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass
class AuditEntry:
    """A single audit trail entry.

    Attributes:
        timestamp: UTC datetime of the decision.
        decision_id: Unique identifier for this decision.
        actor: Who or what made the decision.
        action: Type of action (e.g., KILL_SWITCH, ORDER_REJECT).
        reason: Human-readable explanation.
        metadata: Additional structured context.
        entry_hash: SHA-256 hash for tamper detection.
    """

    timestamp: datetime
    decision_id: str
    actor: str
    action: str
    reason: str
    metadata: dict[str, Any] = field(default_factory=dict)
    entry_hash: str = ""

    def __post_init__(self) -> None:
        if self.metadata is None:
            self.metadata = {}

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "timestamp": self.timestamp.isoformat(),
            "decision_id": self.decision_id,
            "actor": self.actor,
            "action": self.action,
            "reason": self.reason,
            "metadata": self.metadata,
            "entry_hash": self.entry_hash,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AuditEntry:
        """Deserialize from dictionary."""
        return cls(
            timestamp=datetime.fromisoformat(data["timestamp"]),
            decision_id=data["decision_id"],
            actor=data["actor"],
            action=data["action"],
            reason=data["reason"],
            metadata=data.get("metadata", {}),
            entry_hash=data.get("entry_hash", ""),
        )


class RiskAuditTrail:
    """Tamper-evident audit trail for risk decisions.

    Maintains a hash-chained log of all risk-related decisions
    for regulatory compliance (MiFID II RTS 6).
    """

    def __init__(self, storage_path: Path | str | None = None) -> None:
        self._entries: list[AuditEntry] = []
        self._storage_path = Path(storage_path) if storage_path else None

    # ── Core logging ────────────────────────────────────────────────

    def log_decision(
        self,
        actor: str,
        action: str,
        reason: str,
        metadata: dict[str, Any] | None = None,
    ) -> AuditEntry:
        """Log a generic risk decision.

        Args:
            actor: Who or what made the decision.
            action: Type of action.
            reason: Human-readable explanation.
            metadata: Additional structured context.

        Returns:
            The created AuditEntry.
        """
        entry = AuditEntry(
            timestamp=datetime.utcnow(),
            decision_id=str(uuid.uuid4()),
            actor=actor,
            action=action,
            reason=reason,
            metadata=metadata or {},
        )
        entry.entry_hash = self._compute_hash(entry)
        self._entries.append(entry)
        return entry

    def log_kill_switch(
        self,
        actor: str,
        reason: str,
        venues: list[str],
        trigger_type: str = "manual",
    ) -> AuditEntry:
        """Log a kill switch activation.

        Args:
            actor: Who triggered the kill switch.
            reason: Why the kill switch was activated.
            venues: List of venues affected.
            trigger_type: 'manual' or 'automatic'.

        Returns:
            The created AuditEntry.
        """
        return self.log_decision(
            actor=actor,
            action="KILL_SWITCH",
            reason=reason,
            metadata={
                "venues": venues,
                "trigger_type": trigger_type,
            },
        )

    def log_pre_trade_check(
        self,
        order_id: str,
        decision: str,
        checks: dict[str, str],
    ) -> AuditEntry:
        """Log a pre-trade risk check result.

        Args:
            order_id: The order that was checked.
            decision: 'PASS' or 'FAIL'.
            checks: Mapping of check name to result.

        Returns:
            The created AuditEntry.
        """
        return self.log_decision(
            actor="pre-trade-engine",
            action="PRE_TRADE_CHECK",
            reason=f"Order {order_id}: {decision}",
            metadata={
                "order_id": order_id,
                "decision": decision,
                "checks": checks,
            },
        )

    def log_otr_alert(
        self,
        venue: str,
        symbol: str,
        otr_value: float,
        threshold: float,
    ) -> AuditEntry:
        """Log an order-to-trade ratio alert.

        Args:
            venue: Trading venue.
            symbol: Financial instrument.
            otr_value: Current OTR value.
            threshold: Configured OTR threshold.

        Returns:
            The created AuditEntry.
        """
        utilization = (otr_value / threshold * 100) if threshold > 0 else 0.0
        return self.log_decision(
            actor="otr-monitor",
            action="OTR_ALERT",
            reason=f"OTR {otr_value} at {utilization:.1f}% of threshold {threshold}",
            metadata={
                "venue": venue,
                "symbol": symbol,
                "otr_value": otr_value,
                "threshold": threshold,
                "utilization_pct": utilization,
            },
        )

    # ── Query ───────────────────────────────────────────────────────

    def get_entries(
        self,
        actor: str | None = None,
        action: str | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[AuditEntry]:
        """Get audit entries with optional filters.

        Args:
            actor: Filter by actor.
            action: Filter by action type.
            start: Filter entries after this time (inclusive).
            end: Filter entries before this time (inclusive).

        Returns:
            List of matching AuditEntry objects.
        """
        result = self._entries
        if actor is not None:
            result = [e for e in result if e.actor == actor]
        if action is not None:
            result = [e for e in result if e.action == action]
        if start is not None:
            result = [e for e in result if e.timestamp >= start]
        if end is not None:
            result = [e for e in result if e.timestamp <= end]
        return result

    # ── Integrity ──────────────────────────────────────────────────

    def verify_integrity(self) -> bool:
        """Verify the hash chain integrity.

        Returns:
            True if the trail is intact, False if tampering detected.
        """
        for i, entry in enumerate(self._entries):
            expected_hash = self._compute_hash(entry, i)
            if entry.entry_hash != expected_hash:
                return False
        return True

    # ── Export ──────────────────────────────────────────────────────

    def export_for_regulator(
        self,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> str:
        """Export audit entries as JSON for regulatory submission.

        Args:
            start: Start of time range (inclusive).
            end: End of time range (inclusive).

        Returns:
            JSON string of matching entries.
        """
        entries = self.get_entries(start=start, end=end)
        return json.dumps([e.to_dict() for e in entries], indent=2)

    # ── Persistence ─────────────────────────────────────────────────

    def save(self) -> None:
        """Persist audit trail to storage path."""
        if self._storage_path is None:
            return
        self._storage_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._storage_path, "w") as f:
            for entry in self._entries:
                f.write(json.dumps(entry.to_dict()) + "\n")

    def load(self) -> None:
        """Load audit trail from storage path."""
        if self._storage_path is None or not self._storage_path.exists():
            return
        self._entries = []
        with open(self._storage_path) as f:
            for line in f:
                line = line.strip()
                if line:
                    data = json.loads(line)
                    self._entries.append(AuditEntry.from_dict(data))

    # ── Hash computation ────────────────────────────────────────────

    def _compute_hash(self, entry: AuditEntry, index: int | None = None) -> str:
        """Compute SHA-256 hash for an entry.

        The hash incorporates the previous entry's hash to create
        a tamper-evident chain.

        Args:
            entry: The entry to hash.
            index: Entry index (for previous hash lookup).

        Returns:
            Hex digest string.
        """
        # Get previous hash for chaining
        prev_hash = ""
        if index is not None and index > 0 and index <= len(self._entries):
            prev_hash = self._entries[index - 1].entry_hash
        elif index is None and self._entries:
            prev_hash = self._entries[-1].entry_hash

        # Build hash input
        hash_input = {
            "timestamp": entry.timestamp.isoformat(),
            "decision_id": entry.decision_id,
            "actor": entry.actor,
            "action": entry.action,
            "reason": entry.reason,
            "metadata": entry.metadata,
            "prev_hash": prev_hash,
        }
        canonical = json.dumps(hash_input, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()
