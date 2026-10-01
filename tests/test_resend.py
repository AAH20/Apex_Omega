"""Unit tests for FIX Resend Request Handler — Gap Fill, Resend Request, sequence range management."""

import pytest

from src.fix.resend import (
    GapFillResult,
    ResendRequestHandler,
    SequenceGap,
)


# ── Initialization ──────────────────────────────────────────────────


def test_handler_initializes_with_default_values():
    handler = ResendRequestHandler()
    assert handler.next_seq_num == 1
    assert handler.expected_seq_num == 1
    assert handler.max_resend_request_size == 2500


def test_handler_initializes_with_custom_values():
    handler = ResendRequestHandler(initial_seq_num=100, max_resend_request_size=500)
    assert handler.next_seq_num == 100
    assert handler.expected_seq_num == 100
    assert handler.max_resend_request_size == 500


# ── Sequence Number Generation ──────────────────────────────────────


def test_get_next_seq_num_increments():
    handler = ResendRequestHandler()
    assert handler.get_next_seq_num() == 1
    assert handler.get_next_seq_num() == 2
    assert handler.get_next_seq_num() == 3


def test_reset_clears_state():
    handler = ResendRequestHandler()
    handler.get_next_seq_num()
    handler.get_next_seq_num()
    handler.process_incoming(1)
    handler.reset(50)
    assert handler.next_seq_num == 50
    assert handler.expected_seq_num == 50


# ── Incoming Message Processing ─────────────────────────────────────


def test_process_incoming_in_order():
    handler = ResendRequestHandler()
    valid, gap = handler.process_incoming(1)
    assert valid is True
    assert gap is None
    valid, gap = handler.process_incoming(2)
    assert valid is True
    assert gap is None


def test_process_incoming_duplicate_rejected():
    handler = ResendRequestHandler()
    handler.process_incoming(1)
    valid, gap = handler.process_incoming(1)
    assert valid is False
    assert gap is None


def test_process_incoming_invalid_seq_num_rejected():
    handler = ResendRequestHandler()
    valid, gap = handler.process_incoming(0)
    assert valid is False
    assert gap is None
    valid, gap = handler.process_incoming(-5)
    assert valid is False
    assert gap is None


def test_process_incoming_gap_detected():
    handler = ResendRequestHandler()
    handler.process_incoming(1)
    valid, gap = handler.process_incoming(5)
    assert valid is True
    assert gap is not None
    assert gap.start == 2
    assert gap.end == 4
    assert gap.count == 3


def test_process_incoming_gap_filled_later():
    handler = ResendRequestHandler()
    handler.process_incoming(1)
    handler.process_incoming(5)  # gap 2-4
    valid, gap = handler.process_incoming(2)
    assert valid is True
    assert gap is None


# ── Message Creation ────────────────────────────────────────────────


def test_create_resend_request_format():
    handler = ResendRequestHandler()
    msg = handler.create_resend_request(10, 20)
    assert msg["7"] == "10"
    assert msg["16"] == "20"


def test_create_resend_request_default_end():
    handler = ResendRequestHandler()
    msg = handler.create_resend_request(10)
    assert msg["7"] == "10"
    assert msg["16"] == "0"


def test_create_gap_fill_format():
    handler = ResendRequestHandler()
    msg = handler.create_gap_fill(5, gap_fill_flag=True)
    assert msg["36"] == "5"
    assert msg["123"] == "Y"


def test_create_gap_fill_reset_mode():
    handler = ResendRequestHandler()
    msg = handler.create_gap_fill(5, gap_fill_flag=False)
    assert msg["36"] == "5"
    assert msg["123"] == "N"


# ── Gap Fill Handling ───────────────────────────────────────────────


def test_handle_gap_fill_fills_missing():
    handler = ResendRequestHandler()
    handler.process_incoming(1)
    handler.process_incoming(5)  # gap 2-4
    result = handler.handle_gap_fill(msg_seq_num=2, new_seq_no=5, gap_fill_flag=True)
    assert result.is_complete is True
    assert result.filled == [2, 3, 4]
    assert result.missing == []


