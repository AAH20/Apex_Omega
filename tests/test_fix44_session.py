"""Tests for FIX 4.4 Session Layer — TDD: write tests first, watch them fail."""
import pytest
import time
from src.fix.session.fix44_session import (
    FIXMessage,
    FIXSession,
    SessionState,
    PartyID,
    FIXParseError,
    FIXChecksumError,
    FIXSequenceError,
    FIXSessionError,
)


# ---------------------------------------------------------------------------
# FIXMessage parsing tests
# ---------------------------------------------------------------------------

class TestFIXMessageParsing:
    """Test parsing of raw FIX 4.4 messages into structured objects."""

    def _build_raw_msg(self, body_fields: dict, seq_num=1, sender="SENDER", target="TARGET",
                       msg_type="D") -> bytes:
        """Helper to build a raw FIX 4.4 message."""
        body_parts = []
        body_parts.append(b"35=" + msg_type.encode() + b"\x01")
        body_parts.append(b"49=" + sender.encode() + b"\x01")
        body_parts.append(b"56=" + target.encode() + b"\x01")
        body_parts.append(b"34=" + str(seq_num).encode() + b"\x01")
        for tag, val in body_fields.items():
            body_parts.append(f"{tag}={val}".encode() + b"\x01")
        body = b"".join(body_parts)
        body_len = len(body)
        header = b"8=FIX.4.4\x01" + f"9={body_len}\x01".encode()
        full = header + body
        checksum = sum(full) % 256
        trailer = f"10={checksum:03d}\x01".encode()
        return full + trailer

    def test_parse_basic_message(self):
        raw = self._build_raw_msg({"55": "AAPL", "54": "1", "38": "100"})
        msg = FIXMessage.from_bytes(raw)
        assert msg.msg_type == "D"
        assert msg.sender_comp_id == "SENDER"
        assert msg.target_comp_id == "TARGET"
        assert msg.seq_num == 1
        assert msg.get_field("55") == "AAPL"
        assert msg.get_field("54") == "1"
        assert msg.get_field("38") == "100"

    def test_parse_message_with_multiple_fields(self):
        raw = self._build_raw_msg({"55": "MSFT", "54": "2", "38": "500", "44": "150.25", "40": "1"})
        msg = FIXMessage.from_bytes(raw)
        assert msg.get_field("55") == "MSFT"
        assert msg.get_field("44") == "150.25"
        assert msg.get_field("40") == "1"

    def test_parse_message_missing_body_length_raises(self):
        raw = b"8=FIX.4.4\x019=\x0135=D\x01"
        with pytest.raises(FIXParseError):
            FIXMessage.from_bytes(raw)

    def test_parse_message_bad_checksum_raises(self):
        raw = self._build_raw_msg({"55": "AAPL"})
        corrupted = raw[:-4] + b"10=000\x01"
        with pytest.raises(FIXChecksumError):
            FIXMessage.from_bytes(corrupted)

    def test_parse_message_wrong_begin_string_raises(self):
        raw = b"8=FIX.4.2\x019=10\x0135=D\x0110=000\x01"
        with pytest.raises(FIXParseError):
            FIXMessage.from_bytes(raw)

    def test_parse_message_empty_raises(self):
        with pytest.raises(FIXParseError):
            FIXMessage.from_bytes(b"")

    def test_parse_message_no_trailer_raises(self):
        raw = b"8=FIX.4.4\x019=10\x0135=D\x01"
        with pytest.raises(FIXParseError):
            FIXMessage.from_bytes(raw)

    def test_parse_message_with_spaces_in_values(self):
        raw = self._build_raw_msg({"55": "BRK A", "112": "test order"})
        msg = FIXMessage.from_bytes(raw)
        assert msg.get_field("55") == "BRK A"
        assert msg.get_field("112") == "test order"

    def test_parse_message_preserves_raw_bytes(self):
        raw = self._build_raw_msg({"55": "AAPL"})
        msg = FIXMessage.from_bytes(raw)
        assert msg.raw == raw

    def test_parse_message_is_heartbeat(self):
        raw = self._build_raw_msg({}, msg_type="0")
        msg = FIXMessage.from_bytes(raw)
        assert msg.is_heartbeat() is True

    def test_parse_message_is_not_heartbeat(self):
        raw = self._build_raw_msg({"55": "AAPL"}, msg_type="D")
        msg = FIXMessage.from_bytes(raw)
        assert msg.is_heartbeat() is False

    def test_parse_message_is_test_request(self):
        raw = self._build_raw_msg({"112": "TEST123"}, msg_type="1")
        msg = FIXMessage.from_bytes(raw)
        assert msg.is_test_request() is True

    def test_parse_message_is_resend_request(self):
        raw = self._build_raw_msg({"7": "2", "16": "5"}, msg_type="2")
        msg = FIXMessage.from_bytes(raw)
        assert msg.is_resend_request() is True

    def test_parse_message_is_logout(self):
        raw = self._build_raw_msg({}, msg_type="5")
        msg = FIXMessage.from_bytes(raw)
        assert msg.is_logout() is True

    def test_parse_message_is_logon(self):
        raw = self._build_raw_msg({"98": "0", "108": "30"}, msg_type="A")
        msg = FIXMessage.from_bytes(raw)
        assert msg.is_logon() is True

    def test_parse_message_is_sequence_reset(self):
        raw = self._build_raw_msg({"123": "Y", "36": "10"}, msg_type="4")
        msg = FIXMessage.from_bytes(raw)
        assert msg.is_sequence_reset() is True

    def test_parse_message_is_reject(self):
        raw = self._build_raw_msg({"45": "1", "373": "1"}, msg_type="3")
        msg = FIXMessage.from_bytes(raw)
        assert msg.is_reject() is True

    def test_parse_message_with_next_expected_seq_num(self):
        """FIX 4.4 specific: NextExpectedMsgSeqNum (789)."""
        raw = self._build_raw_msg({"98": "0", "108": "30", "789": "5"}, msg_type="A")
        msg = FIXMessage.from_bytes(raw)
        assert msg.get_field("789") == "5"

    def test_parse_message_with_default_appl_ver_id(self):
        """FIX 4.4 specific: DefaultApplVerID (1137)."""
        raw = self._build_raw_msg({"98": "0", "108": "30", "1137": "9"}, msg_type="A")
        msg = FIXMessage.from_bytes(raw)
        assert msg.get_field("1137") == "9"

    def test_parse_message_with_max_message_size(self):
        """FIX 4.4 specific: MaxMessageSize (383)."""
        raw = self._build_raw_msg({"98": "0", "108": "30", "383": "2048"}, msg_type="A")
        msg = FIXMessage.from_bytes(raw)
        assert msg.get_field("383") == "2048"

    def test_parse_message_with_username_password(self):
        """FIX 4.4 specific: Username (553) and Password (554)."""
        raw = self._build_raw_msg({"98": "0", "108": "30", "553": "user1", "554": "pass1"}, msg_type="A")
        msg = FIXMessage.from_bytes(raw)
        assert msg.get_field("553") == "user1"
        assert msg.get_field("554") == "pass1"

    def test_parse_message_with_reset_seq_num_flag(self):
        """FIX 4.4 specific: ResetSeqNumFlag (141)."""
        raw = self._build_raw_msg({"98": "0", "108": "30", "141": "Y"}, msg_type="A")
        msg = FIXMessage.from_bytes(raw)
        assert msg.get_field("141") == "Y"

    def test_parse_message_with_party_ids(self):
        """FIX 4.4 specific: Parties component block."""
        raw = self._build_raw_msg({
            "453": "2",
            "448": "PARTY1", "447": "D", "452": "1",
            "448": "PARTY2", "447": "D", "452": "2",
        }, msg_type="D")
        msg = FIXMessage.from_bytes(raw)
        assert msg.get_field("453") == "2"


