"""Tests for FIX Reject Handler — TDD: written before implementation."""
import pytest
from src.fix.reject import (
    RejectReason,
    RejectAction,
    RejectHandler,
    RejectEvent,
    SessionRejectError,
)


# ---------------------------------------------------------------------------
# RejectReason classification tests
# ---------------------------------------------------------------------------

class TestRejectReasonClassification:
    """Test classification of FIX session reject reasons."""

    def test_invalid_tag_number(self):
        assert RejectReason.from_code(0) == RejectReason.INVALID_TAG_NUMBER

    def test_required_tag_missing(self):
        assert RejectReason.from_code(1) == RejectReason.REQUIRED_TAG_MISSING

    def test_tag_not_defined_for_message_type(self):
        assert RejectReason.from_code(2) == RejectReason.TAG_NOT_DEFINED_FOR_MESSAGE_TYPE

    def test_undefined_tag(self):
        assert RejectReason.from_code(3) == RejectReason.UNDEFINED_TAG

    def test_tag_specified_without_value(self):
        assert RejectReason.from_code(4) == RejectReason.TAG_SPECIFIED_WITHOUT_VALUE

    def test_value_out_of_range(self):
        assert RejectReason.from_code(5) == RejectReason.VALUE_OUT_OF_RANGE

    def test_incorrect_data_format(self):
        assert RejectReason.from_code(6) == RejectReason.INCORRECT_DATA_FORMAT

    def test_decryption_problem(self):
        assert RejectReason.from_code(7) == RejectReason.DECRYPTION_PROBLEM

    def test_signature_problem(self):
        assert RejectReason.from_code(8) == RejectReason.SIGNATURE_PROBLEM

    def test_comp_id_problem(self):
        assert RejectReason.from_code(9) == RejectReason.COMP_ID_PROBLEM

    def test_sending_time_accuracy_problem(self):
        assert RejectReason.from_code(10) == RejectReason.SENDING_TIME_ACCURACY_PROBLEM

    def test_invalid_msg_type(self):
        assert RejectReason.from_code(11) == RejectReason.INVALID_MSG_TYPE

    def test_xml_validation_error(self):
        assert RejectReason.from_code(12) == RejectReason.XML_VALIDATION_ERROR

    def test_tag_appears_more_than_once(self):
        assert RejectReason.from_code(13) == RejectReason.TAG_APPEARS_MORE_THAN_ONCE

    def test_tag_out_of_required_order(self):
        assert RejectReason.from_code(14) == RejectReason.TAG_OUT_OF_REQUIRED_ORDER

    def test_repeating_group_out_of_order(self):
        assert RejectReason.from_code(15) == RejectReason.REPEATING_GROUP_OUT_OF_ORDER

    def test_incorrect_num_in_group_count(self):
        assert RejectReason.from_code(16) == RejectReason.INCORRECT_NUM_IN_GROUP_COUNT

    def test_non_data_value_includes_delimiter(self):
        assert RejectReason.from_code(17) == RejectReason.NON_DATA_VALUE_INCLUDES_DELIMITER

    def test_other_reason(self):
        assert RejectReason.from_code(99) == RejectReason.OTHER

    def test_unknown_reason_maps_to_other(self):
        assert RejectReason.from_code(999) == RejectReason.OTHER

    def test_negative_reason_maps_to_other(self):
        assert RejectReason.from_code(-1) == RejectReason.OTHER


# ---------------------------------------------------------------------------
# RejectAction determination tests
# ---------------------------------------------------------------------------