def test_handle_gap_fill_reset_mode():
    handler = ResendRequestHandler()
    handler.process_incoming(1)
    handler.process_incoming(2)
    result = handler.handle_gap_fill(msg_seq_num=3, new_seq_no=10, gap_fill_flag=False)
    assert result.is_complete is True
    assert handler.expected_seq_num == 10
    assert handler.next_seq_num == 10


def test_handle_gap_fill_partial_already_received():
    handler = ResendRequestHandler()
    handler.process_incoming(1)
    handler.process_incoming(3)  # gap 2
    handler.process_incoming(2)  # fill gap
    result = handler.handle_gap_fill(msg_seq_num=2, new_seq_no=3, gap_fill_flag=True)
    assert result.is_complete is False
    assert result.filled == []
    assert result.missing == [2]


# ── Sequence Range Validation ───────────────────────────────────────


def test_validate_sequence_range_valid():
    handler = ResendRequestHandler()
    errors = handler.validate_sequence_range(1, 100)
    assert errors == []


def test_validate_sequence_range_valid_with_zero_end():
    handler = ResendRequestHandler()
    errors = handler.validate_sequence_range(1, 0)
    assert errors == []


def test_validate_sequence_range_invalid_begin():
    handler = ResendRequestHandler()
    errors = handler.validate_sequence_range(0, 100)
    assert len(errors) == 1
    assert "BeginSeqNo" in errors[0]


def test_validate_sequence_range_invalid_end():
    handler = ResendRequestHandler()
    errors = handler.validate_sequence_range(1, -1)
    assert len(errors) == 1
    assert "EndSeqNo" in errors[0]


def test_validate_sequence_range_end_before_begin():
    handler = ResendRequestHandler()
    errors = handler.validate_sequence_range(100, 50)
    assert len(errors) == 1
    assert "EndSeqNo" in errors[0]


def test_validate_sequence_range_too_large():
    handler = ResendRequestHandler(max_resend_request_size=100)
    errors = handler.validate_sequence_range(1, 200)
    assert len(errors) == 1
    assert "too large" in errors[0]


# ── Gap History ─────────────────────────────────────────────────────


def test_gap_history_tracked():
    handler = ResendRequestHandler()
    handler.process_incoming(1)
    handler.process_incoming(5)  # gap 2-4
    handler.process_incoming(10)  # gap 6-9
    history = handler.get_gap_history()
    assert len(history) == 2
    assert history[0].start == 2
    assert history[0].end == 4
    assert history[1].start == 6
    assert history[1].end == 9


def test_gap_history_empty_initially():
    handler = ResendRequestHandler()
    assert handler.get_gap_history() == []


# ── Data Classes ────────────────────────────────────────────────────


def test_sequence_gap_count_single():
    gap = SequenceGap(5, 5)
    assert gap.count == 1


def test_sequence_gap_count_range():
    gap = SequenceGap(2, 10)
    assert gap.count == 9


def test_sequence_gap_str_single():
    gap = SequenceGap(5, 5)
    assert "5" in str(gap)


def test_sequence_gap_str_range():
    gap = SequenceGap(2, 10)
    assert "2" in str(gap)
    assert "10" in str(gap)


def test_gap_fill_result_complete():
    result = GapFillResult(filled=[1, 2, 3])
    assert result.is_complete is True


def test_gap_fill_result_incomplete_missing():
    result = GapFillResult(filled=[1], missing=[2, 3])
    assert result.is_complete is False


def test_gap_fill_result_incomplete_errors():
    result = GapFillResult(filled=[1], errors=["some error"])
    assert result.is_complete is False


def test_gap_fill_result_str_complete():
    result = GapFillResult(filled=[1, 2, 3])
    assert "complete" in str(result)


def test_gap_fill_result_str_incomplete():
    result = GapFillResult(filled=[1], missing=[2])
    assert "incomplete" in str(result)
