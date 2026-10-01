"""
FIX Protocol Integration Tests — Full Session Lifecycle.

Tests complete FIX session flows: logon, heartbeat, order flow, logout,
gap recovery, session reset, and drop-copy independence.

Target venues: Bloomberg (FIX 4.2/4.4), Tradeweb (FIX 4.2), MarketAxess (FIX 4.2/5.0 SP2).
"""

from __future__ import annotations

import sys
import time
import unittest
from pathlib import Path

# Add fix_harness to path
HARNESS_DIR = Path(__file__).resolve().parents[2] / "src" / "fix_harness"
sys.path.insert(0, str(HARNESS_DIR))

from fix_parser import (
    FIXParser,
    FIXMessage,
    FIXVersion,
    FIXParseError,
    RepeatingGroup,
    build_fix_message,
    NO_RELATED_SYM,
    NO_LEGS,
    NO_PARTY_IDS,
    NO_NESTED_PARTY_IDS,
)
from session_validator import (
    SessionValidator,
    ValidationResult,
    RejectOnRejectDetector,
    SessionState,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SOH = "\x01"


def current_timestamp() -> str:
    """Get current timestamp in FIX format."""
    return time.strftime("%Y%m%d-%H:%M:%S", time.gmtime())


def make_logon(seq_num: int, heartbeat_interval: int = 30) -> bytes:
    """Build a Logon (MsgType=A) message."""
    fields = [
        (35, "A"),
        (49, "SENDER"),
        (56, "TARGET"),
        (34, str(seq_num)),
        (52, current_timestamp()),
        (98, "0"),  # EncryptMethod = None
        (108, str(heartbeat_interval)),  # HeartBtInt
    ]
    return build_fix_message(FIXVersion.FIX_4_2, "A", fields)


def make_heartbeat(seq_num: int, test_req_id: str | None = None) -> bytes:
    """Build a Heartbeat (MsgType=0) message."""
    fields = [
        (35, "0"),
        (49, "SENDER"),
        (56, "TARGET"),
        (34, str(seq_num)),
        (52, current_timestamp()),
    ]
    if test_req_id:
        fields.append((112, test_req_id))  # TestReqID
    return build_fix_message(FIXVersion.FIX_4_2, "0", fields)


def make_test_request(seq_num: int, test_req_id: str = "TEST001") -> bytes:
    """Build a TestRequest (MsgType=1) message."""
    fields = [
        (35, "1"),
        (49, "SENDER"),
        (56, "TARGET"),
        (34, str(seq_num)),
        (52, current_timestamp()),
        (112, test_req_id),  # TestReqID
    ]
    return build_fix_message(FIXVersion.FIX_4_2, "1", fields)


def make_new_order_single(
    seq_num: int,
    cl_oid: str = "ORD001",
    symbol: str = "AAPL",
    side: str = "1",
    qty: str = "100",
    ord_type: str = "1",
    time_in_force: str = "0",
) -> bytes:
    """Build a NewOrderSingle (MsgType=D) message."""
    fields = [
        (35, "D"),
        (49, "SENDER"),
        (56, "TARGET"),
        (34, str(seq_num)),
        (52, current_timestamp()),
        (11, cl_oid),  # ClOrdID
        (54, side),  # Side
        (38, qty),  # OrderQty
        (40, ord_type),  # OrdType
        (59, time_in_force),  # TimeInForce
    ]
    groups = {
        NO_RELATED_SYM: [
            [(55, symbol), (65, "4"), (48, f"US{hash(symbol) % 10000000000:010d}"), (22, "1")],
        ],
    }
    return build_fix_message(FIXVersion.FIX_4_2, "D", fields, groups)


def make_execution_report(
    seq_num: int,
    exec_id: str = "EXEC001",
    cl_oid: str = "ORD001",
    exec_type: str = "0",
    ord_status: str = "0",
    side: str = "1",
    qty: str = "100",
    price: str = "150.00",
) -> bytes:
    """Build an ExecutionReport (MsgType=8) message."""
    fields = [
        (35, "8"),
        (49, "SENDER"),
        (56, "TARGET"),
        (34, str(seq_num)),
        (52, current_timestamp()),
        (37, exec_id),  # OrderID
        (11, cl_oid),  # ClOrdID
        (17, exec_id),  # ExecID
        (150, exec_type),  # ExecType
        (39, ord_status),  # OrdStatus
        (54, side),  # Side
        (38, qty),  # OrderQty
        (44, price),  # Price
    ]
    return build_fix_message(FIXVersion.FIX_4_2, "8", fields)


def make_order_cancel_request(
    seq_num: int,
    cl_oid: str = "CAN001",
    orig_cl_oid: str = "ORD001",
    symbol: str = "AAPL",
    side: str = "1",
) -> bytes:
    """Build an OrderCancelRequest (MsgType=F) message."""
    fields = [
        (35, "F"),
        (49, "SENDER"),
        (56, "TARGET"),
        (34, str(seq_num)),
        (52, current_timestamp()),
        (11, cl_oid),  # ClOrdID
        (41, orig_cl_oid),  # OrigClOrdID
        (54, side),  # Side
    ]
    groups = {
        NO_RELATED_SYM: [
            [(55, symbol), (65, "4"), (48, f"US{hash(symbol) % 10000000000:010d}"), (22, "1")],
        ],
    }
    return build_fix_message(FIXVersion.FIX_4_2, "F", fields, groups)


def make_logout(seq_num: int, text: str = "Session complete") -> bytes:
    """Build a Logout (MsgType=5) message."""
    fields = [
        (35, "5"),
        (49, "SENDER"),
        (56, "TARGET"),
        (34, str(seq_num)),
        (52, current_timestamp()),
        (58, text),  # Text
    ]
    return build_fix_message(FIXVersion.FIX_4_2, "5", fields)


def make_reject(seq_num: int, ref_seq_num: int = 0, reason: str = "Invalid tag") -> bytes:
    """Build a Reject (MsgType=3) message."""
    fields = [
        (35, "3"),
        (49, "SENDER"),
        (56, "TARGET"),
        (34, str(seq_num)),
        (52, current_timestamp()),
        (45, str(ref_seq_num)),  # RefSeqNum
        (58, reason),  # Text
    ]
    return build_fix_message(FIXVersion.FIX_4_2, "3", fields)


def make_resend_request(seq_num: int, begin_seq: int, end_seq: int = 0) -> bytes:
    """Build a ResendRequest (MsgType=2) message."""
    fields = [
        (35, "2"),
        (49, "SENDER"),
        (56, "TARGET"),
        (34, str(seq_num)),
        (52, current_timestamp()),
        (7, str(begin_seq)),  # BeginSeqNo
        (16, str(end_seq)),  # EndSeqNo
    ]
    return build_fix_message(FIXVersion.FIX_4_2, "2", fields)


def make_sequence_reset(seq_num: int, new_seq_num: int, gap_fill: bool = True) -> bytes:
    """Build a SequenceReset (MsgType=4) message."""
    fields = [
        (35, "4"),
        (49, "SENDER"),
        (56, "TARGET"),
        (34, str(seq_num)),
        (52, current_timestamp()),
        (36, str(new_seq_num)),  # NewSeqNum
    ]
    if gap_fill:
        fields.append((123, "Y"))  # GapFillFlag
    return build_fix_message(FIXVersion.FIX_4_2, "4", fields)


# ---------------------------------------------------------------------------
# Integration Test: Full Session Lifecycle
# ---------------------------------------------------------------------------

class TestFIXSessionLifecycle(unittest.TestCase):
    """Integration tests for complete FIX session lifecycle."""

    def setUp(self):
        self.parser = FIXParser(FIXVersion.FIX_4_2)
        self.validator = SessionValidator(self.parser)
        self.session_id = "INTEGRATION_SESSION"

    def test_01_logon_handshake(self):
        """Test logon message establishes session with correct sequence number."""
        raw = make_logon(1, heartbeat_interval=30)
        msg = self.parser.parse(raw)
        result = self.validator.validate_message(msg, self.session_id)

        self.assertTrue(result.is_valid, f"Logon failed: {result.errors}")
        self.assertEqual(msg.msg_type, "A")
        self.assertEqual(msg.get_field(98), "0")  # EncryptMethod
        self.assertEqual(msg.get_field(108), "30")  # HeartBtInt

        session = self.validator.sessions[self.session_id]
        self.assertEqual(session.expected_seq_num, 2)

    def test_02_heartbeat_flow(self):
        """Test heartbeat exchange after logon."""
        # Logon
        logon = self.parser.parse(make_logon(1))
        self.validator.validate_message(logon, self.session_id)

        # Heartbeat
        hb = self.parser.parse(make_heartbeat(2))
        result = self.validator.validate_message(hb, self.session_id)
        self.assertTrue(result.is_valid, f"Heartbeat failed: {result.errors}")
        self.assertEqual(hb.msg_type, "0")

        session = self.validator.sessions[self.session_id]
        self.assertEqual(session.expected_seq_num, 3)

    def test_03_test_request_response(self):
        """Test TestRequest/TestReqID heartbeat exchange."""
        # Logon
        logon = self.parser.parse(make_logon(1))
        self.validator.validate_message(logon, self.session_id)

        # TestRequest
        tr = self.parser.parse(make_test_request(2, "ALIVE001"))
        result = self.validator.validate_message(tr, self.session_id)
        self.assertTrue(result.is_valid)
        self.assertEqual(tr.msg_type, "1")
        self.assertEqual(tr.get_field(112), "ALIVE001")

        # Heartbeat with TestReqID response
        hb = self.parser.parse(make_heartbeat(3, test_req_id="ALIVE001"))
        result = self.validator.validate_message(hb, self.session_id)
        self.assertTrue(result.is_valid)
        self.assertEqual(hb.get_field(112), "ALIVE001")

    def test_04_new_order_single_flow(self):
        """Test NewOrderSingle with repeating groups passes validation."""
        # Logon
        logon = self.parser.parse(make_logon(1))
        self.validator.validate_message(logon, self.session_id)

        # NewOrderSingle
        nos = self.parser.parse(make_new_order_single(2, cl_oid="ORD001", symbol="AAPL"))
        result = self.validator.validate_message(nos, self.session_id)
        self.assertTrue(result.is_valid, f"NOS failed: {result.errors}")
        self.assertEqual(nos.msg_type, "D")
        self.assertEqual(nos.get_field(11), "ORD001")
        self.assertIn(NO_RELATED_SYM, nos.groups)

        session = self.validator.sessions[self.session_id]
        self.assertEqual(session.expected_seq_num, 3)

    def test_05_execution_report_flow(self):
        """Test ExecutionReport after NewOrderSingle."""
        # Logon
        logon = self.parser.parse(make_logon(1))
        self.validator.validate_message(logon, self.session_id)

        # NewOrderSingle
        nos = self.parser.parse(make_new_order_single(2, cl_oid="ORD001"))
        self.validator.validate_message(nos, self.session_id)

        # ExecutionReport (New)
        er = self.parser.parse(make_execution_report(3, exec_id="EXEC001", cl_oid="ORD001"))
        result = self.validator.validate_message(er, self.session_id)
        self.assertTrue(result.is_valid, f"ExecutionReport failed: {result.errors}")
        self.assertEqual(er.msg_type, "8")
        self.assertEqual(er.get_field(150), "0")  # ExecType = New
        self.assertEqual(er.get_field(39), "0")  # OrdStatus = New

    def test_06_order_cancel_request_flow(self):
        """Test OrderCancelRequest after order submission."""
        # Logon
        logon = self.parser.parse(make_logon(1))
        self.validator.validate_message(logon, self.session_id)

        # NewOrderSingle
        nos = self.parser.parse(make_new_order_single(2, cl_oid="ORD001"))
        self.validator.validate_message(nos, self.session_id)

        # OrderCancelRequest
        ocr = self.parser.parse(make_order_cancel_request(3, cl_oid="CAN001", orig_cl_oid="ORD001"))
        result = self.validator.validate_message(ocr, self.session_id)
        self.assertTrue(result.is_valid, f"Cancel request failed: {result.errors}")
        self.assertEqual(ocr.msg_type, "F")
        self.assertEqual(ocr.get_field(41), "ORD001")  # OrigClOrdID

    def test_07_logout_flow(self):
        """Test logout message closes session cleanly."""
        # Logon
        logon = self.parser.parse(make_logon(1))
        self.validator.validate_message(logon, self.session_id)

        # Some heartbeats
        for i in range(2, 5):
            hb = self.parser.parse(make_heartbeat(i))
            self.validator.validate_message(hb, self.session_id)

        # Logout
        lo = self.parser.parse(make_logout(5, text="Done"))
        result = self.validator.validate_message(lo, self.session_id)
        self.assertTrue(result.is_valid, f"Logout failed: {result.errors}")
        self.assertEqual(lo.msg_type, "5")
        self.assertEqual(lo.get_field(58), "Done")

        session = self.validator.sessions[self.session_id]
        self.assertEqual(session.expected_seq_num, 6)

    def test_08_full_order_lifecycle(self):
        """Test complete order lifecycle: logon → NOS → ER → cancel → logout."""
        # Logon
        logon = self.parser.parse(make_logon(1))
        self.validator.validate_message(logon, self.session_id)

        # NewOrderSingle
        nos = self.parser.parse(make_new_order_single(2, cl_oid="ORD001", symbol="AAPL", qty="100"))
        result = self.validator.validate_message(nos, self.session_id)
        self.assertTrue(result.is_valid)

        # ExecutionReport (New)
        er1 = self.parser.parse(make_execution_report(3, exec_id="EXEC001", cl_oid="ORD001", exec_type="0", ord_status="0"))
        result = self.validator.validate_message(er1, self.session_id)
        self.assertTrue(result.is_valid)

        # ExecutionReport (Fill)
        er2 = self.parser.parse(make_execution_report(4, exec_id="EXEC002", cl_oid="ORD001", exec_type="F", ord_status="2", price="150.00"))
        result = self.validator.validate_message(er2, self.session_id)
        self.assertTrue(result.is_valid)

        # Logout
        lo = self.parser.parse(make_logout(5, text="Order complete"))
        result = self.validator.validate_message(lo, self.session_id)
        self.assertTrue(result.is_valid)

        session = self.validator.sessions[self.session_id]
        self.assertEqual(session.expected_seq_num, 6)

    def test_09_gap_recovery_during_session(self):
        """Test gap detection and recovery mid-session."""
        # Logon
        logon = self.parser.parse(make_logon(1))
        self.validator.validate_message(logon, self.session_id)

        # Heartbeat 2
        hb2 = self.parser.parse(make_heartbeat(2))
        self.validator.validate_message(hb2, self.session_id)

        # Gap: skip seq 3, send 4
        hb4 = self.parser.parse(make_heartbeat(4))
        result = self.validator.validate_message(hb4, self.session_id)
        self.assertTrue(result.gap_fill_needed)
        self.assertEqual(result.gap_range, (3, 3))

        # ResendRequest for missing message
        rr = self.parser.parse(make_resend_request(5, begin_seq=3, end_seq=3))
        result = self.validator.validate_message(rr, self.session_id)
        self.assertTrue(result.is_valid)
        self.assertEqual(rr.msg_type, "2")

        # GapFill (SequenceReset) fills the gap
        gap_fill = self.parser.parse(make_sequence_reset(3, new_seq_num=6))
        result = self.validator.validate_message(gap_fill, self.session_id)
        self.assertTrue(result.is_valid)
        self.assertEqual(gap_fill.msg_type, "4")
        self.assertEqual(gap_fill.get_field(36), "6")

        session = self.validator.sessions[self.session_id]
        self.assertEqual(len(session.gap_ranges), 0)

    def test_10_session_reset(self):
        """Test SequenceReset to reset session sequence numbers."""
        # Logon
        logon = self.parser.parse(make_logon(1))
        self.validator.validate_message(logon, self.session_id)

        # Some messages
        for i in range(2, 6):
            hb = self.parser.parse(make_heartbeat(i))
            self.validator.validate_message(hb, self.session_id)

        # SequenceReset to new seq num
        reset = self.parser.parse(make_sequence_reset(6, new_seq_num=1, gap_fill=False))
        result = self.validator.validate_message(reset, self.session_id)
        self.assertTrue(result.is_valid)
        self.assertEqual(reset.msg_type, "4")
        self.assertEqual(reset.get_field(36), "1")

    def test_11_poss_dup_flag_retransmission(self):
        """Test PossDupFlag handling during retransmission."""
        # Logon
        logon = self.parser.parse(make_logon(1))
        self.validator.validate_message(logon, self.session_id)

        # Original message
        hb2 = self.parser.parse(make_heartbeat(2))
        self.validator.validate_message(hb2, self.session_id)

        # Retransmit with PossDupFlag=Y
        fields = [
            (35, "0"),
            (49, "SENDER"),
            (56, "TARGET"),
            (34, "2"),
            (52, current_timestamp()),
            (43, "Y"),  # PossDupFlag
            (122, current_timestamp()),  # OrigSendingTime
        ]
        retransmit = self.parser.parse(build_fix_message(FIXVersion.FIX_4_2, "0", fields))
        result = self.validator.validate_message(retransmit, self.session_id)
        self.assertTrue(result.is_valid, f"Retransmit failed: {result.errors}")

    def test_12_multiple_orders_session(self):
        """Test multiple orders in a single session."""
        # Logon
        logon = self.parser.parse(make_logon(1))
        self.validator.validate_message(logon, self.session_id)

        # Order 1
        nos1 = self.parser.parse(make_new_order_single(2, cl_oid="ORD001", symbol="AAPL", qty="100"))
        result = self.validator.validate_message(nos1, self.session_id)
        self.assertTrue(result.is_valid)

        # Order 2
        nos2 = self.parser.parse(make_new_order_single(3, cl_oid="ORD002", symbol="GOOG", qty="50"))
        result = self.validator.validate_message(nos2, self.session_id)
        self.assertTrue(result.is_valid)

        # Order 3
        nos3 = self.parser.parse(make_new_order_single(4, cl_oid="ORD003", symbol="MSFT", qty="200"))
        result = self.validator.validate_message(nos3, self.session_id)
        self.assertTrue(result.is_valid)

        # Execution reports
        for i, (exec_id, cl_oid) in enumerate([("EXEC001", "ORD001"), ("EXEC002", "ORD002"), ("EXEC003", "ORD003")], start=5):
            er = self.parser.parse(make_execution_report(i, exec_id=exec_id, cl_oid=cl_oid))
            result = self.validator.validate_message(er, self.session_id)
            self.assertTrue(result.is_valid)

        # Logout
        lo = self.parser.parse(make_logout(8, text="All orders complete"))
        result = self.validator.validate_message(lo, self.session_id)
        self.assertTrue(result.is_valid)

        session = self.validator.sessions[self.session_id]
        self.assertEqual(session.expected_seq_num, 9)

    def test_13_reject_handling_in_session(self):
        """Test Reject message handling during session."""
        # Logon
        logon = self.parser.parse(make_logon(1))
        self.validator.validate_message(logon, self.session_id)

        # Normal heartbeat
        hb = self.parser.parse(make_heartbeat(2))
        self.validator.validate_message(hb, self.session_id)

        # Reject message
        rej = self.parser.parse(make_reject(3, ref_seq_num=2, reason="Invalid tag"))
        result = self.validator.validate_message(rej, self.session_id)
        self.assertTrue(result.is_valid)
        self.assertEqual(rej.msg_type, "3")
        self.assertEqual(rej.get_field(45), "2")  # RefSeqNum

        # Session continues after reject
        hb2 = self.parser.parse(make_heartbeat(4))
        result = self.validator.validate_message(hb2, self.session_id)
        self.assertTrue(result.is_valid)

    def test_14_drop_copy_session_alongside_live(self):
        """Test drop-copy session runs independently alongside live session."""
        live_session = "LIVE_SESSION"
        drop_copy_session = "DROP_COPY_SESSION"

        # Logon both sessions
        logon = self.parser.parse(make_logon(1))
        self.validator.validate_message(logon, live_session)
        self.validator.validate_message(logon, drop_copy_session, is_drop_copy=True)

        # Live session: order flow
        nos = self.parser.parse(make_new_order_single(2, cl_oid="ORD001"))
        self.validator.validate_message(nos, live_session)

        er = self.parser.parse(make_execution_report(3, exec_id="EXEC001", cl_oid="ORD001"))
        self.validator.validate_message(er, live_session)

        # Drop-copy session: different sequence
        hb_dc = self.parser.parse(make_heartbeat(2))
        self.validator.validate_message(hb_dc, drop_copy_session, is_drop_copy=True)

        # Verify independence
        live = self.validator.sessions[live_session]
        drop_copy = self.validator.sessions[drop_copy_session]

        self.assertFalse(live.is_drop_copy)
        self.assertTrue(drop_copy.is_drop_copy)
        self.assertEqual(live.expected_seq_num, 4)
        self.assertEqual(drop_copy.expected_seq_num, 3)

    def test_15_large_order_with_repeating_groups(self):
        """Test large order with multiple NoRelatedSym and NoLegs groups."""
        # Logon
        logon = self.parser.parse(make_logon(1))
        self.validator.validate_message(logon, self.session_id)

        # Build large order with multiple symbols
        symbols = ["AAPL", "GOOG", "MSFT", "AMZN", "TSLA"]
        fields = [
            (35, "D"),
            (49, "SENDER"),
            (56, "TARGET"),
            (34, "2"),
            (52, current_timestamp()),
            (11, "BULK001"),
            (54, "1"),
            (38, "1000"),
            (40, "1"),
        ]
        groups = {
            NO_RELATED_SYM: [
                [(55, sym), (65, "4"), (48, f"US{hash(sym) % 10000000000:010d}"), (22, "1")]
                for sym in symbols
            ],
        }
        large_order = self.parser.parse(build_fix_message(FIXVersion.FIX_4_2, "D", fields, groups))
        result = self.validator.validate_message(large_order, self.session_id)
        self.assertTrue(result.is_valid, f"Large order failed: {result.errors}")
        self.assertEqual(large_order.groups[NO_RELATED_SYM].count, 5)

    def test_16_session_state_consistency(self):
        """Test session state remains consistent through complex flows."""
        # Logon
        logon = self.parser.parse(make_logon(1))
        self.validator.validate_message(logon, self.session_id)

        # Mix of message types
        messages = [
            make_heartbeat(2),
            make_new_order_single(3, cl_oid="ORD001"),
            make_execution_report(4, exec_id="EXEC001", cl_oid="ORD001"),
            make_heartbeat(5),
            make_order_cancel_request(6, cl_oid="CAN001", orig_cl_oid="ORD001"),
            make_heartbeat(7),
        ]

        for i, raw in enumerate(messages, start=2):
            msg = self.parser.parse(raw)
            result = self.validator.validate_message(msg, self.session_id)
            self.assertTrue(result.is_valid, f"Message {i} failed: {result.errors}")

        session = self.validator.sessions[self.session_id]
        self.assertEqual(session.expected_seq_num, 8)
        self.assertEqual(len(session.received_seq_nums), 7)

    def test_17_concurrent_sessions_isolation(self):
        """Test multiple concurrent sessions don't interfere."""
        session_a = "SESSION_A"
        session_b = "SESSION_B"

        # Both sessions logon
        logon_a = self.parser.parse(make_logon(1))
        self.validator.validate_message(logon_a, session_a)

        logon_b = self.parser.parse(make_logon(1))
        self.validator.validate_message(logon_b, session_b)

        # Session A: order flow
        nos_a = self.parser.parse(make_new_order_single(2, cl_oid="ORD_A"))
        self.validator.validate_message(nos_a, session_a)

        # Session B: different order flow
        nos_b = self.parser.parse(make_new_order_single(2, cl_oid="ORD_B"))
        self.validator.validate_message(nos_b, session_b)

        # Verify isolation
        session_a_state = self.validator.sessions[session_a]
        session_b_state = self.validator.sessions[session_b]

        self.assertEqual(session_a_state.expected_seq_num, 3)
        self.assertEqual(session_b_state.expected_seq_num, 3)
        self.assertNotEqual(session_a_state.session_id, session_b_state.session_id)

    def test_18_logout_then_reconnect(self):
        """Test session can reconnect after logout."""
        # First session
        logon1 = self.parser.parse(make_logon(1))
        self.validator.validate_message(logon1, self.session_id)

        hb = self.parser.parse(make_heartbeat(2))
        self.validator.validate_message(hb, self.session_id)

        lo = self.parser.parse(make_logout(3, text="Bye"))
        self.validator.validate_message(lo, self.session_id)

        # Reconnect with new session
        new_session = "RECONNECT_SESSION"
        logon2 = self.parser.parse(make_logon(1))
        result = self.validator.validate_message(logon2, new_session)
        self.assertTrue(result.is_valid)

        session = self.validator.sessions[new_session]
        self.assertEqual(session.expected_seq_num, 2)

    def test_19_heartbeat_interval_compliance(self):
        """Test heartbeat interval is respected in session."""
        # Logon with 30s heartbeat
        logon = self.parser.parse(make_logon(1, heartbeat_interval=30))
        self.validator.validate_message(logon, self.session_id)

        self.assertEqual(logon.get_field(108), "30")

        # Multiple heartbeats within interval
        for i in range(2, 10):
            hb = self.parser.parse(make_heartbeat(i))
            result = self.validator.validate_message(hb, self.session_id)
            self.assertTrue(result.is_valid)

    def test_20_full_day_simulation(self):
        """Simulate a full trading day with mixed message types."""
        # Logon
        logon = self.parser.parse(make_logon(1))
        self.validator.validate_message(logon, self.session_id)

        seq = 2
        # Morning orders
        for i in range(5):
            nos = self.parser.parse(make_new_order_single(seq, cl_oid=f"ORD{seq:03d}", symbol=["AAPL", "GOOG", "MSFT", "AMZN", "TSLA"][i]))
            result = self.validator.validate_message(nos, self.session_id)
            self.assertTrue(result.is_valid)
            seq += 1

        # Execution reports
        for i in range(5):
            er = self.parser.parse(make_execution_report(seq, exec_id=f"EXEC{seq:03d}", cl_oid=f"ORD{seq:03d}"))
            result = self.validator.validate_message(er, self.session_id)
            self.assertTrue(result.is_valid)
            seq += 1

        # Mid-day heartbeats
        for _ in range(3):
            hb = self.parser.parse(make_heartbeat(seq))
            result = self.validator.validate_message(hb, self.session_id)
            self.assertTrue(result.is_valid)
            seq += 1

        # Afternoon cancels
        for i in range(2):
            ocr = self.parser.parse(make_order_cancel_request(seq, cl_oid=f"CAN{seq:03d}", orig_cl_oid=f"ORD{seq:03d}"))
            result = self.validator.validate_message(ocr, self.session_id)
            self.assertTrue(result.is_valid)
            seq += 1

        # End of day logout
        lo = self.parser.parse(make_logout(seq, text="EOD"))
        result = self.validator.validate_message(lo, self.session_id)
        self.assertTrue(result.is_valid)

        session = self.validator.sessions[self.session_id]
        self.assertEqual(session.expected_seq_num, seq + 1)
        self.assertEqual(len(session.received_seq_nums), seq)


if __name__ == "__main__":
    unittest.main()