# ---------------------------------------------------------------------------
# FIXMessage building tests
# ---------------------------------------------------------------------------

class TestFIXMessageBuilding:
    """Test building FIX 4.4 messages from structured data."""

    def test_build_message_produces_valid_bytes(self):
        msg = FIXMessage(msg_type="D", sender_comp_id="SENDER", target_comp_id="TARGET",
                         seq_num=1, fields={"55": "AAPL", "54": "1", "38": "100"})
        raw = msg.to_bytes()
        assert raw.startswith(b"8=FIX.4.4\x01")
        assert b"35=D\x01" in raw
        assert b"49=SENDER\x01" in raw
        assert b"56=TARGET\x01" in raw
        assert b"34=1\x01" in raw
        assert b"55=AAPL\x01" in raw
        assert raw.endswith(b"\x01")

    def test_build_message_checksum_is_correct(self):
        msg = FIXMessage(msg_type="0", sender_comp_id="S", target_comp_id="T", seq_num=1, fields={})
        raw = msg.to_bytes()
        trailer_start = raw.rfind(b"10=")
        checksum_str = raw[trailer_start + 3:trailer_start + 6]
        expected = sum(raw[:trailer_start]) % 256
        assert int(checksum_str) == expected

    def test_build_message_body_length_is_correct(self):
        msg = FIXMessage(msg_type="D", sender_comp_id="S", target_comp_id="T", seq_num=1,
                         fields={"55": "AAPL"})
        raw = msg.to_bytes()
        bl_start = raw.find(b"9=") + 2
        bl_end = raw.find(b"\x01", bl_start)
        body_len = int(raw[bl_start:bl_end])
        body_start = bl_end + 1
        body_end = raw.rfind(b"10=")
        actual_body_len = body_end - body_start
        assert body_len == actual_body_len

    def test_build_message_roundtrip(self):
        original = FIXMessage(msg_type="8", sender_comp_id="SENDER", target_comp_id="TARGET",
                              seq_num=42, fields={"55": "AAPL", "38": "100", "17": "EXEC1"})
        raw = original.to_bytes()
        parsed = FIXMessage.from_bytes(raw)
        assert parsed.msg_type == "8"
        assert parsed.sender_comp_id == "SENDER"
        assert parsed.target_comp_id == "TARGET"
        assert parsed.seq_num == 42
        assert parsed.get_field("55") == "AAPL"
        assert parsed.get_field("17") == "EXEC1"

    def test_build_message_with_empty_fields(self):
        msg = FIXMessage(msg_type="0", sender_comp_id="S", target_comp_id="T", seq_num=1, fields={})
        raw = msg.to_bytes()
        parsed = FIXMessage.from_bytes(raw)
        assert parsed.msg_type == "0"
        assert parsed.seq_num == 1

    def test_build_logon_with_fix44_fields(self):
        """Build a Logon message with FIX 4.4 specific fields."""
        msg = FIXMessage(msg_type="A", sender_comp_id="SENDER", target_comp_id="TARGET",
                         seq_num=1, fields={
                             "98": "0", "108": "30", "141": "Y",
                             "789": "1", "1137": "9", "383": "2048",
                             "553": "user1", "554": "pass1",
                         })
        raw = msg.to_bytes()
        parsed = FIXMessage.from_bytes(raw)
        assert parsed.msg_type == "A"
        assert parsed.get_field("141") == "Y"
        assert parsed.get_field("789") == "1"
        assert parsed.get_field("1137") == "9"
        assert parsed.get_field("383") == "2048"
        assert parsed.get_field("553") == "user1"
        assert parsed.get_field("554") == "pass1"


