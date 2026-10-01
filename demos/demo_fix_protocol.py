#!/usr/bin/env python3
"""
demo_fix_protocol.py — Apex_Omega FIX Protocol Demo

Demonstrates FIX (Financial Information eXchange) protocol message building
and parsing. Covers:
- FIX message construction with proper field ordering
- Checksum calculation
- Message parsing and field extraction
- Common FIX message types (New Order Single, Execution Report, Market Data)

Usage:
    python demo_fix_protocol.py
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


# FIX field constants
class FixTag:
    BEGIN_STRING = 8
    BODY_LENGTH = 9
    MSG_TYPE = 35
    SENDER_COMP_ID = 49
    TARGET_COMP_ID = 56
    MSG_SEQ_NUM = 34
    SENDING_TIME = 52
    CL_ORD_ID = 11
    SYMBOL = 55
    SIDE = 54
    ORDER_QTY = 38
    ORD_TYPE = 40
    PRICE = 44
    TIME_IN_FORCE = 59
    EXEC_ID = 17
    EXEC_TYPE = 150
    ORD_STATUS = 39
    CUM_QTY = 14
    AVG_PX = 6
    LEAVES_QTY = 151
    MD_REQ_ID = 262
    MD_UPDATE_ACTION = 279
    MD_ENTRY_TYPE = 269
    MD_ENTRY_PX = 270
    MD_ENTRY_SIZE = 271
    CHECKSUM = 10


class FixMsgType:
    HEARTBEAT = "0"
    TEST_REQUEST = "1"
    RESEND_REQUEST = "2"
    REJECT = "3"
    SEQUENCE_RESET = "4"
    LOGOUT = "5"
    NEW_ORDER_SINGLE = "D"
    EXECUTION_REPORT = "8"
    ORDER_CANCEL_REJECT = "9"
    MARKET_DATA_SNAPSHOT = "W"


class Side:
    BUY = "1"
    SELL = "2"


class OrdType:
    MARKET = "1"
    LIMIT = "2"


class OrdStatus:
    NEW = "0"
    PARTIALLY_FILLED = "1"
    FILLED = "2"
    CANCELLED = "4"
    REJECTED = "8"


class ExecType:
    NEW = "0"
    PARTIAL_FILL = "1"
    FILL = "2"
    CANCELLED = "4"
    REJECTED = "8"


class TimeInForce:
    DAY = "0"
    GOOD_TILL_CANCEL = "1"
    AT_THE_OPEN = "2"
    IMMEDIATE_OR_CANCEL = "3"
    FILL_OR_KILL = "4"


SOH = "\x01"


def calculate_checksum(message_body: str) -> int:
    """Calculate FIX checksum (sum of all bytes mod 256)."""
    return sum(ord(c) for c in message_body) % 256


def format_checksum(checksum: int) -> str:
    """Format checksum as 3-digit zero-padded string."""
    return f"{checksum:03d}"


def build_fix_message(fields: dict[int, str]) -> str:
    """Build a complete FIX message from a dict of tag->value."""
    # Exclude BeginString from body — it goes in the header only
    body_fields = {k: v for k, v in fields.items() if k != FixTag.BEGIN_STRING}

    # Build body (everything between BodyLength and Checksum)
    body_parts = []
    for tag in sorted(body_fields.keys()):
        body_parts.append(f"{tag}={body_fields[tag]}")
    body = SOH.join(body_parts) + SOH

    # Calculate body length (everything after BodyLength field, up to but not including Checksum)
    body_length = len(body)

    # Build header
    header = f"8=FIX.4.2{SOH}9={body_length}{SOH}"

    # Full message without checksum
    msg_without_checksum = header + body

    # Calculate checksum
    checksum = calculate_checksum(msg_without_checksum)

    # Complete message
    complete_msg = f"{msg_without_checksum}10={format_checksum(checksum)}{SOH}"

    return complete_msg


def parse_fix_message(message: str) -> dict[int, str]:
    """Parse a FIX message and return a dict of tag->value."""
    fields = {}
    # Split by SOH
    parts = message.split(SOH)
    for part in parts:
        if "=" in part:
            tag_str, value = part.split("=", 1)
            try:
                tag = int(tag_str)
                fields[tag] = value
            except ValueError:
                pass
    return fields


def get_field_name(tag: int) -> str:
    """Return human-readable name for a FIX tag."""
    names = {
        8: "BeginString",
        9: "BodyLength",
        35: "MsgType",
        49: "SenderCompID",
        56: "TargetCompID",
        34: "MsgSeqNum",
        52: "SendingTime",
        11: "ClOrdID",
        55: "Symbol",
        54: "Side",
        38: "OrderQty",
        40: "OrdType",
        44: "Price",
        59: "TimeInForce",
        17: "ExecID",
        150: "ExecType",
        39: "OrdStatus",
        14: "CumQty",
        6: "AvgPx",
        151: "LeftsQty",
        262: "MDReqID",
        279: "MDUpdateAction",
        269: "MDEntryType",
        270: "MDEntryPx",
        271: "MDEntrySize",
        10: "CheckSum",
    }
    return names.get(tag, f"Tag{tag}")


def get_msg_type_name(msg_type: str) -> str:
    """Return human-readable name for a FIX message type."""
    names = {
        "0": "Heartbeat",
        "1": "TestRequest",
        "2": "ResendRequest",
        "3": "Reject",
        "4": "SequenceReset",
        "5": "Logout",
        "D": "NewOrderSingle",
        "8": "ExecutionReport",
        "9": "OrderCancelReject",
        "W": "MarketDataSnapshot",
    }
    return names.get(msg_type, f"Unknown({msg_type})")


def display_fix_message(message: str, title: str = "FIX Message") -> None:
    """Display a FIX message in a readable format."""
    print(f"\n  {title}:")
    print(f"  Raw: {message.replace(SOH, '|')}")
    print(f"\n  {'Tag':<6} {'Name':<20} {'Value':<20}")
    print(f"  {'-'*6} {'-'*20} {'-'*20}")

    fields = parse_fix_message(message)
    for tag in sorted(fields.keys()):
        name = get_field_name(tag)
        value = fields[tag]
        print(f"  {tag:<6} {name:<20} {value:<20}")


def build_new_order_single(
    cl_ord_id: str,
    symbol: str,
    side: str,
    quantity: int,
    ord_type: str,
    price: Optional[float] = None,
    time_in_force: str = TimeInForce.DAY,
) -> str:
    """Build a FIX NewOrderSingle (MsgType=D) message."""
    fields = {
        FixTag.BEGIN_STRING: "FIX.4.2",
        FixTag.MSG_TYPE: FixMsgType.NEW_ORDER_SINGLE,
        FixTag.SENDER_COMP_ID: "APEX_OMEGA",
        FixTag.TARGET_COMP_ID: "EXCHANGE",
        FixTag.MSG_SEQ_NUM: "1",
        FixTag.SENDING_TIME: "20240115-10:30:00.000",
        FixTag.CL_ORD_ID: cl_ord_id,
        FixTag.SYMBOL: symbol,
        FixTag.SIDE: side,
        FixTag.ORDER_QTY: str(quantity),
        FixTag.ORD_TYPE: ord_type,
        FixTag.TIME_IN_FORCE: time_in_force,
    }
    if price is not None:
        fields[FixTag.PRICE] = f"{price:.2f}"

    return build_fix_message(fields)


def build_execution_report(
    exec_id: str,
    cl_ord_id: str,
    symbol: str,
    side: str,
    ord_status: str,
    exec_type: str,
    cum_qty: int,
    leaves_qty: int,
    avg_px: float,
    last_qty: Optional[int] = None,
    last_px: Optional[float] = None,
) -> str:
    """Build a FIX ExecutionReport (MsgType=8) message."""
    fields = {
        FixTag.BEGIN_STRING: "FIX.4.2",
        FixTag.MSG_TYPE: FixMsgType.EXECUTION_REPORT,
        FixTag.SENDER_COMP_ID: "EXCHANGE",
        FixTag.TARGET_COMP_ID: "APEX_OMEGA",
        FixTag.MSG_SEQ_NUM: "2",
        FixTag.SENDING_TIME: "20240115-10:30:01.000",
        FixTag.EXEC_ID: exec_id,
        FixTag.CL_ORD_ID: cl_ord_id,
        FixTag.SYMBOL: symbol,
        FixTag.SIDE: side,
        FixTag.ORD_STATUS: ord_status,
        FixTag.EXEC_TYPE: exec_type,
        FixTag.CUM_QTY: str(cum_qty),
        FixTag.LEAVES_QTY: str(leaves_qty),
        FixTag.AVG_PX: f"{avg_px:.2f}",
    }
    if last_qty is not None:
        fields[31] = str(last_qty)  # LastQty
    if last_px is not None:
        fields[32] = f"{last_px:.2f}"  # LastPx

    return build_fix_message(fields)


def build_market_data_snapshot(
    md_req_id: str,
    symbol: str,
    entries: list[dict],
) -> str:
    """Build a FIX MarketDataSnapshot (MsgType=W) message."""
    fields = {
        FixTag.BEGIN_STRING: "FIX.4.2",
        FixTag.MSG_TYPE: FixMsgType.MARKET_DATA_SNAPSHOT,
        FixTag.SENDER_COMP_ID: "EXCHANGE",
        FixTag.TARGET_COMP_ID: "APEX_OMEGA",
        FixTag.MSG_SEQ_NUM: "3",
        FixTag.SENDING_TIME: "20240115-10:30:02.000",
        FixTag.MD_REQ_ID: md_req_id,
        FixTag.SYMBOL: symbol,
        268: str(len(entries)),  # NoMDEntries
    }

    for i, entry in enumerate(entries):
        base = 1000 + i * 10  # Use high tags for repeating group entries
        fields[base + 1] = entry.get("update_action", "0")  # MDUpdateAction
        fields[base + 2] = entry.get("entry_type", "0")  # MDEntryType
        fields[base + 3] = f"{entry.get('price', 0):.2f}"  # MDEntryPx
        fields[base + 4] = str(entry.get("size", 0))  # MDEntrySize

    return build_fix_message(fields)


def run_demo() -> None:
    """Run the FIX protocol demonstration."""
    print("=" * 80)
    print("  Apex_Omega — FIX Protocol Demo")
    print("=" * 80)

    # 1. New Order Single
    print("\n" + "=" * 80)
    print("  1. New Order Single (MsgType=D)")
    print("=" * 80)

    order_msg = build_new_order_single(
        cl_ord_id="ORD-2024-001",
        symbol="AAPL",
        side=Side.BUY,
        quantity=100,
        ord_type=OrdType.LIMIT,
        price=150.50,
        time_in_force=TimeInForce.DAY,
    )
    display_fix_message(order_msg, "New Order Single")

    # 2. Execution Report - New
    print("\n" + "=" * 80)
    print("  2. Execution Report — New (MsgType=8)")
    print("=" * 80)

    exec_new = build_execution_report(
        exec_id="EXEC-001",
        cl_ord_id="ORD-2024-001",
        symbol="AAPL",
        side=Side.BUY,
        ord_status=OrdStatus.NEW,
        exec_type=ExecType.NEW,
        cum_qty=0,
        leaves_qty=100,
        avg_px=0.0,
    )
    display_fix_message(exec_new, "Execution Report (New)")

    # 3. Execution Report - Partial Fill
    print("\n" + "=" * 80)
    print("  3. Execution Report — Partial Fill (MsgType=8)")
    print("=" * 80)

    exec_partial = build_execution_report(
        exec_id="EXEC-002",
        cl_ord_id="ORD-2024-001",
        symbol="AAPL",
        side=Side.BUY,
        ord_status=OrdStatus.PARTIALLY_FILLED,
        exec_type=ExecType.PARTIAL_FILL,
        cum_qty=40,
        leaves_qty=60,
        avg_px=150.50,
        last_qty=40,
        last_px=150.50,
    )
    display_fix_message(exec_partial, "Execution Report (Partial Fill)")

    # 4. Execution Report - Filled
    print("\n" + "=" * 80)
    print("  4. Execution Report — Filled (MsgType=8)")
    print("=" * 80)

    exec_filled = build_execution_report(
        exec_id="EXEC-003",
        cl_ord_id="ORD-2024-001",
        symbol="AAPL",
        side=Side.BUY,
        ord_status=OrdStatus.FILLED,
        exec_type=ExecType.FILL,
        cum_qty=100,
        leaves_qty=0,
        avg_px=150.50,
        last_qty=60,
        last_px=150.50,
    )
    display_fix_message(exec_filled, "Execution Report (Filled)")

    # 5. Market Data Snapshot
    print("\n" + "=" * 80)
    print("  5. Market Data Snapshot (MsgType=W)")
    print("=" * 80)

    md_entries = [
        {"update_action": "0", "entry_type": "0", "price": 150.25, "size": 500},   # Bid
        {"update_action": "0", "entry_type": "1", "price": 150.50, "size": 300},   # Ask
        {"update_action": "1", "entry_type": "0", "price": 150.00, "size": 1000},  # Bid update
    ]
    md_msg = build_market_data_snapshot(
        md_req_id="MD-001",
        symbol="AAPL",
        entries=md_entries,
    )
    display_fix_message(md_msg, "Market Data Snapshot")

    # 6. Message Parsing Demo
    print("\n" + "=" * 80)
    print("  6. Message Parsing Demo")
    print("=" * 80)

    # Parse the order message back
    parsed = parse_fix_message(order_msg)
    print(f"\n  Parsed New Order Single:")
    print(f"  {'Field':<25} {'Value':<20}")
    print(f"  {'-'*25} {'-'*20}")
    for tag in sorted(parsed.keys()):
        name = get_field_name(tag)
        print(f"  {name:<25} {parsed[tag]:<20}")

    # Verify checksum
    print(f"\n  Checksum Verification:")
    # Extract checksum from message
    checksum_tag_pos = order_msg.rfind(f"{SOH}{FixTag.CHECKSUM}=")
    if checksum_tag_pos >= 0:
        checksum_start = checksum_tag_pos + 1 + len(f"{FixTag.CHECKSUM}=")
        checksum_end = order_msg.find(SOH, checksum_start)
        msg_checksum = order_msg[checksum_start:checksum_end]

        # Recalculate — include the SOH separator before the checksum field
        msg_for_calc = order_msg[:checksum_tag_pos + 1]
        calc_checksum = format_checksum(calculate_checksum(msg_for_calc))

        print(f"  Message checksum:  {msg_checksum}")
        print(f"  Calculated checksum: {calc_checksum}")
        print(f"  Match: {'✅ YES' if msg_checksum == calc_checksum else '❌ NO'}")

    # Summary
    print(f"\n{'='*80}")
    print("  FIX Protocol Summary")
    print(f"{'='*80}")
    print(f"  Messages demonstrated:")
    print(f"    - New Order Single (D)")
    print(f"    - Execution Report (8) — New, Partial Fill, Filled")
    print(f"    - Market Data Snapshot (W)")
    print(f"  Features:")
    print(f"    - FIX 4.2 message format")
    print(f"    - Proper field ordering (sorted by tag)")
    print(f"    - Checksum calculation and verification")
    print(f"    - Message parsing and field extraction")


if __name__ == "__main__":
    run_demo()