class TestRejectActionDetermination:
    """Test recovery action determination based on reject reason."""

    def test_invalid_tag_number_requires_disconnect(self):
        action = RejectHandler.determine_action(RejectReason.INVALID_TAG_NUMBER)
        assert action == RejectAction.DISCONNECT

    def test_required_tag_missing_requires_disconnect(self):
        action = RejectHandler.determine_action(RejectReason.REQUIRED_TAG_MISSING)
        assert action == RejectAction.DISCONNECT

    def test_tag_not_defined_requires_disconnect(self):
        action = RejectHandler.determine_action(RejectReason.TAG_NOT_DEFINED_FOR_MESSAGE_TYPE)
        assert action == RejectAction.DISCONNECT

    def test_undefined_tag_requires_disconnect(self):
        action = RejectHandler.determine_action(RejectReason.UNDEFINED_TAG)
        assert action == RejectAction.DISCONNECT

    def test_tag_without_value_requires_disconnect(self):
        action = RejectHandler.determine_action(RejectReason.TAG_SPECIFIED_WITHOUT_VALUE)
        assert action == RejectAction.DISCONNECT

    def test_value_out_of_range_requires_retry(self):
        action = RejectHandler.determine_action(RejectReason.VALUE_OUT_OF_RANGE)
        assert action == RejectAction.RETRY

    def test_incorrect_data_format_requires_retry(self):
        action = RejectHandler.determine_action(RejectReason.INCORRECT_DATA_FORMAT)
        assert action == RejectAction.RETRY

    def test_decryption_problem_requires_disconnect(self):
        action = RejectHandler.determine_action(RejectReason.DECRYPTION_PROBLEM)
        assert action == RejectAction.DISCONNECT

    def test_signature_problem_requires_disconnect(self):
        action = RejectHandler.determine_action(RejectReason.SIGNATURE_PROBLEM)
        assert action == RejectAction.DISCONNECT

    def test_comp_id_problem_requires_disconnect(self):
        action = RejectHandler.determine_action(RejectReason.COMP_ID_PROBLEM)
        assert action == RejectAction.DISCONNECT

    def test_sending_time_accuracy_requires_retry(self):
        action = RejectHandler.determine_action(RejectReason.SENDING_TIME_ACCURACY_PROBLEM)
        assert action == RejectAction.RETRY

    def test_invalid_msg_type_requires_disconnect(self):
        action = RejectHandler.determine_action(RejectReason.INVALID_MSG_TYPE)
        assert action == RejectAction.DISCONNECT

    def test_xml_validation_error_requires_retry(self):
        action = RejectHandler.determine_action(RejectReason.XML_VALIDATION_ERROR)
        assert action == RejectAction.RETRY

    def test_tag_more_than_once_requires_retry(self):
        action = RejectHandler.determine_action(RejectReason.TAG_APPEARS_MORE_THAN_ONCE)
        assert action == RejectAction.RETRY

    def test_tag_out_of_order_requires_retry(self):
        action = RejectHandler.determine_action(RejectReason.TAG_OUT_OF_REQUIRED_ORDER)
        assert action == RejectAction.RETRY

    def test_repeating_group_out_of_order_requires_retry(self):
        action = RejectHandler.determine_action(RejectReason.REPEATING_GROUP_OUT_OF_ORDER)
        assert action == RejectAction.RETRY

    def test_incorrect_num_in_group_requires_retry(self):
        action = RejectHandler.determine_action(RejectReason.INCORRECT_NUM_IN_GROUP_COUNT)
        assert action == RejectAction.RETRY

    def test_non_data_value_delimiter_requires_disconnect(self):
        action = RejectHandler.determine_action(RejectReason.NON_DATA_VALUE_INCLUDES_DELIMITER)
        assert action == RejectAction.DISCONNECT

    def test_other_requires_logout(self):
        action = RejectHandler.determine_action(RejectReason.OTHER)
        assert action == RejectAction.LOGOUT


# ---------------------------------------------------------------------------
# RejectHandler processing tests
# ---------------------------------------------------------------------------