# ---------------------------------------------------------------------------
# Sequence number management tests
# ---------------------------------------------------------------------------

class TestSequenceNumbers:
    """Test sequence number tracking and gap detection."""

    def test_initial_seq_num_is_one(self):
        session = FIXSession(sender_comp_id="SENDER", target_comp_id="TARGET")
        assert session.next_send_seq_num == 1
        assert session.next_recv_seq_num == 1

    def test_send_increments_seq_num(self):
        session = FIXSession(sender_comp_id="SENDER", target_comp_id="TARGET")
        msg1 = session.send_message("D", {"55": "AAPL"})
        msg2 = session.send_message("D", {"55": "MSFT"})
        assert msg1.seq_num == 1
        assert msg2.seq_num == 2
        assert session.next_send_seq_num == 3

    def test_recv_accepts_expected_seq_num(self):
        session = FIXSession(sender_comp_id="SENDER", target_comp_id="TARGET")
        session.expect_seq_num(1)
        session.receive_message(FIXMessage(msg_type="D", sender_comp_id="T", target_comp_id="S",
                                           seq_num=1, fields={}))
        assert session.next_recv_seq_num == 2

    def test_recv_detects_gap(self):
        session = FIXSession(sender_comp_id="SENDER", target_comp_id="TARGET")
        session.expect_seq_num(1)
        session.receive_message(FIXMessage(msg_type="D", sender_comp_id="T", target_comp_id="S",
                                           seq_num=3, fields={}))
        assert session.has_gap() is True
        assert session.gap_start == 1
        assert session.gap_end == 2

    def test_recv_detects_duplicate(self):
        session = FIXSession(sender_comp_id="SENDER", target_comp_id="TARGET")
        session.expect_seq_num(1)
        session.receive_message(FIXMessage(msg_type="D", sender_comp_id="T", target_comp_id="S",
                                           seq_num=1, fields={}))
        session.receive_message(FIXMessage(msg_type="D", sender_comp_id="T", target_comp_id="S",
                                           seq_num=1, fields={}))
        assert session.has_duplicate() is True

    def test_recv_detects_seq_num_too_low(self):
        session = FIXSession(sender_comp_id="SENDER", target_comp_id="TARGET")
        session.expect_seq_num(5)
        session.receive_message(FIXMessage(msg_type="D", sender_comp_id="T", target_comp_id="S",
                                           seq_num=3, fields={}))
        assert session.has_seq_num_too_low() is True

    def test_seq_num_reset(self):
        session = FIXSession(sender_comp_id="SENDER", target_comp_id="TARGET")
        session.send_message("D", {"55": "AAPL"})
        session.send_message("D", {"55": "MSFT"})
        assert session.next_send_seq_num == 3
        session.reset_seq_nums()
        assert session.next_send_seq_num == 1
        assert session.next_recv_seq_num == 1

    def test_gap_cleared_after_resend(self):
        session = FIXSession(sender_comp_id="SENDER", target_comp_id="TARGET")
        session.expect_seq_num(1)
        session.receive_message(FIXMessage(msg_type="D", sender_comp_id="T", target_comp_id="S",
                                           seq_num=3, fields={}))
        assert session.has_gap() is True
        session.clear_gap()
        assert session.has_gap() is False


