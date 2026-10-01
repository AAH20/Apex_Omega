"""FIX Reject Handler — session-level reject handling, error classification, and recovery.

Handles FIX session-level reject messages (MsgType=3) with proper error
classification per FIX 4.2 spec and determines appropriate recovery actions.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional

from src.fix.session.fix42_session import FIXMessage


class RejectReason(Enum):
    """FIX session reject reason codes per FIX 4.2 specification."""

    INVALID_TAG_NUMBER = 0
    REQUIRED_TAG_MISSING = 1
    TAG_NOT_DEFINED_FOR_MESSAGE_TYPE = 2
    UNDEFINED_TAG = 3
    TAG_SPECIFIED_WITHOUT_VALUE = 4
    VALUE_OUT_OF_RANGE = 5
    INCORRECT_DATA_FORMAT = 6
    DECRYPTION_PROBLEM = 7
    SIGNATURE_PROBLEM = 8
    COMP_ID_PROBLEM = 9
    SENDING_TIME_ACCURACY_PROBLEM = 10
    INVALID_MSG_TYPE = 11
    XML_VALIDATION_ERROR = 12
    TAG_APPEARS_MORE_THAN_ONCE = 13
    TAG_OUT_OF_REQUIRED_ORDER = 14
    REPEATING_GROUP_OUT_OF_ORDER = 15
    INCORRECT_NUM_IN_GROUP_COUNT = 16
    NON_DATA_VALUE_INCLUDES_DELIMITER = 17
    OTHER = 99

    @classmethod
    def from_code(cls, code: int) -> RejectReason:
        """Map a numeric reject reason code to the enum value.

        Args:
            code: The FIX tag 373 numeric reason code.

        Returns:
            The matching RejectReason, or OTHER if unrecognized.
        """
        for reason in cls:
            if reason.value == code:
                return reason
        return cls.OTHER


class RejectAction(Enum):
    """Recovery actions for session-level rejects."""

    RETRY = "retry"
    DISCONNECT = "disconnect"
    LOGOUT = "logout"


class SessionRejectError(Exception):
    """Raised when a reject message cannot be processed."""


@dataclass
class RejectEvent:
    """Represents a processed reject event with classification and action."""

    ref_seq_num: int
    reason: RejectReason
    action: RejectAction
    ref_tag: Optional[int] = None
    ref_msg_type: Optional[str] = None
    text: Optional[str] = None
    is_reject_on_reject: bool = False

    def is_critical(self) -> bool:
        """Check if this reject requires immediate disconnect."""
        return self.action == RejectAction.DISCONNECT

    def __str__(self) -> str:
        return (
            f"RejectEvent(seq={self.ref_seq_num}, "
            f"reason={self.reason.name}, "
            f"action={self.action.name})"
        )


class RejectHandler:
    """Handles FIX session-level reject messages with error classification and recovery."""

    # Mapping of reject reasons to recovery actions
    _REASON_ACTION_MAP: Dict[RejectReason, RejectAction] = {
        RejectReason.INVALID_TAG_NUMBER: RejectAction.DISCONNECT,
        RejectReason.REQUIRED_TAG_MISSING: RejectAction.DISCONNECT,
        RejectReason.TAG_NOT_DEFINED_FOR_MESSAGE_TYPE: RejectAction.DISCONNECT,
        RejectReason.UNDEFINED_TAG: RejectAction.DISCONNECT,
        RejectReason.TAG_SPECIFIED_WITHOUT_VALUE: RejectAction.DISCONNECT,
        RejectReason.VALUE_OUT_OF_RANGE: RejectAction.RETRY,
        RejectReason.INCORRECT_DATA_FORMAT: RejectAction.RETRY,
        RejectReason.DECRYPTION_PROBLEM: RejectAction.DISCONNECT,
        RejectReason.SIGNATURE_PROBLEM: RejectAction.DISCONNECT,
        RejectReason.COMP_ID_PROBLEM: RejectAction.DISCONNECT,
        RejectReason.SENDING_TIME_ACCURACY_PROBLEM: RejectAction.RETRY,
        RejectReason.INVALID_MSG_TYPE: RejectAction.DISCONNECT,
        RejectReason.XML_VALIDATION_ERROR: RejectAction.RETRY,
        RejectReason.TAG_APPEARS_MORE_THAN_ONCE: RejectAction.RETRY,
        RejectReason.TAG_OUT_OF_REQUIRED_ORDER: RejectAction.RETRY,
        RejectReason.REPEATING_GROUP_OUT_OF_ORDER: RejectAction.RETRY,
        RejectReason.INCORRECT_NUM_IN_GROUP_COUNT: RejectAction.RETRY,
        RejectReason.NON_DATA_VALUE_INCLUDES_DELIMITER: RejectAction.DISCONNECT,
        RejectReason.OTHER: RejectAction.LOGOUT,
    }

    def __init__(
        self,
        sender_comp_id: str = "SENDER",
        target_comp_id: str = "TARGET",
        max_rejects_before_disconnect: int = 5,
    ):
        """Initialize the reject handler.

        Args:
            sender_comp_id: Sender's CompID for building reject responses.
            target_comp_id: Target's CompID for building reject responses.
            max_rejects_before_disconnect: Threshold for forced disconnect.
        """
        self.sender_comp_id = sender_comp_id
        self.target_comp_id = target_comp_id
        self.max_rejects_before_disconnect = max_rejects_before_disconnect
        self._reject_history: List[RejectEvent] = []

    @staticmethod
    def determine_action(reason: RejectReason) -> RejectAction:
        """Determine the recovery action for a given reject reason.

        Args:
            reason: The classified reject reason.

        Returns:
            The appropriate recovery action.
        """
        return RejectHandler._REASON_ACTION_MAP.get(reason, RejectAction.LOGOUT)

    def process_reject(
        self,
        fields: Dict[str, str],
        msg_seq_num: Optional[int] = None,
    ) -> RejectEvent:
        """Process a reject message's fields and classify the error.

        Args:
            fields: Dictionary of FIX field tag -> value strings.
            msg_seq_num: The MsgSeqNum of the reject message itself (for loop detection).

        Returns:
            A RejectEvent with classification and recovery action.

        Raises:
            SessionRejectError: If required fields are missing or invalid.
        """
        # Validate required fields
        ref_seq_num_str = fields.get("45")
        if ref_seq_num_str is None:
            raise SessionRejectError("Missing RefSeqNum (tag 45) in reject message")

        reason_code_str = fields.get("373")
        if reason_code_str is None:
            raise SessionRejectError("Missing SessionRejectReason (tag 373) in reject message")

        try:
            ref_seq_num = int(ref_seq_num_str)
        except ValueError as e:
            raise SessionRejectError(f"Invalid RefSeqNum: {ref_seq_num_str!r}") from e

        try:
            reason_code = int(reason_code_str)
        except ValueError as e:
            raise SessionRejectError(
                f"Invalid SessionRejectReason: {reason_code_str!r}"
            ) from e

        reason = RejectReason.from_code(reason_code)
        action = self.determine_action(reason)

        # Detect reject-on-reject loop
        is_reject_on_reject = (
            msg_seq_num is not None and ref_seq_num == msg_seq_num
        )

        # Extract optional fields
        ref_tag_str = fields.get("371")
        ref_tag = int(ref_tag_str) if ref_tag_str is not None else None

        ref_msg_type = fields.get("372")
        text = fields.get("58")

        event = RejectEvent(
            ref_seq_num=ref_seq_num,
            reason=reason,
            action=action,
            ref_tag=ref_tag,
            ref_msg_type=ref_msg_type,
            text=text,
            is_reject_on_reject=is_reject_on_reject,
        )

        self._reject_history.append(event)
        return event

    @property
    def reject_history(self) -> List[RejectEvent]:
        """Get the history of processed reject events."""
        return list(self._reject_history)

    def clear_history(self) -> None:
        """Clear the reject history."""
        self._reject_history.clear()

    def should_disconnect(self) -> bool:
        """Check if the session should be disconnected based on reject history.

        Returns:
            True if the number of rejects exceeds the threshold.
        """
        return len(self._reject_history) >= self.max_rejects_before_disconnect

    def get_reject_counts_by_reason(self) -> Dict[RejectReason, int]:
        """Get counts of rejects grouped by reason.

        Returns:
            Dictionary mapping reject reasons to their occurrence count.
        """
        counts: Dict[RejectReason, int] = {}
        for event in self._reject_history:
            counts[event.reason] = counts.get(event.reason, 0) + 1
        return counts

    def build_reject_response(
        self,
        ref_seq_num: int,
        reason: RejectReason,
        ref_tag: Optional[int] = None,
        ref_msg_type: Optional[str] = None,
        text: Optional[str] = None,
    ) -> FIXMessage:
        """Build a FIX reject response message.

        Args:
            ref_seq_num: The sequence number of the rejected message.
            reason: The reject reason.
            ref_tag: The tag number that caused the reject, if applicable.
            ref_msg_type: The message type that was rejected, if applicable.
            text: Optional descriptive text.

        Returns:
            A FIXMessage of type Reject (3).
        """
        fields: Dict[str, str] = {
            "45": str(ref_seq_num),
            "373": str(reason.value),
        }
        if ref_tag is not None:
            fields["371"] = str(ref_tag)
        if ref_msg_type is not None:
            fields["372"] = ref_msg_type
        if text is not None:
            fields["58"] = text

        return FIXMessage(
            msg_type="3",
            sender_comp_id=self.sender_comp_id,
            target_comp_id=self.target_comp_id,
            seq_num=0,  # Will be set by session layer
            fields=fields,
        )