class TestRejectHandlerProcessing:
    """Test processing of reject messages through the handler."""

    def _make_reject_msg(self, ref_seq_num=5, ref_tag=None, ref_msg_type=None,
                         reason_code=0, text="Invalid tag"):
        """Helper to build a reject message dict."""
        fields = {
            "45": str(ref_seq_num),
            "373": str(reason_code),
            "58": text,
        }
        if ref_tag is not None:
            fields["371"] = str(ref_tag)
        if ref_msg_type is not None:
            fields["372"] = str(ref_msg_type)
        return fields

    def test_process_reject_returns_event(self):
        handler = RejectHandler()
        fields = self._make_reject_msg(ref_seq_num=5, reason_code=0)
        event = handler.process_reject(fields)
        assert isinstance(event, RejectEvent)
        assert event.ref_seq_num == 5
        assert event.reason == RejectReason.INVALID_TAG_NUMBER
        assert event.action == RejectAction.DISCONNECT

    def test_process_reject_with_ref_tag(self):
        handler = RejectHandler()
        fields = self._make_reject_msg(ref_seq_num=10, ref_tag=55, reason_code=0)
        event = handler.process_reject(fields)
        assert event.ref_tag == 55

    def test_process_reject_with_ref_msg_type(self):
        handler = RejectHandler()
        fields = self._make_reject_msg(ref_seq_num=10, ref_msg_type="D", reason_code=11)
        event = handler.process_reject(fields)
        assert event.ref_msg_type == "D"
        assert event.reason == RejectReason.INVALID_MSG_TYPE

    def test_process_reject_with_text(self):
        handler = RejectHandler()
        fields = self._make_reject_msg(ref_seq_num=3, reason_code=5, text="Price out of range")
        event = handler.process_reject(fields)
        assert event.text == "Price out of range"

    def test_process_reject_missing_ref_seq_num_raises(self):
        handler = RejectHandler()
        fields = {"373": "0", "58": "test"}
        with pytest.raises(SessionRejectError):
            handler.process_reject(fields)

    def test_process_reject_missing_reason_code_raises(self):
        handler = RejectHandler()
        fields = {"45": "5", "58": "test"}
        with pytest.raises(SessionRejectError):
            handler.process_reject(fields)

    def test_process_reject_invalid_reason_code_raises(self):
        handler = RejectHandler()
        fields = {"45": "5", "373": "not_a_number", "58": "test"}
        with pytest.raises(SessionRejectError):
            handler.process_reject(fields)

    def test_handler_tracks_reject_history(self):
        handler = RejectHandler()
        fields1 = self._make_reject_msg(ref_seq_num=5, reason_code=0)
        fields2 = self._make_reject_msg(ref_seq_num=10, reason_code=5)
        handler.process_reject(fields1)
        handler.process_reject(fields2)
        assert len(handler.reject_history) == 2

    def test_handler_clears_history(self):
        handler = RejectHandler()
        fields = self._make_reject_msg(ref_seq_num=5, reason_code=0)
        handler.process_reject(fields)
        assert len(handler.reject_history) == 1
        handler.clear_history()
        assert len(handler.reject_history) == 0

    def test_handler_detects_reject_on_reject_loop(self):
        """A reject with RefSeqNum equal to its own seq num indicates a loop."""
        handler = RejectHandler()
        # Simulate: reject message with seq_num=7, ref_seq_num=7
        fields = self._make_reject_msg(ref_seq_num=7, reason_code=0)
        event = handler.process_reject(fields, msg_seq_num=7)
        assert event.is_reject_on_reject is True

    def test_handler_no_loop_when_ref_differs(self):
        handler = RejectHandler()
        fields = self._make_reject_msg(ref_seq_num=5, reason_code=0)
        event = handler.process_reject(fields, msg_seq_num=7)
        assert event.is_reject_on_reject is False

    def test_handler_counts_rejects_by_reason(self):
        handler = RejectHandler()
        handler.process_reject(self._make_reject_msg(ref_seq_num=1, reason_code=0))
        handler.process_reject(self._make_reject_msg(ref_seq_num=2, reason_code=0))
        handler.process_reject(self._make_reject_msg(ref_seq_num=3, reason_code=5))
        counts = handler.get_reject_counts_by_reason()
        assert counts[RejectReason.INVALID_TAG_NUMBER] == 2
        assert counts[RejectReason.VALUE_OUT_OF_RANGE] == 1

    def test_handler_max_rejects_threshold(self):
        handler = RejectHandler(max_rejects_before_disconnect=3)
        handler.process_reject(self._make_reject_msg(ref_seq_num=1, reason_code=5))
        handler.process_reject(self._make_reject_msg(ref_seq_num=2, reason_code=5))
        assert handler.should_disconnect() is False
        handler.process_reject(self._make_reject_msg(ref_seq_num=3, reason_code=5))
        assert handler.should_disconnect() is True

    def test_handler_generates_reject_message(self):
        handler = RejectHandler(sender_comp_id="SENDER", target_comp_id="TARGET")
        msg = handler.build_reject_response(
            ref_seq_num=5,
            reason=RejectReason.INVALID_TAG_NUMBER,
            ref_tag=55,
        )
        assert msg.msg_type == "3"
        assert msg.get_field("45") == "5"
        assert msg.get_field("371") == "55"
        assert msg.get_field("373") == "0"

    def test_handler_generates_reject_with_text(self):
        handler = RejectHandler(sender_comp_id="SENDER", target_comp_id="TARGET")
        msg = handler.build_reject_response(
            ref_seq_num=10,
            reason=RejectReason.VALUE_OUT_OF_RANGE,
            text="Price must be positive",
        )
        assert msg.get_field("58") == "Price must be positive"
        assert msg.get_field("373") == "5"