# ---------------------------------------------------------------------------
# Heartbeat tests
# ---------------------------------------------------------------------------

class TestHeartbeat:
    """Test heartbeat timeout detection and sending."""

    def test_heartbeat_not_timed_out_initially(self):
        session = FIXSession(sender_comp_id="SENDER", target_comp_id="TARGET", heartbeat_interval=30)
        assert session.is_heartbeat_timed_out() is False

    def test_heartbeat_timed_out_after_interval(self):
        session = FIXSession(sender_comp_id="SENDER", target_comp_id="TARGET", heartbeat_interval=1)
        session.mark_heartbeat_sent()
        time.sleep(1.1)
        assert session.is_heartbeat_timed_out() is True

    def test_heartbeat_not_timed_out_within_interval(self):
        session = FIXSession(sender_comp_id="SENDER", target_comp_id="TARGET", heartbeat_interval=30)
        session.mark_heartbeat_sent()
        assert session.is_heartbeat_timed_out() is False

    def test_heartbeat_message_built_correctly(self):
        session = FIXSession(sender_comp_id="SENDER", target_comp_id="TARGET", heartbeat_interval=30)
        hb = session.build_heartbeat()
        assert hb.msg_type == "0"
        assert hb.sender_comp_id == "SENDER"
        assert hb.target_comp_id == "TARGET"

    def test_heartbeat_with_test_request_id(self):
        session = FIXSession(sender_comp_id="SENDER", target_comp_id="TARGET", heartbeat_interval=30)
        hb = session.build_heartbeat(test_request_id="REQ123")
        assert hb.get_field("112") == "REQ123"

    def test_heartbeat_sent_updates_timestamp(self):
        session = FIXSession(sender_comp_id="SENDER", target_comp_id="TARGET", heartbeat_interval=30)
        assert session.last_heartbeat_time is None
        session.mark_heartbeat_sent()
        assert session.last_heartbeat_time is not None

    def test_heartbeat_received_updates_timestamp(self):
        session = FIXSession(sender_comp_id="SENDER", target_comp_id="TARGET", heartbeat_interval=30)
        assert session.last_recv_time is None
        session.mark_message_received()
        assert session.last_recv_time is not None

    def test_heartbeat_interval_customizable(self):
        session = FIXSession(sender_comp_id="SENDER", target_comp_id="TARGET", heartbeat_interval=60)
        assert session.heartbeat_interval == 60


