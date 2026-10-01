"""FIX 4.4 Protocol Engine — Session Layer.

Implements FIX 4.4 session-level protocol with:
- Session state machine (DISCONNECTED → CONNECTING → LOGGED_IN → LOGGED_OUT)
- Sequence number management with gap detection
- Heartbeat monitoring
- Session reset (ResetSeqNumFlag)
- Party ID support (Parties component block)
- All FIX 4.4 session messages: Logon, Logout, Heartbeat, Test Request,
  Resend Request, Reject, Sequence Reset
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

FIX_44_BEGIN_STRING = b"8=FIX.4.4\x01"
FIX_44_BEGIN_STRING_PREFIX = "8=FIX.4.4"

MSG_TYPE_LOGON = "A"
MSG_TYPE_LOGOUT = "5"
MSG_TYPE_HEARTBEAT = "0"
MSG_TYPE_TEST_REQUEST = "1"
MSG_TYPE_RESEND_REQUEST = "2"
MSG_TYPE_REJECT = "3"
MSG_TYPE_SEQUENCE_RESET = "4"

TAG_MSG_TYPE = "35"
TAG_SENDER_COMP_ID = "49"
TAG_TARGET_COMP_ID = "56"
TAG_MSG_SEQ_NUM = "34"
TAG_BEGIN_SEQ_NO = "7"
TAG_END_SEQ_NO = "16"
TAG_TEST_REQ_ID = "112"
TAG_GAP_FILL_FLAG = "123"
TAG_NEW_SEQ_NO = "36"
TAG_REF_SEQ_NUM = "45"
TAG_REF_MSG_TYPE = "372"
TAG_SESSION_REJECT_REASON = "373"
TAG_TEXT = "58"
TAG_ENCRYPT_METHOD = "98"
TAG_HEART_BT_INT = "108"
TAG_RESET_SEQ_NUM_FLAG = "141"
TAG_NEXT_EXPECTED_MSG_SEQ_NUM = "789"
TAG_DEFAULT_APPL_VER_ID = "1137"
TAG_MAX_MESSAGE_SIZE = "383"
TAG_USERNAME = "553"
TAG_PASSWORD = "554"
TAG_NO_PARTY_IDS = "453"
TAG_PARTY_ID = "448"
TAG_PARTY_ID_SOURCE = "447"
TAG_PARTY_ROLE = "452"
TAG_PARTY_SUB_ID_TYPE = "523"
TAG_PARTY_SUB_ID = "802"

ENCRYPT_METHOD_NONE = "0"

SESSION_REJECT_REASON_REQUIRED_TAG_MISSING = "1"
SESSION_REJECT_REASON_INVALID_TAG_NUMBER = "2"
SESSION_REJECT_REASON_TAG_NOT_DEFINED_FOR_THIS_MESSAGE_TYPE = "3"
SESSION_REJECT_REASON_UNDEFINED_TAG = "4"
SESSION_REJECT_REASON_TAG_SPECIFIED_WITHOUT_A_VALUE = "5"
SESSION_REJECT_REASON_VALUE_IS_INCORRECT = "6"
SESSION_REJECT_REASON_INCORRECT_DATA_FORMAT_FOR_VALUE = "7"
SESSION_REJECT_REASON_DECRYPTION_PROBLEM = "8"
SESSION_REJECT_REASON_SIGNATURE_PROBLEM = "9"
SESSION_REJECT_REASON_COMP_ID_PROBLEM = "10"
SESSION_REJECT_REASON_SENDING_TIME_ACCURACY_PROBLEM = "11"
SESSION_REJECT_REASON_INVALID_MSG_TYPE = "12"
SESSION_REJECT_REASON_XML_VALIDATION_ERROR = "13"
SESSION_REJECT_REASON_TAG_APPEARS_MORE_THAN_ONCE = "14"
SESSION_REJECT_REASON_TAG_SPECIFIED_OUT_OF_REQUIRED_ORDER = "15"
SESSION_REJECT_REASON_REPEATING_GROUP_FIELDS_OUT_OF_ORDER = "16"
SESSION_REJECT_REASON_INCORRECT_NUM_IN_GROUP_COUNT_FOR_REPEATING_GROUP = "17"
SESSION_REJECT_REASON_NON_DATA_VALUE_INCLUDES_FIELD_DELIMITER = "18"
SESSION_REJECT_REASON_INVALID_UNSUPPORTED_APPLICATION_VERSION = "19"
SESSION_REJECT_REASON_OTHER = "99"


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class FIXParseError(Exception):
    """Raised when a FIX message cannot be parsed."""
    pass


class FIXChecksumError(Exception):
    """Raised when a FIX message checksum is invalid."""
    pass


class FIXSequenceError(Exception):
    """Raised for sequence number errors or invalid state transitions."""
    pass


class FIXSessionError(Exception):
    """Raised for general session errors."""
    pass


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class SessionState(Enum):
    """FIX session state machine states."""
    DISCONNECTED = "DISCONNECTED"
    CONNECTING = "CONNECTING"
    LOGGED_IN = "LOGGED_IN"
    LOGGED_OUT = "LOGGED_OUT"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class PartyID:
    """FIX 4.4 Party ID (Parties component block entry)."""
    party_id: str
    party_id_source: str
    party_role: int
    party_sub_ids: list[tuple[str, str]] = field(default_factory=list)


@dataclass
class FIXMessage:
    """A FIX 4.4 message."""
    msg_type: str
    sender_comp_id: str
    target_comp_id: str
    seq_num: int
    fields: dict[str, str] = field(default_factory=dict)
    raw: Optional[bytes] = None

    def get_field(self, tag: str) -> Optional[str]:
        """Get a field value by tag."""
        return self.fields.get(tag)

    def is_heartbeat(self) -> bool:
        return self.msg_type == MSG_TYPE_HEARTBEAT

    def is_test_request(self) -> bool:
        return self.msg_type == MSG_TYPE_TEST_REQUEST

    def is_resend_request(self) -> bool:
        return self.msg_type == MSG_TYPE_RESEND_REQUEST

    def is_logout(self) -> bool:
        return self.msg_type == MSG_TYPE_LOGOUT

    def is_logon(self) -> bool:
        return self.msg_type == MSG_TYPE_LOGON

    def is_sequence_reset(self) -> bool:
        return self.msg_type == MSG_TYPE_SEQUENCE_RESET

    def is_reject(self) -> bool:
        return self.msg_type == MSG_TYPE_REJECT

    def to_bytes(self) -> bytes:
        """Serialize this message to FIX 4.4 wire format."""
        body_parts = []
        body_parts.append(f"{TAG_MSG_TYPE}={self.msg_type}".encode() + b"\x01")
        body_parts.append(f"{TAG_SENDER_COMP_ID}={self.sender_comp_id}".encode() + b"\x01")
        body_parts.append(f"{TAG_TARGET_COMP_ID}={self.target_comp_id}".encode() + b"\x01")
        body_parts.append(f"{TAG_MSG_SEQ_NUM}={self.seq_num}".encode() + b"\x01")
        for tag, val in self.fields.items():
            body_parts.append(f"{tag}={val}".encode() + b"\x01")
        body = b"".join(body_parts)
        body_len = len(body)
        header = FIX_44_BEGIN_STRING + f"9={body_len}\x01".encode()
        full = header + body
        checksum = sum(full) % 256
        trailer = f"10={checksum:03d}\x01".encode()
        return full + trailer

    @classmethod
    def from_bytes(cls, raw: bytes) -> FIXMessage:
        """Parse a raw FIX 4.4 message."""
        if not raw:
            raise FIXParseError("Empty message")

        # Check BeginString
        if not raw.startswith(FIX_44_BEGIN_STRING):
            raise FIXParseError(f"Invalid BeginString: expected FIX.4.4")

        # Find BodyLength
        bl_start = raw.find(b"9=")
        if bl_start == -1:
            raise FIXParseError("Missing BodyLength (9)")
        bl_end = raw.find(b"\x01", bl_start)
        if bl_end == -1:
            raise FIXParseError("Malformed BodyLength")
        try:
            body_len = int(raw[bl_start + 2:bl_end])
        except ValueError:
            raise FIXParseError("Invalid BodyLength value")

        # Find Checksum
        cs_start = raw.rfind(b"10=")
        if cs_start == -1:
            raise FIXParseError("Missing Checksum (10)")
        cs_end = raw.find(b"\x01", cs_start)
        if cs_end == -1:
            raise FIXParseError("Malformed Checksum")
        try:
            checksum = int(raw[cs_start + 3:cs_end])
        except ValueError:
            raise FIXParseError("Invalid Checksum value")

        # Verify checksum
        expected_checksum = sum(raw[:cs_start]) % 256
        if checksum != expected_checksum:
            raise FIXChecksumError(f"Checksum mismatch: expected {expected_checksum}, got {checksum}")

        # Parse body
        body_start = bl_end + 1
        body_end = cs_start
        # Remove trailing \x01 before 10=
        if raw[body_end - 1:body_end] == b"\x01":
            body_end -= 1
        body = raw[body_start:body_end]

        # Parse fields
        fields: dict[str, str] = {}
        msg_type = None
        sender_comp_id = None
        target_comp_id = None
        seq_num = None

        parts = body.split(b"\x01")
        for part in parts:
            if not part:
                continue
            eq_pos = part.find(b"=")
            if eq_pos == -1:
                raise FIXParseError(f"Malformed field: {part}")
            tag = part[:eq_pos].decode("ascii")
            val = part[eq_pos + 1:].decode("ascii")
            fields[tag] = val
            if tag == TAG_MSG_TYPE:
                msg_type = val
            elif tag == TAG_SENDER_COMP_ID:
                sender_comp_id = val
            elif tag == TAG_TARGET_COMP_ID:
                target_comp_id = val
            elif tag == TAG_MSG_SEQ_NUM:
                try:
                    seq_num = int(val)
                except ValueError:
                    raise FIXParseError(f"Invalid MsgSeqNum: {val}")

        if msg_type is None:
            raise FIXParseError("Missing MsgType (35)")
        if sender_comp_id is None:
            raise FIXParseError("Missing SenderCompID (49)")
        if target_comp_id is None:
            raise FIXParseError("Missing TargetCompID (56)")
        if seq_num is None:
            raise FIXParseError("Missing MsgSeqNum (34)")

        return cls(
            msg_type=msg_type,
            sender_comp_id=sender_comp_id,
            target_comp_id=target_comp_id,
            seq_num=seq_num,
            fields=fields,
            raw=raw,
        )


# ---------------------------------------------------------------------------
# Session
# ---------------------------------------------------------------------------

class FIXSession:
    """FIX 4.4 session with state machine, sequence numbers, and heartbeat."""

    def __init__(
        self,
        sender_comp_id: str,
        target_comp_id: str,
        heartbeat_interval: int = 30,
        encrypt_method: int = 0,
        reset_on_logon: bool = False,
    ):
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

        self.gap_start: Optional[int] = None
        self.gap_end: Optional[int] = None
        self.has_gap_flag = False
        self.has_duplicate_flag = False
        self.has_seq_num_too_low_flag = False

    # -- State machine --

    def connect(self) -> None:
        """Transition to CONNECTING state."""
        if self.state == SessionState.DISCONNECTED:
            self.state = SessionState.CONNECTING

    def logon(self) -> None:
        """Transition to LOGGED_IN state."""
        if self.state != SessionState.CONNECTING:
            raise FIXSequenceError(f"Cannot logon from state {self.state}")
        self.state = SessionState.LOGGED_IN
        if self.reset_on_logon:
            self.next_send_seq_num = 1
            self.next_recv_seq_num = 1

    def logout(self) -> None:
        """Transition to LOGGED_OUT state."""
        if self.state == SessionState.LOGGED_IN:
            self.state = SessionState.LOGGED_OUT

    def disconnect(self) -> None:
        """Transition to DISCONNECTED state."""
        self.state = SessionState.DISCONNECTED

    # -- Sequence numbers --

    def expect_seq_num(self, seq_num: int) -> None:
        """Set the expected next receive sequence number."""
        self.next_recv_seq_num = seq_num

    def reset_seq_nums(self) -> None:
        """Reset both send and receive sequence numbers to 1."""
        self.next_send_seq_num = 1
        self.next_recv_seq_num = 1

    def has_gap(self) -> bool:
        return self.has_gap_flag

    def has_duplicate(self) -> bool:
        return self.has_duplicate_flag

    def has_seq_num_too_low(self) -> bool:
        return self.has_seq_num_too_low_flag

    def clear_gap(self) -> None:
        self.has_gap_flag = False
        self.gap_start = None
        self.gap_end = None

    # -- Send/Receive --

    def send_message(self, msg_type: str, fields: dict[str, str],
                     party_ids: Optional[list[PartyID]] = None) -> FIXMessage:
        """Build and send a message, incrementing the send sequence number."""

        all_fields = dict(fields)
        if party_ids:
            all_fields[TAG_NO_PARTY_IDS] = str(len(party_ids))
            for pid in party_ids:
                all_fields[TAG_PARTY_ID] = pid.party_id
                all_fields[TAG_PARTY_ID_SOURCE] = pid.party_id_source
                all_fields[TAG_PARTY_ROLE] = str(pid.party_role)
                for sub_id_type, sub_id in pid.party_sub_ids:
                    all_fields[TAG_PARTY_SUB_ID_TYPE] = sub_id_type
                    all_fields[TAG_PARTY_SUB_ID] = sub_id

        msg = FIXMessage(
            msg_type=msg_type,
            sender_comp_id=self.sender_comp_id,
            target_comp_id=self.target_comp_id,
            seq_num=self.next_send_seq_num,
            fields=all_fields,
        )
        self.next_send_seq_num += 1
        self.last_heartbeat_time = time.time()
        return msg

    def receive_message(self, msg: FIXMessage) -> None:
        """Process a received message, checking sequence numbers."""

        self.last_recv_time = time.time()
        seq = msg.seq_num

        if seq == self.next_recv_seq_num:
            self.next_recv_seq_num += 1
        elif seq > self.next_recv_seq_num:
            self.has_gap_flag = True
            self.gap_start = self.next_recv_seq_num
            self.gap_end = seq - 1
            self.next_recv_seq_num = seq + 1
        else:
            if seq == self.next_recv_seq_num - 1:
                self.has_duplicate_flag = True
            else:
                self.has_seq_num_too_low_flag = True

    # -- Heartbeat --

    def mark_heartbeat_sent(self) -> None:
        self.last_heartbeat_time = time.time()

    def mark_message_received(self) -> None:
        self.last_recv_time = time.time()

    def is_heartbeat_timed_out(self) -> bool:
        if self.last_heartbeat_time is None:
            return False
        return (time.time() - self.last_heartbeat_time) > self.heartbeat_interval

    def build_heartbeat(self, test_request_id: Optional[str] = None) -> FIXMessage:
        fields = {}
        if test_request_id is not None:
            fields[TAG_TEST_REQ_ID] = test_request_id
        return FIXMessage(
            msg_type=MSG_TYPE_HEARTBEAT,
            sender_comp_id=self.sender_comp_id,
            target_comp_id=self.target_comp_id,
            seq_num=self.next_send_seq_num,
            fields=fields,
        )

    # -- Message builders --

    def build_logon(
        self,
        next_expected_seq_num: Optional[int] = None,
        default_appl_ver_id: Optional[str] = None,
        max_message_size: Optional[int] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
    ) -> FIXMessage:
        """Build a Logon (35=A) message with FIX 4.4 fields."""
        fields: dict[str, str] = {
            TAG_ENCRYPT_METHOD: str(self.encrypt_method),
            TAG_HEART_BT_INT: str(self.heartbeat_interval),
        }
        if self.reset_on_logon:
            fields[TAG_RESET_SEQ_NUM_FLAG] = "Y"
        if next_expected_seq_num is not None:
            fields[TAG_NEXT_EXPECTED_MSG_SEQ_NUM] = str(next_expected_seq_num)
        if default_appl_ver_id is not None:
            fields[TAG_DEFAULT_APPL_VER_ID] = default_appl_ver_id
        if max_message_size is not None:
            fields[TAG_MAX_MESSAGE_SIZE] = str(max_message_size)
        if username is not None:
            fields[TAG_USERNAME] = username
        if password is not None:
            fields[TAG_PASSWORD] = password

        return FIXMessage(
            msg_type=MSG_TYPE_LOGON,
            sender_comp_id=self.sender_comp_id,
            target_comp_id=self.target_comp_id,
            seq_num=self.next_send_seq_num,
            fields=fields,
        )

    def build_logout(self, text: Optional[str] = None) -> FIXMessage:
        """Build a Logout (35=5) message."""
        fields = {}
        if text is not None:
            fields[TAG_TEXT] = text
        return FIXMessage(
            msg_type=MSG_TYPE_LOGOUT,
            sender_comp_id=self.sender_comp_id,
            target_comp_id=self.target_comp_id,
            seq_num=self.next_send_seq_num,
            fields=fields,
        )

    def build_test_request(self, test_req_id: str) -> FIXMessage:
        """Build a Test Request (35=1) message."""
        return FIXMessage(
            msg_type=MSG_TYPE_TEST_REQUEST,
            sender_comp_id=self.sender_comp_id,
            target_comp_id=self.target_comp_id,
            seq_num=self.next_send_seq_num,
            fields={TAG_TEST_REQ_ID: test_req_id},
        )

    def build_resend_request(self, begin_seq_no: Optional[int] = None,
                             end_seq_no: Optional[int] = None) -> FIXMessage:
        """Build a Resend Request (35=2) message."""
        if begin_seq_no is None:
            begin_seq_no = self.gap_start if self.gap_start else self.next_recv_seq_num
        if end_seq_no is None:
            end_seq_no = self.gap_end if self.gap_end else begin_seq_no
        return FIXMessage(
            msg_type=MSG_TYPE_RESEND_REQUEST,
            sender_comp_id=self.sender_comp_id,
            target_comp_id=self.target_comp_id,
            seq_num=self.next_send_seq_num,
            fields={
                TAG_BEGIN_SEQ_NO: str(begin_seq_no),
                TAG_END_SEQ_NO: str(end_seq_no),
            },
        )

    def build_sequence_reset(self, gap_fill: bool, new_seq_num: int) -> FIXMessage:
        """Build a Sequence Reset (35=4) message."""
        return FIXMessage(
            msg_type=MSG_TYPE_SEQUENCE_RESET,
            sender_comp_id=self.sender_comp_id,
            target_comp_id=self.target_comp_id,
            seq_num=self.next_send_seq_num,
            fields={
                TAG_GAP_FILL_FLAG: "Y" if gap_fill else "N",
                TAG_NEW_SEQ_NO: str(new_seq_num),
            },
        )

    def build_reject(self, ref_seq_num: int, ref_msg_type: Optional[str] = None,
                     session_reject_reason: Optional[int] = None,
                     text: Optional[str] = None) -> FIXMessage:
        """Build a Reject (35=3) message."""
        fields: dict[str, str] = {
            TAG_REF_SEQ_NUM: str(ref_seq_num),
        }
        if ref_msg_type is not None:
            fields[TAG_REF_MSG_TYPE] = ref_msg_type
        if session_reject_reason is not None:
            fields[TAG_SESSION_REJECT_REASON] = str(session_reject_reason)
        if text is not None:
            fields[TAG_TEXT] = text
        return FIXMessage(
            msg_type=MSG_TYPE_REJECT,
            sender_comp_id=self.sender_comp_id,
            target_comp_id=self.target_comp_id,
            seq_num=self.next_send_seq_num,
            fields=fields,
        )