# ---------------------------------------------------------------------------
# RejectEvent tests
# ---------------------------------------------------------------------------

class TestRejectEvent:
    """Test RejectEvent dataclass behavior."""

    def test_event_str_representation(self):
        event = RejectEvent(
            ref_seq_num=5,
            reason=RejectReason.INVALID_TAG_NUMBER,
            action=RejectAction.DISCONNECT,
            ref_tag=55,
            ref_msg_type="D",
            text="Invalid tag",
            is_reject_on_reject=False,
        )
        s = str(event)
        assert "seq=5" in s
        assert "INVALID_TAG_NUMBER" in s
        assert "DISCONNECT" in s

    def test_event_is_critical_for_disconnect_actions(self):
        event = RejectEvent(
            ref_seq_num=1,
            reason=RejectReason.INVALID_TAG_NUMBER,
            action=RejectAction.DISCONNECT,
        )
        assert event.is_critical() is True

    def test_event_is_not_critical_for_retry(self):
        event = RejectEvent(
            ref_seq_num=1,
            reason=RejectReason.VALUE_OUT_OF_RANGE,
            action=RejectAction.RETRY,
        )
        assert event.is_critical() is False

    def test_event_is_not_critical_for_logout(self):
        event = RejectEvent(
            ref_seq_num=1,
            reason=RejectReason.OTHER,
            action=RejectAction.LOGOUT,
        )
        assert event.is_critical() is False


# ---------------------------------------------------------------------------
# Integration-style tests
# ---------------------------------------------------------------------------

class TestRejectHandlerIntegration:
    """Integration tests combining multiple features."""

    def test_full_reject_flow_with_recovery(self):
        handler = RejectHandler(max_rejects_before_disconnect=5)
        # Process a retryable reject
        fields = {"45": "10", "373": "5", "58": "Price out of range"}
        event = handler.process_reject(fields, msg_seq_num=15)
        assert event.action == RejectAction.RETRY
        assert handler.should_disconnect() is False

    def test_multiple_critical_rejects_trigger_disconnect(self):
        handler = RejectHandler(max_rejects_before_disconnect=2)
        handler.process_reject({"45": "1", "373": "0", "58": "Invalid tag"})
        handler.process_reject({"45": "2", "373": "1", "58": "Missing tag"})
        assert handler.should_disconnect() is True

    def test_reject_on_reject_loop_triggers_disconnect(self):
        handler = RejectHandler()
        fields = {"45": "7", "373": "0", "58": "Invalid tag"}
        event = handler.process_reject(fields, msg_seq_num=7)
        assert event.is_reject_on_reject is True
        assert event.action == RejectAction.DISCONNECT

    def test_handler_with_custom_comp_ids(self):
        handler = RejectHandler(
            sender_comp_id="BANK",
            target_comp_id="EXCHANGE",
        )
        msg = handler.build_reject_response(
            ref_seq_num=1,
            reason=RejectReason.OTHER,
        )
        assert msg.sender_comp_id == "BANK"
        assert msg.target_comp_id == "EXCHANGE"