# ---------------------------------------------------------------------------
# Session state machine tests
# ---------------------------------------------------------------------------

class TestSessionStateMachine:
    """Test session state transitions."""

    def test_initial_state_is_disconnected(self):
        session = FIXSession(sender_comp_id="SENDER", target_comp_id="TARGET")
        assert session.state == SessionState.DISCONNECTED

    def test_connect_transitions_to_connecting(self):
        session = FIXSession(sender_comp_id="SENDER", target_comp_id="TARGET")
        session.connect()
        assert session.state == SessionState.CONNECTING

    def test_logon_transitions_to_logged_in(self):
        session = FIXSession(sender_comp_id="SENDER", target_comp_id="TARGET")
        session.connect()
        session.logon()
        assert session.state == SessionState.LOGGED_IN

    def test_logout_transitions_to_logged_out(self):
        session = FIXSession(sender_comp_id="SENDER", target_comp_id="TARGET")
        session.connect()
        session.logon()
        session.logout()
        assert session.state == SessionState.LOGGED_OUT

    def test_disconnect_transitions_to_disconnected(self):
        session = FIXSession(sender_comp_id="SENDER", target_comp_id="TARGET")
        session.connect()
        session.logon()
        session.disconnect()
        assert session.state == SessionState.DISCONNECTED

    def test_invalid_transition_raises(self):
        session = FIXSession(sender_comp_id="SENDER", target_comp_id="TARGET")
        with pytest.raises(FIXSequenceError):
            session.logon()

    def test_state_transitions_are_idempotent(self):
        session = FIXSession(sender_comp_id="SENDER", target_comp_id="TARGET")
        session.connect()
        session.connect()
        assert session.state == SessionState.CONNECTING

    def test_can_send_only_when_logged_in(self):
        session = FIXSession(sender_comp_id="SENDER", target_comp_id="TARGET")
        session.connect()
        session.logon()
        msg = session.send_message("D", {"55": "AAPL"})
        assert msg.seq_num == 1

    def test_can_receive_only_when_logged_in(self):
        session = FIXSession(sender_comp_id="SENDER", target_comp_id="TARGET")
        session.connect()
        session.logon()
        msg = FIXMessage(msg_type="D", sender_comp_id="T", target_comp_id="S",
                         seq_num=1, fields={})
        session.receive_message(msg)
        assert session.next_recv_seq_num == 2

    def test_session_tracks_comp_ids(self):
        session = FIXSession(sender_comp_id="SENDER", target_comp_id="TARGET")
        assert session.sender_comp_id == "SENDER"
        assert session.target_comp_id == "TARGET"

    def test_session_heartbeat_interval_stored(self):
        session = FIXSession(sender_comp_id="SENDER", target_comp_id="TARGET", heartbeat_interval=45)
        assert session.heartbeat_interval == 45

    def test_session_stores_encrypt_method(self):
        session = FIXSession(sender_comp_id="SENDER", target_comp_id="TARGET", encrypt_method=0)
        assert session.encrypt_method == 0

    def test_session_stores_reset_flag(self):
        session = FIXSession(sender_comp_id="SENDER", target_comp_id="TARGET", reset_on_logon=True)
        assert session.reset_on_logon is True

    def test_full_lifecycle(self):
        session = FIXSession(sender_comp_id="SENDER", target_comp_id="TARGET")
        assert session.state == SessionState.DISCONNECTED
        session.connect()
        assert session.state == SessionState.CONNECTING
        session.logon()
        assert session.state == SessionState.LOGGED_IN
        msg = session.send_message("D", {"55": "AAPL"})
        assert msg.seq_num == 1
        session.logout()
        assert session.state == SessionState.LOGGED_OUT
        session.disconnect()
        assert session.state == SessionState.DISCONNECTED


