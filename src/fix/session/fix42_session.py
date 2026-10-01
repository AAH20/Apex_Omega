"""FIX 4.2 Protocol Engine — Session Layer.

Implements message parsing, sequence number management, heartbeat handling,
and session state machine per the FIX 4.2 specification.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class FIXParseError(Exception):
    """Raised when a FIX message cannot be parsed."""


class FIXChecksumError(Exception):
    """Raised when a FIX message checksum is invalid."""


class FIXSequenceError(Exception):
    """Raised for sequence number or state machine violations."""


# ---------------------------------------------------------------------------
# Session State Enum
# ---------------------------------------------------------------------------

class SessionState(Enum):
    """FIX session state machine states."""

    DISCONNECTED = "DISCONNECTED"
    CONNECTING = "CONNECTING"
    LOGGED_IN = "LOGGED_IN"
    LOGGED_OUT = "LOGGED_OUT"


# ---------------------------------------------------------------------------
# FIX Message
# ---------------------------------------------------------------------------

@dataclass
class FIXMessage:
    """Represents a parsed FIX 4.2 message."""

    msg_type: str
    sender_comp_id: str
    target_comp_id: str
    seq_num: int
    fields: dict[str, str] = field(default_factory=dict)
    raw: bytes = b""

    @classmethod
    def from_bytes(cls, data: bytes) -> FIXMessage:
        """Parse a raw FIX message from bytes.

        Args:
            data: Raw FIX message bytes.

        Returns:
            Parsed FIXMessage.

        Raises:
            FIXParseError: If the message is malformed.
            FIXChecksumError: If the checksum is invalid.
        """
        if not data:
            raise FIXParseError("Empty message")

        # Split into fields
        parts = data.split(b"\x01")
        # Remove trailing empty part after last SOH
        if parts and parts[-1] == b"":
            parts = parts[:-1]

        if len(parts) < 3:
            raise FIXParseError("Message too short")

        # Parse header
        begin_string = parts[0]
        if not begin_string.startswith(b"8=FIX.4.2"):
            raise FIXParseError(f"Invalid BeginString: {begin_string!r}")

        body_length_field = parts[1]
        if not body_length_field.startswith(b"9="):
            raise FIXParseError(f"Missing BodyLength: {body_length_field!r}")

        try:
            body_length = int(body_length_field[2:])
        except ValueError as e:
            raise FIXParseError(f"Invalid BodyLength: {body_length_field!r}") from e

        # Parse body fields (everything between header and trailer)
        body_parts = parts[2:-1]  # Exclude header and trailer
        trailer = parts[-1]

        # Validate checksum
        if not trailer.startswith(b"10="):
            raise FIXParseError(f"Missing checksum: {trailer!r}")

        try:
            expected_checksum = int(trailer[3:6])
        except ValueError as e:
            raise FIXParseError(f"Invalid checksum: {trailer!r}") from e

        # Compute checksum over everything before the 10= field (including trailing SOH)
        checksum_data = data[: data.rfind(b"10=")]
        computed_checksum = sum(checksum_data) % 256

        if computed_checksum != expected_checksum:
            raise FIXChecksumError(
                f"Checksum mismatch: expected {expected_checksum:03d}, got {computed_checksum:03d}"
            )

        # Parse body fields into a dict
        parsed_fields: dict[str, str] = {}
        msg_type = ""
        sender_comp_id = ""
        target_comp_id = ""
        seq_num = 0

        for part in body_parts:
            if b"=" not in part:
                continue
            tag_bytes, val_bytes = part.split(b"=", 1)
            tag = tag_bytes.decode("ascii", errors="replace")
            val = val_bytes.decode("ascii", errors="replace")

            if tag == "35":
                msg_type = val
            elif tag == "49":
                sender_comp_id = val
            elif tag == "56":
                target_comp_id = val
            elif tag == "34":
                try:
                    seq_num = int(val)
                except ValueError as e:
                    raise FIXParseError(f"Invalid MsgSeqNum: {val!r}") from e
            else:
                parsed_fields[tag] = val

        if not msg_type:
            raise FIXParseError("Missing MsgType (35)")

        return cls(
            msg_type=msg_type,
            sender_comp_id=sender_comp_id,
            target_comp_id=target_comp_id,
            seq_num=seq_num,
            fields=parsed_fields,
            raw=data,
        )

    def to_bytes(self) -> bytes:
        """Serialize this message to raw FIX bytes.

        Returns:
            Raw FIX message bytes.
        """
        # Build body
        body_parts: list[bytes] = []
        body_parts.append(b"35=" + self.msg_type.encode() + b"\x01")
        body_parts.append(b"49=" + self.sender_comp_id.encode() + b"\x01")
        body_parts.append(b"56=" + self.target_comp_id.encode() + b"\x01")
        body_parts.append(b"34=" + str(self.seq_num).encode() + b"\x01")
        for tag, val in self.fields.items():
            body_parts.append(f"{tag}={val}".encode() + b"\x01")
        body = b"".join(body_parts)

        # Build header
        header = b"8=FIX.4.2\x01" + f"9={len(body)}\x01".encode()

        # Compute checksum
        full = header + body
        checksum = sum(full) % 256
        trailer = f"10={checksum:03d}\x01".encode()

        return full + trailer

    def get_field(self, tag: str) -> Optional[str]:
        """Get a field value by tag.

        Args:
            tag: The FIX field tag (e.g., "55" for Symbol).

        Returns:
            The field value, or None if not present.
        """
        return self.fields.get(tag)

    def is_heartbeat(self) -> bool:
        """Check if this is a heartbeat message (MsgType=0)."""
        return self.msg_type == "0"

    def is_test_request(self) -> bool:
        """Check if this is a test request (MsgType=1)."""
        return self.msg_type == "1"

    def is_resend_request(self) -> bool:
        """Check if this is a resend request (MsgType=2)."""
        return self.msg_type == "2"

    def is_logout(self) -> bool:
        """Check if this is a logout message (MsgType=5)."""
        return self.msg_type == "5"

    def is_logon(self) -> bool:
        """Check if this is a logon message (MsgType=A)."""
        return self.msg_type == "A"


# ---------------------------------------------------------------------------
# FIX Session
# ---------------------------------------------------------------------------

class FIXSession:
    """FIX 4.2 session layer with state machine, sequence numbers, and heartbeat."""

    def __init__(
        self,
        sender_comp_id: str,
        target_comp_id: str,
        heartbeat_interval: int = 30,
        encrypt_method: int = 0,
        reset_on_logon: bool = False,
    ) -> None:
        """Initialize a FIX session.

        Args:
            sender_comp_id: Sender's CompID.
            target_comp_id: Target's CompID.
            heartbeat_interval: Heartbeat interval in seconds.
            encrypt_method: Encryption method (0 = None).
            reset_on_logon: Whether to reset sequence numbers on logon.
        """
        self.sender_comp_id = sender_comp_id
        self.target_comp_id = target_comp_id
        self.heartbeat_interval = heartbeat_interval
        self.encrypt_method = encrypt_method
        self.reset_on_logon = reset_on_logon

        self.state = SessionState.DISCONNECTED
        self.next_send_seq_num = 1
        self.next_recv_seq_num = 1

        self.last_heartbeat_time: Optional[float] = None
        self.last_recv_time: Optional[float] = None

        self._gap_start: Optional[int] = None
        self._gap_end: Optional[int] = None
        self._has_duplicate = False
        self._has_seq_num_too_low = False

    # ------------------------------------------------------------------
    # State machine
    # ------------------------------------------------------------------

    def connect(self) -> None:
        """Transition to CONNECTING state."""
        if self.state == SessionState.DISCONNECTED:
            self.state = SessionState.CONNECTING

    def logon(self) -> None:
        """Transition to LOGGED_IN state.

        Raises:
            FIXSequenceError: If not in CONNECTING state.
        """
        if self.state != SessionState.CONNECTING:
            raise FIXSequenceError(
                f"Cannot logon from state {self.state.value}"
            )
        if self.reset_on_logon:
            self.reset_seq_nums()
        self.state = SessionState.LOGGED_IN

    def logout(self) -> None:
        """Transition to LOGGED_OUT state."""
        if self.state == SessionState.LOGGED_IN:
            self.state = SessionState.LOGGED_OUT

    def disconnect(self) -> None:
        """Transition to DISCONNECTED state."""
        self.state = SessionState.DISCONNECTED

    # ------------------------------------------------------------------
    # Sequence number management
    # ------------------------------------------------------------------

    def send_message(self, msg_type: str, fields: dict[str, str]) -> FIXMessage:
        """Build and send a FIX message.

        Args:
            msg_type: The FIX message type.
            fields: Additional fields to include.

        Returns:
            The built FIXMessage.

        Raises:
            FIXSequenceError: If not in LOGGED_IN state.
        """
        if self.state != SessionState.LOGGED_IN:
            raise FIXSequenceError(
                f"Cannot send message in state {self.state.value}"
            )
        msg = FIXMessage(
            msg_type=msg_type,
            sender_comp_id=self.sender_comp_id,
            target_comp_id=self.target_comp_id,
            seq_num=self.next_send_seq_num,
            fields=fields,
        )
        self.next_send_seq_num += 1
        return msg

    def receive_message(self, msg: FIXMessage) -> None:
        """Process a received FIX message.

        Args:
            msg: The received FIXMessage.

        Raises:
            FIXSequenceError: If not in LOGGED_IN state.
        """
        if self.state != SessionState.LOGGED_IN:
            raise FIXSequenceError(
                f"Cannot receive message in state {self.state.value}"
            )
        self.mark_message_received()
        seq = msg.seq_num
        if seq == self.next_recv_seq_num:
            self.next_recv_seq_num += 1
        elif seq > self.next_recv_seq_num:
            self._gap_start = self.next_recv_seq_num
            self._gap_end = seq - 1
            self.next_recv_seq_num = seq + 1
        else:
            # seq < next_recv_seq_num
            if seq == self.next_recv_seq_num - 1:
                self._has_duplicate = True
            else:
                self._has_seq_num_too_low = True

    def expect_seq_num(self, seq_num: int) -> None:
        """Set the expected next receive sequence number.

        Args:
            seq_num: The expected sequence number.
        """
        self.next_recv_seq_num = seq_num

    def reset_seq_nums(self) -> None:
        """Reset both send and receive sequence numbers to 1."""
        self.next_send_seq_num = 1
        self.next_recv_seq_num = 1
        self._gap_start = None
        self._gap_end = None
        self._has_duplicate = False
        self._has_seq_num_too_low = False

    # ------------------------------------------------------------------
    # Gap detection
    # ------------------------------------------------------------------

    def has_gap(self) -> bool:
        """Check if a sequence number gap has been detected."""
        return self._gap_start is not None

    @property
    def gap_start(self) -> Optional[int]:
        """Get the start of the detected gap."""
        return self._gap_start

    @property
    def gap_end(self) -> Optional[int]:
        """Get the end of the detected gap."""
        return self._gap_end

    def clear_gap(self) -> None:
        """Clear the gap state."""
        self._gap_start = None
        self._gap_end = None

    def has_duplicate(self) -> bool:
        """Check if a duplicate sequence number was detected."""
        return self._has_duplicate

    def has_seq_num_too_low(self) -> bool:
        """Check if a sequence number too low was detected."""
        return self._has_seq_num_too_low

    # ------------------------------------------------------------------
    # Heartbeat
    # ------------------------------------------------------------------

    def build_heartbeat(self, test_request_id: Optional[str] = None) -> FIXMessage:
        """Build a heartbeat message.

        Args:
            test_request_id: Optional TestReqID to include.

        Returns:
            A heartbeat FIXMessage.
        """
        fields: dict[str, str] = {}
        if test_request_id is not None:
            fields["112"] = test_request_id
        return FIXMessage(
            msg_type="0",
            sender_comp_id=self.sender_comp_id,
            target_comp_id=self.target_comp_id,
            seq_num=self.next_send_seq_num,
            fields=fields,
        )

    def mark_heartbeat_sent(self) -> None:
        """Mark that a heartbeat was sent."""
        self.last_heartbeat_time = time.time()

    def mark_message_received(self) -> None:
        """Mark that a message was received."""
        self.last_recv_time = time.time()

    def is_heartbeat_timed_out(self) -> bool:
        """Check if the heartbeat has timed out.

        Returns:
            True if the heartbeat interval has elapsed since the last heartbeat.
        """
        if self.last_heartbeat_time is None:
            return False
        return (time.time() - self.last_heartbeat_time) > self.heartbeat_interval

    # ------------------------------------------------------------------
    # Resend request
    # ------------------------------------------------------------------

    def build_resend_request(self) -> FIXMessage:
        """Build a resend request message.

        Returns:
            A resend request FIXMessage.
        """
        begin = self._gap_start if self._gap_start is not None else 1
        end = self._gap_end if self._gap_end is not None else 0
        return FIXMessage(
            msg_type="2",
            sender_comp_id=self.sender_comp_id,
            target_comp_id=self.target_comp_id,
            seq_num=self.next_send_seq_num,
            fields={"7": str(begin), "16": str(end)},
        )
