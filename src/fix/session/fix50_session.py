"""FIX 5.0 Session Layer — transport-independent session management.

FIX 5.0 introduces:
- Transport independence (session layer decoupled from transport)
- ApplVerID (tag 1128) for application version identification
- ApplExtID (tag 1156) for application extension identification
- CstmApplVerID (tag 1129) for custom application version identification
- Standard session establishment with Logon/Logout
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class FIXParseError(Exception):
    """Raised when a FIX message cannot be parsed."""


class FIXChecksumError(Exception):
    """Raised when a FIX message checksum is invalid."""


class FIXSequenceError(Exception):
    """Raised when a sequence number violation or invalid state transition occurs."""


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class SessionState(Enum):
    """FIX session states."""
    DISCONNECTED = auto()
    CONNECTING = auto()
    LOGGED_IN = auto()
    LOGGED_OUT = auto()


class TransportType(Enum):
    """Supported transport types."""
    IN_MEMORY = auto()
    TCP = auto()
    UDP = auto()
    FILE = auto()


# ---------------------------------------------------------------------------
# Transport layer (abstract)
# ---------------------------------------------------------------------------

class FIXTransport:
    """Abstract base class for FIX transport implementations."""

    def __init__(self, transport_type: TransportType):
        self.transport_type = transport_type

    def send(self, data: bytes) -> None:
        raise NotImplementedError

    def receive(self) -> Optional[bytes]:
        raise NotImplementedError

    def connect(self) -> None:
        raise NotImplementedError

    def disconnect(self) -> None:
        raise NotImplementedError


class InMemoryTransport(FIXTransport):
    """In-memory transport for testing and simulation."""

    def __init__(self):
        super().__init__(TransportType.IN_MEMORY)
        self.sent_messages: list[FIXMessage] = []
        self._incoming: list[FIXMessage] = []
        self.send_count: int = 0
        self.receive_count: int = 0
        self._connected: bool = False

    def send(self, data: bytes) -> None:
        msg = FIXMessage.from_bytes(data)
        self.sent_messages.append(msg)
        self.send_count += 1

    def receive(self) -> Optional[bytes]:
        if self._incoming:
            self.receive_count += 1
            msg = self._incoming.pop(0)
            return msg.to_bytes()
        return None

    def deliver(self, msg: FIXMessage) -> None:
        """Deliver an incoming message (simulates network receive)."""
        self._incoming.append(msg)

    def connect(self) -> None:
        self._connected = True

    def disconnect(self) -> None:
        self._connected = False

    @property
    def connected(self) -> bool:
        return self._connected


# ---------------------------------------------------------------------------
# FIX Message
# ---------------------------------------------------------------------------

@dataclass
class FIXMessage:
    """Represents a FIX 5.0 message."""

    msg_type: str
    sender_comp_id: str
    target_comp_id: str
    seq_num: int
    fields: dict[str, str] = field(default_factory=dict)
    raw: Optional[bytes] = None

    def get_field(self, tag: str) -> Optional[str]:
        """Get a field value by tag."""
        return self.fields.get(tag)

    def set_field(self, tag: str, value: str) -> None:
        """Set a field value."""
        self.fields[tag] = value

    def is_heartbeat(self) -> bool:
        return self.msg_type == "0"

    def is_test_request(self) -> bool:
        return self.msg_type == "1"

    def is_resend_request(self) -> bool:
        return self.msg_type == "2"

    def is_logout(self) -> bool:
        return self.msg_type == "5"

    def is_logon(self) -> bool:
        return self.msg_type == "A"

    def to_bytes(self) -> bytes:
        """Serialize the message to FIX 5.0 wire format."""
        body_parts = []
        body_parts.append(b"35=" + self.msg_type.encode() + b"\x01")
        body_parts.append(b"49=" + self.sender_comp_id.encode() + b"\x01")
        body_parts.append(b"56=" + self.target_comp_id.encode() + b"\x01")
        body_parts.append(b"34=" + str(self.seq_num).encode() + b"\x01")
        for tag, val in self.fields.items():
            body_parts.append(f"{tag}={val}".encode() + b"\x01")
        body = b"".join(body_parts)
        body_len = len(body)
        header = b"8=FIX.5.0\x01" + f"9={body_len}\x01".encode()
        full = header + body
        checksum = sum(full) % 256
        trailer = f"10={checksum:03d}\x01".encode()
        return full + trailer

    @classmethod
    def from_bytes(cls, data: bytes) -> FIXMessage:
        """Parse a FIX 5.0 message from raw bytes."""
        if not data:
            raise FIXParseError("Empty message")

        # Parse header - check BeginString first
        if not data.startswith(b"8=FIX.5.0\x01"):
            raise FIXParseError("Invalid BeginString, expected FIX.5.0")

        # Find the trailer (10=...)
        trailer_idx = data.rfind(b"10=")
        if trailer_idx == -1:
            raise FIXParseError("No trailer found")

        # Extract and verify checksum
        checksum_str = data[trailer_idx + 3:trailer_idx + 6]
        try:
            expected_checksum = int(checksum_str)
        except ValueError:
            raise FIXParseError("Invalid checksum format")

        actual_checksum = sum(data[:trailer_idx]) % 256
        if actual_checksum != expected_checksum:
            raise FIXChecksumError(
                f"Checksum mismatch: expected {expected_checksum}, got {actual_checksum}"
            )

        # Extract body length (9=...)
        bl_start = data.find(b"9=")
        if bl_start == -1:
            raise FIXParseError("No body length field found")
        bl_end = data.find(b"\x01", bl_start)
        if bl_end == -1:
            raise FIXParseError("Malformed body length field")
        try:
            body_len = int(data[bl_start + 2:bl_end])
        except ValueError:
            raise FIXParseError("Invalid body length")

        # Extract body
        body_start = bl_end + 1
        body_end = body_start + body_len
        body = data[body_start:body_end]

        # Parse body fields
        fields: dict[str, str] = {}
        msg_type = ""
        sender_comp_id = ""
        target_comp_id = ""
        seq_num = 0

        parts = body.split(b"\x01")
        for part in parts:
            if not part:
                continue
            eq_idx = part.find(b"=")
            if eq_idx == -1:
                continue
            tag = part[:eq_idx].decode()
            value = part[eq_idx + 1:].decode()

            if tag == "35":
                msg_type = value
            elif tag == "49":
                sender_comp_id = value
            elif tag == "56":
                target_comp_id = value
            elif tag == "34":
                seq_num = int(value)
            else:
                fields[tag] = value

        return cls(
            msg_type=msg_type,
            sender_comp_id=sender_comp_id,
            target_comp_id=target_comp_id,
            seq_num=seq_num,
            fields=fields,
            raw=data,
        )


# ---------------------------------------------------------------------------
# FIX Session
# ---------------------------------------------------------------------------

class FIXSession:
    """FIX 5.0 session with transport independence."""

    def __init__(
        self,
        sender_comp_id: str,
        target_comp_id: str,
        transport: Optional[FIXTransport] = None,
        heartbeat_interval: int = 30,
        encrypt_method: int = 0,
        reset_on_logon: bool = False,
        appl_ver_id: Optional[str] = None,
        appl_ext_id: Optional[str] = None,
        cstm_appl_ver_id: Optional[str] = None,
    ):
        self.sender_comp_id = sender_comp_id
        self.target_comp_id = target_comp_id
        self.transport = transport or InMemoryTransport()
        self.heartbeat_interval = heartbeat_interval
        self.encrypt_method = encrypt_method
        self.reset_on_logon = reset_on_logon
        self.appl_ver_id = appl_ver_id
        self.appl_ext_id = appl_ext_id
        self.cstm_appl_ver_id = cstm_appl_ver_id

        self.state = SessionState.DISCONNECTED
        self.next_send_seq_num = 1
        self.next_recv_seq_num = 1
        self.last_heartbeat_time: Optional[float] = None
        self.last_recv_time: Optional[float] = None

        self._gap_start: Optional[int] = None
        self._gap_end: Optional[int] = None
        self._has_duplicate = False
        self._has_seq_num_too_low = False

    @property
    def transport_type(self) -> TransportType:
        return self.transport.transport_type

    def set_transport(self, transport: FIXTransport) -> None:
        """Swap the transport layer."""
        self.transport = transport

    def connect(self) -> None:
        """Initiate connection."""
        if self.state == SessionState.DISCONNECTED:
            self.state = SessionState.CONNECTING
            self.transport.connect()

    def logon(self) -> None:
        """Send logon message and transition to LOGGED_IN."""
        if self.state != SessionState.CONNECTING:
            raise FIXSequenceError(
                f"Cannot logon from state {self.state.name}"
            )

        if self.reset_on_logon:
            self.next_send_seq_num = 1
            self.next_recv_seq_num = 1

        logon_fields: dict[str, str] = {
            "98": str(self.encrypt_method),
            "108": str(self.heartbeat_interval),
        }
        if self.appl_ver_id is not None:
            logon_fields["1128"] = self.appl_ver_id
        if self.appl_ext_id is not None:
            logon_fields["1156"] = self.appl_ext_id
        if self.cstm_appl_ver_id is not None:
            logon_fields["1129"] = self.cstm_appl_ver_id

        self._send_message("A", logon_fields)
        self.state = SessionState.LOGGED_IN

    def logout(self) -> None:
        """Send logout message and transition to LOGGED_OUT."""
        if self.state != SessionState.LOGGED_IN:
            raise FIXSequenceError(
                f"Cannot logout from state {self.state.name}"
            )
        self._send_message("5", {})
        self.state = SessionState.LOGGED_OUT

    def disconnect(self) -> None:
        """Disconnect and transition to DISCONNECTED."""
        self.transport.disconnect()
        self.state = SessionState.DISCONNECTED

    def send_message(self, msg_type: str, fields: dict[str, str]) -> FIXMessage:
        """Send a message (only when logged in)."""
        if self.state != SessionState.LOGGED_IN:
            raise FIXSequenceError(
                f"Cannot send message in state {self.state.name}"
            )
        return self._send_message(msg_type, fields)

    def _send_message(self, msg_type: str, fields: dict[str, str]) -> FIXMessage:
        """Internal: build and send a message."""
        msg = FIXMessage(
            msg_type=msg_type,
            sender_comp_id=self.sender_comp_id,
            target_comp_id=self.target_comp_id,
            seq_num=self.next_send_seq_num,
            fields=fields,
        )
        self.next_send_seq_num += 1
        self.transport.send(msg.to_bytes())
        return msg

    def receive_message(self, msg: FIXMessage) -> None:
        """Process an incoming message."""
        if self.state != SessionState.LOGGED_IN:
            raise FIXSequenceError(
                f"Cannot receive message in state {self.state.name}"
            )

        self.last_recv_time = time.time()

        if msg.seq_num == self.next_recv_seq_num:
            self.next_recv_seq_num += 1
        elif msg.seq_num > self.next_recv_seq_num:
            self._gap_start = self.next_recv_seq_num
            self._gap_end = msg.seq_num - 1
            self.next_recv_seq_num = msg.seq_num + 1
        else:
            if msg.seq_num == self.next_recv_seq_num - 1:
                self._has_duplicate = True
            else:
                self._has_seq_num_too_low = True

    def expect_seq_num(self, seq_num: int) -> None:
        """Set the expected next receive sequence number."""
        self.next_recv_seq_num = seq_num

    @property
    def gap_start(self) -> Optional[int]:
        return self._gap_start

    @property
    def gap_end(self) -> Optional[int]:
        return self._gap_end

    def has_gap(self) -> bool:
        return self._gap_start is not None

    def clear_gap(self) -> None:
        self._gap_start = None
        self._gap_end = None

    def has_duplicate(self) -> bool:
        return self._has_duplicate

    def has_seq_num_too_low(self) -> bool:
        return self._has_seq_num_too_low

    def reset_seq_nums(self) -> None:
        self.next_send_seq_num = 1
        self.next_recv_seq_num = 1

    def mark_heartbeat_sent(self) -> None:
        self.last_heartbeat_time = time.time()

    def mark_message_received(self) -> None:
        self.last_recv_time = time.time()

    def is_heartbeat_timed_out(self) -> bool:
        if self.last_heartbeat_time is None:
            return False
        return (time.time() - self.last_heartbeat_time) > self.heartbeat_interval

    def build_heartbeat(self, test_request_id: Optional[str] = None) -> FIXMessage:
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

    def build_resend_request(self) -> FIXMessage:
        return FIXMessage(
            msg_type="2",
            sender_comp_id=self.sender_comp_id,
            target_comp_id=self.target_comp_id,
            seq_num=self.next_send_seq_num,
            fields={
                "7": str(self._gap_start or self.next_recv_seq_num),
                "16": str(self._gap_end or self.next_recv_seq_num - 1),
            },
        )