# ---------------------------------------------------------------------------
# FIX 4.4 Session Reset tests
# ---------------------------------------------------------------------------

class TestSessionReset:
    """Test FIX 4.4 specific session reset functionality."""

    def test_reset_seq_num_flag_in_logon(self):
        """ResetSeqNumFlag (141) in Logon resets sequence numbers."""
        session = FIXSession(sender_comp_id="SENDER", target_comp_id="TARGET", reset_on_logon=True)
        session.connect()
        session.logon()
        # After logon with reset flag, seq nums should be 1
        assert session.next_send_seq_num == 1
        assert session.next_recv_seq_num == 1

    def test_reset_seq_num_flag_builds_logon_with_flag(self):
        """Logon message should include ResetSeqNumFlag when configured."""
        session = FIXSession(sender_comp_id="SENDER", target_comp_id="TARGET", reset_on_logon=True)
        session.connect()
        logon_msg = session.build_logon()
        assert logon_msg.get_field("141") == "Y"

    def test_no_reset_seq_num_flag_by_default(self):
        """By default, ResetSeqNumFlag should not be set."""
        session = FIXSession(sender_comp_id="SENDER", target_comp_id="TARGET")
        session.connect()
        logon_msg = session.build_logon()
        assert logon_msg.get_field("141") is None

    def test_reset_seq_nums_resets_both_directions(self):
        """Resetting sequence numbers resets both send and receive."""
        session = FIXSession(sender_comp_id="SENDER", target_comp_id="TARGET")
        session.connect()
        session.logon()
        session.send_message("D", {"55": "AAPL"})
        session.send_message("D", {"55": "MSFT"})
        session.send_message("D", {"55": "GOOG"})
        assert session.next_send_seq_num == 4
        session.reset_seq_nums()
        assert session.next_send_seq_num == 1
        assert session.next_recv_seq_num == 1

    def test_sequence_reset_message_gap_fill(self):
        """Sequence Reset with GapFillFlag=Y is gap fill mode."""
        session = FIXSession(sender_comp_id="SENDER", target_comp_id="TARGET")
        session.connect()
        session.logon()
        sr = session.build_sequence_reset(gap_fill=True, new_seq_num=10)
        assert sr.msg_type == "4"
        assert sr.get_field("123") == "Y"
        assert sr.get_field("36") == "10"

    def test_sequence_reset_message_reset_mode(self):
        """Sequence Reset with GapFillFlag=N is reset mode."""
        session = FIXSession(sender_comp_id="SENDER", target_comp_id="TARGET")
        session.connect()
        session.logon()
        sr = session.build_sequence_reset(gap_fill=False, new_seq_num=1)
        assert sr.msg_type == "4"
        assert sr.get_field("123") == "N"
        assert sr.get_field("36") == "1"

    def test_next_expected_msg_seq_num_in_logon(self):
        """FIX 4.4 Logon should support NextExpectedMsgSeqNum (789)."""
        session = FIXSession(sender_comp_id="SENDER", target_comp_id="TARGET")
        session.connect()
        logon_msg = session.build_logon(next_expected_seq_num=10)
        assert logon_msg.get_field("789") == "10"

    def test_default_appl_ver_id_in_logon(self):
        """FIX 4.4 Logon should support DefaultApplVerID (1137)."""
        session = FIXSession(sender_comp_id="SENDER", target_comp_id="TARGET")
        session.connect()
        logon_msg = session.build_logon(default_appl_ver_id="9")
        assert logon_msg.get_field("1137") == "9"

    def test_max_message_size_in_logon(self):
        """FIX 4.4 Logon should support MaxMessageSize (383)."""
        session = FIXSession(sender_comp_id="SENDER", target_comp_id="TARGET")
        session.connect()
        logon_msg = session.build_logon(max_message_size=4096)
        assert logon_msg.get_field("383") == "4096"

    def test_username_password_in_logon(self):
        """FIX 4.4 Logon should support Username (553) and Password (554)."""
        session = FIXSession(sender_comp_id="SENDER", target_comp_id="TARGET")
        session.connect()
        logon_msg = session.build_logon(username="trader1", password="secret")
        assert logon_msg.get_field("553") == "trader1"
        assert logon_msg.get_field("554") == "secret"


# ---------------------------------------------------------------------------
# Party ID support tests
# ---------------------------------------------------------------------------

class TestPartyID:
    """Test FIX 4.4 party ID support."""

    def test_party_id_creation(self):
        party = PartyID(party_id="PARTY1", party_id_source="D", party_role=1)
        assert party.party_id == "PARTY1"
        assert party.party_id_source == "D"
        assert party.party_role == 1

    def test_party_id_with_sub_ids(self):
        party = PartyID(party_id="PARTY1", party_id_source="D", party_role=1,
                        party_sub_ids=[("SUB1", "1"), ("SUB2", "2")])
        assert len(party.party_sub_ids) == 2

    def test_party_id_in_message(self):
        """Party IDs should be included in outgoing messages."""
        session = FIXSession(sender_comp_id="SENDER", target_comp_id="TARGET")
        session.connect()
        session.logon()
        party = PartyID(party_id="EXEC_BROKER", party_id_source="D", party_role=1)
        msg = session.send_message("D", {"55": "AAPL"}, party_ids=[party])
        assert msg.get_field("453") == "1"
        assert msg.get_field("448") == "EXEC_BROKER"

    def test_multiple_party_ids_in_message(self):
        """Multiple party IDs should be included in outgoing messages."""
        session = FIXSession(sender_comp_id="SENDER", target_comp_id="TARGET")
        session.connect()
        session.logon()
        parties = [
            PartyID(party_id="PARTY1", party_id_source="D", party_role=1),
            PartyID(party_id="PARTY2", party_id_source="D", party_role=2),
        ]
        msg = session.send_message("D", {"55": "AAPL"}, party_ids=parties)
        assert msg.get_field("453") == "2"

    def test_party_id_source_values(self):
        """PartyIDSource should support standard FIX 4.4 values."""
        # D = BIC, A = CUSIP, etc.
        party = PartyID(party_id="BANK1", party_id_source="D", party_role=1)
        assert party.party_id_source == "D"

    def test_party_role_values(self):
        """PartyRole should support standard FIX 4.4 values."""
        # 1 = Executing Firm, 2 = Broker of Credit, etc.
        party = PartyID(party_id="FIRM1", party_id_source="D", party_role=1)
        assert party.party_role == 1


# ---------------------------------------------------------------------------
# Integration-style tests
# ---------------------------------------------------------------------------

class TestFIXSessionIntegration:
    """Integration tests combining multiple features."""

    def test_send_and_receive_roundtrip(self):
        session = FIXSession(sender_comp_id="SENDER", target_comp_id="TARGET")
        session.connect()
        session.logon()
        sent = session.send_message("D", {"55": "AAPL", "38": "100"})
        received = FIXMessage.from_bytes(sent.to_bytes())
        session.receive_message(received)
        assert session.next_recv_seq_num == 2

    def test_heartbeat_during_session(self):
        session = FIXSession(sender_comp_id="SENDER", target_comp_id="TARGET", heartbeat_interval=30)
        session.connect()
        session.logon()
        hb = session.build_heartbeat()
        assert hb.msg_type == "0"
        session.send_message("0", {})
        assert session.next_send_seq_num == 2

    def test_gap_detection_triggers_resend_request(self):
        session = FIXSession(sender_comp_id="SENDER", target_comp_id="TARGET")
        session.connect()
        session.logon()
        session.receive_message(FIXMessage(msg_type="D", sender_comp_id="T", target_comp_id="S",
                                           seq_num=5, fields={}))
        assert session.has_gap() is True
        rr = session.build_resend_request()
        assert rr.msg_type == "2"
        assert rr.get_field("7") == "1"
        assert rr.get_field("16") == "4"

    def test_multiple_messages_in_sequence(self):
        session = FIXSession(sender_comp_id="SENDER", target_comp_id="TARGET")
        session.connect()
        session.logon()
        for i in range(1, 6):
            msg = session.send_message("D", {"55": f"SYM{i}"})
            assert msg.seq_num == i
        assert session.next_send_seq_num == 6

    def test_session_with_custom_heartbeat_interval(self):
        session = FIXSession(sender_comp_id="SENDER", target_comp_id="TARGET", heartbeat_interval=120)
        session.connect()
        session.logon()
        assert session.heartbeat_interval == 120
        hb = session.build_heartbeat()
        assert hb.msg_type == "0"

    def test_full_logon_with_all_fix44_fields(self):
        """Test a complete Logon exchange with all FIX 4.4 fields."""
        session = FIXSession(sender_comp_id="SENDER", target_comp_id="TARGET",
                             heartbeat_interval=30, reset_on_logon=True)
        session.connect()
        logon = session.build_logon(
            next_expected_seq_num=1,
            default_appl_ver_id="9",
            max_message_size=4096,
            username="trader1",
            password="secret",
        )
        assert logon.msg_type == "A"
        assert logon.get_field("98") == "0"
        assert logon.get_field("108") == "30"
        assert logon.get_field("141") == "Y"
        assert logon.get_field("789") == "1"
        assert logon.get_field("1137") == "9"
        assert logon.get_field("383") == "4096"
        assert logon.get_field("553") == "trader1"
        assert logon.get_field("554") == "secret"

    def test_logout_with_text(self):
        """Test Logout message with Text field."""
        session = FIXSession(sender_comp_id="SENDER", target_comp_id="TARGET")
        session.connect()
        session.logon()
        logout = session.build_logout(text="End of session")
        assert logout.msg_type == "5"
        assert logout.get_field("58") == "End of session"

    def test_reject_message(self):
        """Test Reject message with session reject reason."""
        session = FIXSession(sender_comp_id="SENDER", target_comp_id="TARGET")
        session.connect()
        session.logon()
        reject = session.build_reject(ref_seq_num=5, ref_msg_type="D",
                                      session_reject_reason=1, text="Required field missing")
        assert reject.msg_type == "3"
        assert reject.get_field("45") == "5"
        assert reject.get_field("372") == "D"
        assert reject.get_field("373") == "1"
        assert reject.get_field("58") == "Required field missing"

    def test_test_request_message(self):
        """Test Test Request message."""
        session = FIXSession(sender_comp_id="SENDER", target_comp_id="TARGET")
        session.connect()
        session.logon()
        tr = session.build_test_request(test_req_id="TEST1")
        assert tr.msg_type == "1"
        assert tr.get_field("112") == "TEST1"

    def test_resend_request_message(self):
        """Test Resend Request message."""
        session = FIXSession(sender_comp_id="SENDER", target_comp_id="TARGET")
        session.connect()
        session.logon()
        rr = session.build_resend_request(begin_seq_no=1, end_seq_no=10)
        assert rr.msg_type == "2"
        assert rr.get_field("7") == "1"
        assert rr.get_field("16") == "10"
