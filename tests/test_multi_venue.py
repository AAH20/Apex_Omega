"""TDD tests for Multi-Venue Feed Handler — written before implementation."""
import threading
import time
import pytest

from src.feed.multi_venue import (
    MarketDataEvent,
    RingBuffer,
    MultiVenueFeedHandler,
    VenueStats,
    FeedError,
    EventValidationError,
)


def make_event(symbol="BTCUSDT", ts=1, bid=1.0, ask=2.0, bsize=1, asize=1,
               venue="BINANCE", etype="QUOTE", seq=1):
    return MarketDataEvent(
        symbol=symbol, timestamp_ns=ts, bid_price=bid, ask_price=ask,
        bid_size=bsize, ask_size=asize, venue=venue, event_type=etype, sequence=seq,
    )


class TestMarketDataEvent:
    def test_creation(self):
        e = make_event()
        assert e.symbol == "BTCUSDT"
        assert e.venue == "BINANCE"

    def test_serialization_roundtrip(self):
        e = make_event(symbol="ETHUSDT", ts=99, bid=100.0, ask=101.0, bsize=5, asize=6,
                        venue="COINBASE", etype="TRADE", seq=42)
        data = e.to_bytes()
        r = MarketDataEvent.from_bytes(data)
        assert r == e

    def test_spread(self):
        assert make_event(bid=100.0, ask=110.0).spread == pytest.approx(10.0)

    def test_mid_price(self):
        assert make_event(bid=100.0, ask=110.0).mid_price == pytest.approx(105.0)

    def test_invalid_symbol(self):
        with pytest.raises(EventValidationError):
            make_event(symbol="")

    def test_invalid_timestamp(self):
        with pytest.raises(EventValidationError):
            make_event(ts=-1)

    def test_invalid_price(self):
        with pytest.raises(EventValidationError):
            make_event(bid=-1.0)

    def test_invalid_sequence(self):
        with pytest.raises(EventValidationError):
            make_event(seq=0)

    def test_invalid_event_type(self):
        with pytest.raises(EventValidationError):
            make_event(etype="INVALID")

    def test_equality(self):
        assert make_event() == make_event()
        assert make_event() != make_event(symbol="ETHUSDT")

    def test_hash(self):
        assert hash(make_event()) == hash(make_event())


class TestRingBuffer:
    def test_creation(self):
        rb = RingBuffer(capacity=1024)
        assert rb.capacity == 1024
        assert rb.size == 0
        assert rb.is_empty()

    def test_push_pop(self):
        rb = RingBuffer(capacity=10)
        e = make_event()
        rb.push(e)
        assert rb.size == 1
        assert rb.pop() == e
        assert rb.size == 0

    def test_fifo_order(self):
        rb = RingBuffer(capacity=10)
        for i in range(5):
            rb.push(make_event(symbol=f"SYM{i}", seq=i + 1))
        for i in range(5):
            assert rb.pop().symbol == f"SYM{i}"

    def test_wrap_around(self):
        rb = RingBuffer(capacity=4)
        for i in range(6):
            rb.push(make_event(symbol=f"SYM{i}", seq=i + 1))
        assert rb.size == 4
        assert rb.pop().symbol == "SYM2"

    def test_overflow_overwrites_oldest(self):
        rb = RingBuffer(capacity=3)
        for i in range(5):
            rb.push(make_event(symbol=f"SYM{i}", seq=i + 1))
        assert rb.size == 3
        assert rb.pop().symbol == "SYM2"

    def test_pop_empty(self):
        assert RingBuffer(capacity=10).pop() is None

    def test_peek(self):
        rb = RingBuffer(capacity=10)
        e = make_event()
        rb.push(e)
        assert rb.peek() == e
        assert rb.size == 1

    def test_clear(self):
        rb = RingBuffer(capacity=10)
        for i in range(5):
            rb.push(make_event())
        rb.clear()
        assert rb.size == 0

    def test_is_full(self):
        rb = RingBuffer(capacity=3)
        for i in range(3):
            rb.push(make_event())
        assert rb.is_full()

    def test_power_of_two(self):
        assert RingBuffer(capacity=1000).capacity == 1024

    def test_zero_capacity_raises(self):
        with pytest.raises(ValueError):
            RingBuffer(capacity=0)

    def test_thread_safety(self):
        rb = RingBuffer(capacity=10000)
        errors = []

        def producer():
            try:
                for i in range(1000):
                    rb.push(make_event(symbol=f"S{i % 10}", seq=i + 1))
            except Exception as e:
                errors.append(e)

        def consumer():
            try:
                count = 0
                while count < 1000:
                    if rb.pop() is not None:
                        count += 1
                    else:
                        time.sleep(0.001)
            except Exception as e:
                errors.append(e)

        t1 = threading.Thread(target=producer)
        t2 = threading.Thread(target=consumer)
        t1.start()
        t2.start()
        t1.join(timeout=10)
        t2.join(timeout=10)
        assert not errors

    def test_zero_copy_peek(self):
        rb = RingBuffer(capacity=10)
        e = make_event()
        rb.push(e)
        assert rb.peek() is e

    def test_len(self):
        rb = RingBuffer(capacity=10)
        assert len(rb) == 0
        rb.push(make_event())
        assert len(rb) == 1

    def test_bool(self):
        rb = RingBuffer(capacity=10)
        assert not rb
        rb.push(make_event())
        assert rb

    def test_iter(self):
        rb = RingBuffer(capacity=10)
        for i in range(3):
            rb.push(make_event(symbol=f"SYM{i}", seq=i + 1))
        assert [e.symbol for e in rb] == ["SYM0", "SYM1", "SYM2"]

    def test_getitem(self):
        rb = RingBuffer(capacity=10)
        for i in range(3):
            rb.push(make_event(symbol=f"SYM{i}", seq=i + 1))
        assert rb[0].symbol == "SYM0"
        assert rb[2].symbol == "SYM2"

    def test_getitem_out_of_range(self):
        rb = RingBuffer(capacity=10)
        rb.push(make_event())
        with pytest.raises(IndexError):
            _ = rb[5]

    def test_contains(self):
        rb = RingBuffer(capacity=10)
        e = make_event()
        rb.push(e)
        assert e in rb
        assert make_event(symbol="ETHUSDT") not in rb

    def test_reversed(self):
        rb = RingBuffer(capacity=10)
        for i in range(3):
            rb.push(make_event(symbol=f"SYM{i}", seq=i + 1))
        assert [e.symbol for e in reversed(rb)] == ["SYM2", "SYM1", "SYM0"]

    def test_copy(self):
        rb = RingBuffer(capacity=10)
        for i in range(3):
            rb.push(make_event(symbol=f"SYM{i}", seq=i + 1))
        c = rb.copy()
        assert len(c) == 3
        rb.clear()
        assert len(c) == 3

    def test_maxlen(self):
        assert RingBuffer(capacity=100).maxlen == 100

    def test_maxlen_readonly(self):
        rb = RingBuffer(capacity=100)
        with pytest.raises(AttributeError):
            rb.maxlen = 200

    def test_throughput(self):
        rb = RingBuffer(capacity=100000)
        start = time.monotonic()
        for i in range(50000):
            rb.push(make_event(symbol=f"S{i % 100}", seq=i + 1))
        elapsed = time.monotonic() - start
        assert 50000 / elapsed > 100000

    def test_memory_efficiency(self):
        import sys
        rb = RingBuffer(capacity=1000)
        rb.push(make_event())
        assert sys.getsizeof(rb._buffer) < 10_000_000

    def test_extend(self):
        rb = RingBuffer(capacity=10)
        events = [make_event(symbol=f"SYM{i}", seq=i + 1) for i in range(5)]
        rb.extend(events)
        assert len(rb) == 5

    def test_extend_overflow(self):
        rb = RingBuffer(capacity=3)
        events = [make_event(symbol=f"SYM{i}", seq=i + 1) for i in range(5)]
        rb.extend(events)
        assert len(rb) == 3
        assert rb[0].symbol == "SYM2"

    def test_popleft(self):
        rb = RingBuffer(capacity=10)
        for i in range(3):
            rb.push(make_event(symbol=f"SYM{i}", seq=i + 1))
        assert rb.popleft().symbol == "SYM0"
        assert len(rb) == 2

    def test_pop_right(self):
        rb = RingBuffer(capacity=10)
        for i in range(3):
            rb.push(make_event(symbol=f"SYM{i}", seq=i + 1))
        assert rb.pop().symbol == "SYM2"
        assert len(rb) == 2

    def test_remove(self):
        rb = RingBuffer(capacity=10)
        e = make_event()
        rb.push(e)
        rb.remove(e)
        assert len(rb) == 0

    def test_remove_not_found(self):
        rb = RingBuffer(capacity=10)
        rb.push(make_event())
        with pytest.raises(ValueError):
            rb.remove(make_event(symbol="ETHUSDT"))

    def test_rotate(self):
        rb = RingBuffer(capacity=10)
        for i in range(5):
            rb.push(make_event(symbol=f"SYM{i}", seq=i + 1))
        rb.rotate(2)
        assert rb[0].symbol == "SYM3"

    def test_rotate_negative(self):
        rb = RingBuffer(capacity=10)
        for i in range(5):
            rb.push(make_event(symbol=f"SYM{i}", seq=i + 1))
        rb.rotate(-2)
        assert rb[0].symbol == "SYM2"

    def test_reverse(self):
        rb = RingBuffer(capacity=10)
        for i in range(3):
            rb.push(make_event(symbol=f"SYM{i}", seq=i + 1))
        rb.reverse()
        assert rb[0].symbol == "SYM2"

    def test_count(self):
        rb = RingBuffer(capacity=10)
        e = make_event()
        rb.push(e)
        rb.push(e)
        assert rb.count(e) == 2

    def test_index(self):
        rb = RingBuffer(capacity=10)
        e = make_event()
        rb.push(e)
        assert rb.index(e) == 0

    def test_index_not_found(self):
        rb = RingBuffer(capacity=10)
        rb.push(make_event())
        with pytest.raises(ValueError):
            rb.index(make_event(symbol="ETHUSDT"))

    def test_slice(self):
        rb = RingBuffer(capacity=10)
        for i in range(5):
            rb.push(make_event(symbol=f"SYM{i}", seq=i + 1))
        assert [e.symbol for e in rb[1:3]] == ["SYM1", "SYM2"]

    def test_event_validation(self):
        rb = RingBuffer(capacity=10)
        with pytest.raises((TypeError, AttributeError)):
            rb.push("not an event")

    def test_none_event(self):
        rb = RingBuffer(capacity=10)
        with pytest.raises((TypeError, AttributeError)):
            rb.push(None)

    def test_invalid_type(self):
        rb = RingBuffer(capacity=10)
        with pytest.raises((TypeError, AttributeError)):
            rb.push(123)

    def test_int_price_accepted(self):
        rb = RingBuffer(capacity=10)
        e = make_event(bid=1, ask=2)
        rb.push(e)
        assert rb.size == 1

    def test_float_size_rejected(self):
        with pytest.raises((TypeError, AttributeError)):
            make_event(bsize=1.5)

    def test_negative_size_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(bsize=-1)

    def test_negative_ask_size_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(asize=-1)

    def test_zero_size_valid(self):
        e = make_event(bsize=0, asize=0, etype="HEARTBEAT")
        assert e.bid_size == 0

    def test_large_symbol(self):
        rb = RingBuffer(capacity=10)
        e = make_event(symbol="A" * 50)
        rb.push(e)
        assert rb.size == 1

    def test_large_venue(self):
        rb = RingBuffer(capacity=10)
        e = make_event(venue="A" * 50)
        rb.push(e)
        assert rb.size == 1

    def test_special_chars_symbol(self):
        rb = RingBuffer(capacity=10)
        e = make_event(symbol="BTC-USDT")
        rb.push(e)
        assert rb.size == 1

    def test_unicode_symbol(self):
        rb = RingBuffer(capacity=10)
        e = make_event(symbol="BTCUSDT🚀")
        rb.push(e)
        assert rb.size == 1

    def test_unicode_venue(self):
        rb = RingBuffer(capacity=10)
        e = make_event(venue="BİNANCE")
        rb.push(e)
        assert rb.size == 1

    def test_unicode_event_type_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(etype="QUOTE🚀")

    def test_newline_symbol_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(symbol="BTC\nUSDT")

    def test_tab_symbol_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(symbol="BTC\tUSDT")

    def test_null_byte_symbol_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(symbol="BTC\x00USDT")

    def test_control_char_symbol_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(symbol="BTC\x01USDT")

    def test_delete_char_symbol_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(symbol="BTC\x7fUSDT")

    def test_newline_venue_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(venue="BINANCE\n")

    def test_tab_venue_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(venue="BINANCE\t")

    def test_null_byte_venue_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(venue="BINANCE\x00")

    def test_control_char_venue_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(venue="BINANCE\x01")

    def test_delete_char_venue_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(venue="BINANCE\x7f")

    def test_newline_event_type_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(etype="QUOTE\n")

    def test_tab_event_type_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(etype="QUOTE\t")

    def test_null_byte_event_type_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(etype="QUOTE\x00")

    def test_control_char_event_type_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(etype="QUOTE\x01")

    def test_delete_char_event_type_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(etype="QUOTE\x7f")

    def test_leading_whitespace_symbol_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(symbol=" BTCUSDT")

    def test_trailing_whitespace_symbol_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(symbol="BTCUSDT ")

    def test_leading_whitespace_venue_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(venue=" BINANCE")

    def test_trailing_whitespace_venue_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(venue="BINANCE ")

    def test_leading_whitespace_event_type_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(etype=" QUOTE")

    def test_trailing_whitespace_event_type_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(etype="QUOTE ")

    def test_only_whitespace_symbol_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(symbol=" ")

    def test_only_whitespace_venue_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(venue=" ")

    def test_only_whitespace_event_type_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(etype=" ")

    def test_only_tab_symbol_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(symbol="\t")

    def test_only_tab_venue_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(venue="\t")

    def test_only_tab_event_type_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(etype="\t")

    def test_only_newline_symbol_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(symbol="\n")

    def test_only_newline_venue_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(venue="\n")

    def test_only_newline_event_type_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(etype="\n")

    def test_only_carriage_return_symbol_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(symbol="\r")

    def test_only_carriage_return_venue_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(venue="\r")

    def test_only_carriage_return_event_type_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(etype="\r")

    def test_only_null_byte_symbol_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(symbol="\x00")

    def test_only_null_byte_venue_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(venue="\x00")

    def test_only_null_byte_event_type_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(etype="\x00")

    def test_only_control_char_symbol_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(symbol="\x01")

    def test_only_control_char_venue_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(venue="\x01")

    def test_only_control_char_event_type_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(etype="\x01")

    def test_only_high_control_char_symbol_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(symbol="\x1f")

    def test_only_high_control_char_venue_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(venue="\x1f")

    def test_only_high_control_char_event_type_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(etype="\x1f")

    def test_only_delete_char_symbol_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(symbol="\x7f")

    def test_only_delete_char_venue_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(venue="\x7f")

    def test_only_delete_char_event_type_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(etype="\x7f")

    def test_mixed_whitespace_symbol_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(symbol=" \t\n\r")

    def test_mixed_whitespace_venue_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(venue=" \t\n\r")

    def test_mixed_whitespace_event_type_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(etype=" \t\n\r")

    def test_mixed_control_chars_symbol_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(symbol="\x00\x01\x1f\x7f")

    def test_mixed_control_chars_venue_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(venue="\x00\x01\x1f\x7f")

    def test_mixed_control_chars_event_type_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(etype="\x00\x01\x1f\x7f")

    def test_all_whitespace_types_symbol_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(symbol=" \t\n\r\x0b\x0c")

    def test_all_whitespace_types_venue_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(venue=" \t\n\r\x0b\x0c")

    def test_all_whitespace_types_event_type_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(etype=" \t\n\r\x0b\x0c")

    def test_vertical_tab_symbol_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(symbol="BTC\x0bUSDT")

    def test_vertical_tab_venue_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(venue="BINANCE\x0b")

    def test_vertical_tab_event_type_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(etype="QUOTE\x0b")

    def test_form_feed_symbol_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(symbol="BTC\x0cUSDT")

    def test_form_feed_venue_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(venue="BINANCE\x0c")

    def test_form_feed_event_type_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(etype="QUOTE\x0c")

    def test_escape_char_symbol_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(symbol="BTC\x1bUSDT")

    def test_escape_char_venue_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(venue="BINANCE\x1b")

    def test_escape_char_event_type_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(etype="QUOTE\x1b")

    def test_bell_char_symbol_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(symbol="BTC\x07USDT")

    def test_bell_char_venue_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(venue="BINANCE\x07")

    def test_bell_char_event_type_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(etype="QUOTE\x07")

    def test_backspace_char_symbol_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(symbol="BTC\x08USDT")

    def test_backspace_char_venue_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(venue="BINANCE\x08")

    def test_backspace_char_event_type_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(etype="QUOTE\x08")

    def test_shift_out_char_symbol_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(symbol="BTC\x0eUSDT")

    def test_shift_out_char_venue_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(venue="BINANCE\x0e")

    def test_shift_out_char_event_type_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(etype="QUOTE\x0e")

    def test_shift_in_char_symbol_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(symbol="BTC\x0fUSDT")

    def test_shift_in_char_venue_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(venue="BINANCE\x0f")

    def test_shift_in_char_event_type_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(etype="QUOTE\x0f")

    def test_data_link_escape_char_symbol_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(symbol="BTC\x10USDT")

    def test_data_link_escape_char_venue_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(venue="BINANCE\x10")

    def test_data_link_escape_char_event_type_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(etype="QUOTE\x10")

    def test_device_control_1_char_symbol_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(symbol="BTC\x11USDT")

    def test_device_control_1_char_venue_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(venue="BINANCE\x11")

    def test_device_control_1_char_event_type_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(etype="QUOTE\x11")

    def test_device_control_2_char_symbol_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(symbol="BTC\x12USDT")

    def test_device_control_2_char_venue_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(venue="BINANCE\x12")

    def test_device_control_2_char_event_type_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(etype="QUOTE\x12")

    def test_device_control_3_char_symbol_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(symbol="BTC\x13USDT")

    def test_device_control_3_char_venue_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(venue="BINANCE\x13")

    def test_device_control_3_char_event_type_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(etype="QUOTE\x13")

    def test_device_control_4_char_symbol_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(symbol="BTC\x14USDT")

    def test_device_control_4_char_venue_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(venue="BINANCE\x14")

    def test_device_control_4_char_event_type_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(etype="QUOTE\x14")

    def test_negative_acknowledge_char_symbol_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(symbol="BTC\x15USDT")

    def test_negative_acknowledge_char_venue_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(venue="BINANCE\x15")

    def test_negative_acknowledge_char_event_type_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(etype="QUOTE\x15")

    def test_synchronous_idle_char_symbol_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(symbol="BTC\x16USDT")

    def test_synchronous_idle_char_venue_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(venue="BINANCE\x16")

    def test_synchronous_idle_char_event_type_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(etype="QUOTE\x16")

    def test_end_of_transmission_block_char_symbol_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(symbol="BTC\x17USDT")

    def test_end_of_transmission_block_char_venue_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(venue="BINANCE\x17")

    def test_end_of_transmission_block_char_event_type_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(etype="QUOTE\x17")

    def test_cancel_char_symbol_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(symbol="BTC\x18USDT")

    def test_cancel_char_venue_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(venue="BINANCE\x18")

    def test_cancel_char_event_type_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(etype="QUOTE\x18")

    def test_end_of_medium_char_symbol_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(symbol="BTC\x19USDT")

    def test_end_of_medium_char_venue_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(venue="BINANCE\x19")

    def test_end_of_medium_char_event_type_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(etype="QUOTE\x19")

    def test_substitute_char_symbol_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(symbol="BTC\x1aUSDT")

    def test_substitute_char_venue_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(venue="BINANCE\x1a")

    def test_substitute_char_event_type_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(etype="QUOTE\x1a")

    def test_information_separator_4_char_symbol_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(symbol="BTC\x1cUSDT")

    def test_information_separator_4_char_venue_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(venue="BINANCE\x1c")

    def test_information_separator_4_char_event_type_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(etype="QUOTE\x1c")

    def test_information_separator_3_char_symbol_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(symbol="BTC\x1dUSDT")

    def test_information_separator_3_char_venue_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(venue="BINANCE\x1d")

    def test_information_separator_3_char_event_type_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(etype="QUOTE\x1d")

    def test_information_separator_2_char_symbol_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(symbol="BTC\x1eUSDT")

    def test_information_separator_2_char_venue_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(venue="BINANCE\x1e")

    def test_information_separator_2_char_event_type_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(etype="QUOTE\x1e")

    def test_information_separator_1_char_symbol_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(symbol="BTC\x1fUSDT")

    def test_information_separator_1_char_venue_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(venue="BINANCE\x1f")

    def test_information_separator_1_char_event_type_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(etype="QUOTE\x1f")


class TestVenueStats:
    def test_creation(self):
        s = VenueStats(venue="BINANCE")
        assert s.venue == "BINANCE"
        assert s.event_count == 0
        assert s.last_sequence == 0
        assert s.gap_count == 0

    def test_record_event(self):
        s = VenueStats(venue="BINANCE")
        s.record_event(sequence=1)
        assert s.event_count == 1
        assert s.last_sequence == 1

    def test_detects_gap(self):
        s = VenueStats(venue="BINANCE")
        s.record_event(sequence=1)
        s.record_event(sequence=3)
        assert s.gap_count == 1

    def test_no_gap_consecutive(self):
        s = VenueStats(venue="BINANCE")
        s.record_event(sequence=1)
        s.record_event(sequence=2)
        s.record_event(sequence=3)
        assert s.gap_count == 0

    def test_multiple_gaps(self):
        s = VenueStats(venue="BINANCE")
        s.record_event(sequence=1)
        s.record_event(sequence=3)
        s.record_event(sequence=5)
        assert s.gap_count == 2

    def test_reset(self):
        s = VenueStats(venue="BINANCE")
        s.record_event(sequence=1)
        s.record_event(sequence=3)
        s.reset()
        assert s.event_count == 0
        assert s.last_sequence == 0
        assert s.gap_count == 0


class TestMultiVenueFeedHandler:
    def test_creation(self):
        h = MultiVenueFeedHandler(venues=["BINANCE", "COINBASE"])
        assert "BINANCE" in h.venues
        assert "COINBASE" in h.venues

    def test_ingest_single(self):
        h = MultiVenueFeedHandler(venues=["BINANCE"])
        h.ingest(make_event())
        assert h.get_stats("BINANCE").event_count == 1

    def test_ingest_multiple_venues(self):
        h = MultiVenueFeedHandler(venues=["BINANCE", "COINBASE", "KRAKEN"])
        for v in ["BINANCE", "COINBASE", "KRAKEN"]:
            h.ingest(make_event(venue=v))
        assert h.get_stats("BINANCE").event_count == 1
        assert h.get_stats("COINBASE").event_count == 1
        assert h.get_stats("KRAKEN").event_count == 1

    def test_rejects_unknown_venue(self):
        h = MultiVenueFeedHandler(venues=["BINANCE"])
        with pytest.raises(FeedError):
            h.ingest(make_event(venue="UNKNOWN"))

    def test_detects_sequence_gap(self):
        h = MultiVenueFeedHandler(venues=["BINANCE"])
        h.ingest(make_event(seq=1))
        h.ingest(make_event(seq=3))
        assert h.get_stats("BINANCE").gap_count == 1

    def test_get_events_by_venue(self):
        h = MultiVenueFeedHandler(venues=["BINANCE", "COINBASE"])
        for i in range(5):
            h.ingest(make_event(venue="BINANCE", seq=i + 1))
        for i in range(3):
            h.ingest(make_event(venue="COINBASE", seq=i + 1))
        assert len(h.get_events_by_venue("BINANCE")) == 5
        assert len(h.get_events_by_venue("COINBASE")) == 3

    def test_get_events_by_symbol(self):
        h = MultiVenueFeedHandler(venues=["BINANCE"])
        for i in range(3):
            h.ingest(make_event(symbol="BTCUSDT", seq=i + 1))
        for i in range(2):
            h.ingest(make_event(symbol="ETHUSDT", seq=i + 10))
        assert len(h.get_events_by_symbol("BTCUSDT")) == 3
        assert len(h.get_events_by_symbol("ETHUSDT")) == 2

    def test_total_event_count(self):
        h = MultiVenueFeedHandler(venues=["BINANCE", "COINBASE"])
        for i in range(10):
            h.ingest(make_event(venue="BINANCE", seq=i + 1))
        for i in range(5):
            h.ingest(make_event(venue="COINBASE", seq=i + 1))
        assert h.total_event_count == 15

    def test_throughput(self):
        h = MultiVenueFeedHandler(venues=["BINANCE"])
        start = time.monotonic()
        for i in range(1000):
            h.ingest(make_event(seq=i + 1))
        elapsed = time.monotonic() - start
        assert h.get_throughput() > 0
        assert h.get_stats("BINANCE").event_count == 1000

    def test_batch_ingest(self):
        h = MultiVenueFeedHandler(venues=["BINANCE"])
        events = [make_event(seq=i + 1) for i in range(100)]
        h.ingest_batch(events)
        assert h.get_stats("BINANCE").event_count == 100

    def test_batch_ingest_empty(self):
        h = MultiVenueFeedHandler(venues=["BINANCE"])
        h.ingest_batch([])
        assert h.get_stats("BINANCE").event_count == 0

    def test_concurrent_ingestion(self):
        h = MultiVenueFeedHandler(venues=["BINANCE", "COINBASE"])
        errors = []

        def ingest_events(venue, count):
            try:
                for i in range(count):
                    h.ingest(make_event(venue=venue, seq=i + 1))
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=ingest_events, args=("BINANCE", 500)),
            threading.Thread(target=ingest_events, args=("COINBASE", 500)),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)
        assert not errors
        assert h.get_stats("BINANCE").event_count == 500
        assert h.get_stats("COINBASE").event_count == 500

    def test_heartbeat_event(self):
        h = MultiVenueFeedHandler(venues=["BINANCE"])
        h.ingest(make_event(bid=0, ask=0, bsize=0, asize=0, etype="HEARTBEAT"))
        assert h.get_stats("BINANCE").event_count == 1

    def test_trade_event(self):
        h = MultiVenueFeedHandler(venues=["BINANCE"])
        h.ingest(make_event(bid=50000.0, ask=0, bsize=10, asize=0, etype="TRADE"))
        assert h.get_stats("BINANCE").event_count == 1

    def test_book_update_event(self):
        h = MultiVenueFeedHandler(venues=["BINANCE"])
        h.ingest(make_event(bid=50000.0, ask=50010.0, bsize=100, asize=200, etype="BOOK_UPDATE"))
        assert h.get_stats("BINANCE").event_count == 1

    def test_get_all_stats(self):
        h = MultiVenueFeedHandler(venues=["BINANCE", "COINBASE"])
        for v in ["BINANCE", "COINBASE"]:
            h.ingest(make_event(venue=v))
        stats = h.get_all_stats()
        assert "BINANCE" in stats
        assert "COINBASE" in stats

    def test_reset_stats(self):
        h = MultiVenueFeedHandler(venues=["BINANCE"])
        h.ingest(make_event())
        h.reset_stats()
        assert h.get_stats("BINANCE").event_count == 0

    def test_is_healthy(self):
        h = MultiVenueFeedHandler(venues=["BINANCE"])
        assert h.is_healthy()

    def test_is_healthy_with_events(self):
        h = MultiVenueFeedHandler(venues=["BINANCE"])
        h.ingest(make_event())
        assert h.is_healthy()

    def test_venue_list(self):
        h = MultiVenueFeedHandler(venues=["BINANCE", "COINBASE", "KRAKEN"])
        assert len(h.venues) == 3

    def test_large_batch_performance(self):
        h = MultiVenueFeedHandler(venues=["BINANCE"])
        events = [make_event(symbol=f"S{i % 100}", seq=i + 1) for i in range(10000)]
        start = time.monotonic()
        h.ingest_batch(events)
        elapsed = time.monotonic() - start
        assert h.get_stats("BINANCE").event_count == 10000
        assert elapsed < 1.0

    def test_consumer_lag(self):
        h = MultiVenueFeedHandler(venues=["BINANCE"])
        for i in range(100):
            h.ingest(make_event(seq=i + 1))
        assert h.get_consumer_lag() == 100

    def test_consumer_lag_after_read(self):
        h = MultiVenueFeedHandler(venues=["BINANCE"])
        for i in range(100):
            h.ingest(make_event(seq=i + 1))
        for _ in range(50):
            h.get_next_event()
        assert h.get_consumer_lag() == 50

    def test_get_next_event_fifo(self):
        h = MultiVenueFeedHandler(venues=["BINANCE"])
        for i in range(5):
            h.ingest(make_event(symbol=f"SYM{i}", seq=i + 1))
        for i in range(5):
            assert h.get_next_event().symbol == f"SYM{i}"

    def test_get_next_event_empty(self):
        h = MultiVenueFeedHandler(venues=["BINANCE"])
        assert h.get_next_event() is None

    def test_multiple_venues_independent_sequences(self):
        h = MultiVenueFeedHandler(venues=["BINANCE", "COINBASE"])
        for i in range(1, 4):
            h.ingest(make_event(venue="BINANCE", seq=i))
        for i in range(1, 4):
            h.ingest(make_event(venue="COINBASE", seq=i))
        assert h.get_stats("BINANCE").last_sequence == 3
        assert h.get_stats("COINBASE").last_sequence == 3
        assert h.get_stats("BINANCE").gap_count == 0
        assert h.get_stats("COINBASE").gap_count == 0

    def test_venue_failover_simulation(self):
        h = MultiVenueFeedHandler(venues=["BINANCE", "COINBASE"])
        for i in range(10):
            h.ingest(make_event(venue="BINANCE", seq=i + 1))
        for i in range(10, 20):
            h.ingest(make_event(venue="COINBASE", seq=i + 1))
        assert h.get_stats("BINANCE").event_count == 10
        assert h.get_stats("COINBASE").event_count == 10
        assert h.total_event_count == 20

    def test_event_filtering_by_type(self):
        h = MultiVenueFeedHandler(venues=["BINANCE"])
        for etype in ["QUOTE", "TRADE", "BOOK_UPDATE", "HEARTBEAT"]:
            h.ingest(make_event(etype=etype))
        assert len(h.get_events_by_type("QUOTE")) == 1
        assert len(h.get_events_by_type("TRADE")) == 1

    def test_event_filtering_by_venue_and_symbol(self):
        h = MultiVenueFeedHandler(venues=["BINANCE", "COINBASE"])
        h.ingest(make_event(venue="BINANCE", symbol="BTCUSDT"))
        h.ingest(make_event(venue="COINBASE", symbol="ETHUSDT"))
        events = h.get_events(venue="BINANCE", symbol="BTCUSDT")
        assert len(events) == 1
        assert events[0].venue == "BINANCE"
        assert events[0].symbol == "BTCUSDT"

    def test_ring_buffer_capacity(self):
        h = MultiVenueFeedHandler(venues=["BINANCE"], ring_buffer_capacity=100)
        assert h.ring_buffer.capacity == 100

    def test_default_ring_buffer_capacity(self):
        h = MultiVenueFeedHandler(venues=["BINANCE"])
        assert h.ring_buffer.capacity >= 1024

    def test_throughput_over_100k(self):
        h = MultiVenueFeedHandler(venues=["BINANCE"])
        events = [make_event(symbol=f"S{i % 100}", seq=i + 1) for i in range(50000)]
        start = time.monotonic()
        h.ingest_batch(events)
        elapsed = time.monotonic() - start
        assert 50000 / elapsed > 100000

    def test_zero_copy_semantics(self):
        h = MultiVenueFeedHandler(venues=["BINANCE"])
        h.ingest(make_event())
        peeked = h.ring_buffer.peek()
        assert peeked is not None
        assert peeked.symbol == "BTCUSDT"

    def test_event_ordering_preserved(self):
        h = MultiVenueFeedHandler(venues=["BINANCE"])
        for i in range(100):
            h.ingest(make_event(symbol=f"SYM{i}", seq=i + 1))
        for i in range(100):
            assert h.get_next_event().sequence == i + 1

    def test_stats_accuracy(self):
        h = MultiVenueFeedHandler(venues=["BINANCE", "COINBASE"])
        for i in range(10):
            h.ingest(make_event(venue="BINANCE", seq=i + 1))
        for i in range(5):
            h.ingest(make_event(venue="COINBASE", seq=i + 1))
        assert h.get_stats("BINANCE").event_count == 10
        assert h.get_stats("COINBASE").event_count == 5
        assert h.get_stats("BINANCE").last_sequence == 10
        assert h.get_stats("COINBASE").last_sequence == 5
        assert h.total_event_count == 15

    def test_venue_stats_isolation(self):
        h = MultiVenueFeedHandler(venues=["BINANCE", "COINBASE"])
        h.ingest(make_event(venue="BINANCE", seq=1))
        h.ingest(make_event(venue="BINANCE", seq=3))
        h.ingest(make_event(venue="COINBASE", seq=1))
        h.ingest(make_event(venue="COINBASE", seq=2))
        assert h.get_stats("BINANCE").gap_count == 1
        assert h.get_stats("COINBASE").gap_count == 0

    def test_event_serialization_size(self):
        e = make_event()
        assert len(e.to_bytes()) < 200

    def test_event_deserialization_speed(self):
        e = make_event()
        data = e.to_bytes()
        start = time.monotonic()
        for _ in range(10000):
            MarketDataEvent.from_bytes(data)
        elapsed = time.monotonic() - start
        assert elapsed < 1.0

    def test_ingest_after_clear(self):
        h = MultiVenueFeedHandler(venues=["BINANCE"])
        for i in range(10):
            h.ingest(make_event(symbol=f"SYM{i}", seq=i + 1))
        h.ring_buffer.clear()
        assert h.get_stats("BINANCE").event_count == 10
        for i in range(10, 20):
            h.ingest(make_event(symbol=f"SYM{i}", seq=i + 1))
        assert h.get_stats("BINANCE").event_count == 20

    def test_multiple_symbols_per_venue(self):
        h = MultiVenueFeedHandler(venues=["BINANCE"])
        for i, sym in enumerate(["BTCUSDT", "ETHUSDT", "SOLUSDT"]):
            h.ingest(make_event(symbol=sym, seq=i + 1))
        for sym in ["BTCUSDT", "ETHUSDT", "SOLUSDT"]:
            assert len(h.get_events_by_symbol(sym)) == 1

    def test_venue_case_sensitivity(self):
        h = MultiVenueFeedHandler(venues=["BINANCE"])
        with pytest.raises(FeedError):
            h.ingest(make_event(venue="binance"))

    def test_event_type_case_sensitivity(self):
        with pytest.raises(EventValidationError):
            make_event(etype="quote")

    def test_large_symbol_name(self):
        h = MultiVenueFeedHandler(venues=["BINANCE"])
        h.ingest(make_event(symbol="A" * 50))
        assert len(h.get_events_by_symbol("A" * 50)) == 1

    def test_large_venue_name(self):
        h = MultiVenueFeedHandler(venues=["A" * 50])
        h.ingest(make_event(venue="A" * 50))
        assert h.get_stats("A" * 50).event_count == 1

    def test_negative_bid_size(self):
        with pytest.raises(EventValidationError):
            make_event(bsize=-1)

    def test_negative_ask_size(self):
        with pytest.raises(EventValidationError):
            make_event(asize=-1)

    def test_zero_bid_size_valid(self):
        e = make_event(bid=0, ask=0, bsize=0, asize=0, etype="HEARTBEAT")
        assert e.bid_size == 0

    def test_zero_ask_size_valid(self):
        e = make_event(bid=0, ask=0, bsize=0, asize=0, etype="HEARTBEAT")
        assert e.ask_size == 0

    def test_inverted_spread_valid(self):
        e = make_event(bid=2.0, ask=1.0, etype="TRADE")
        assert e.spread == pytest.approx(-1.0)

    def test_trade_event_zero_ask(self):
        e = make_event(bid=50000.0, ask=0, bsize=10, asize=0, etype="TRADE")
        assert e.ask_price == 0.0
        assert e.ask_size == 0

    def test_book_update_event(self):
        e = make_event(bid=50000.0, ask=50010.0, bsize=100, asize=200, etype="BOOK_UPDATE")
        assert e.event_type == "BOOK_UPDATE"
        assert e.bid_size == 100
        assert e.ask_size == 200

    def test_heartbeat_event_zero_prices(self):
        e = make_event(bid=0, ask=0, bsize=0, asize=0, etype="HEARTBEAT")
        assert e.bid_price == 0.0
        assert e.ask_price == 0.0

    def test_sequence_number_overflow(self):
        e = make_event(seq=2**63 - 1)
        assert e.sequence == 2**63 - 1

    def test_timestamp_overflow(self):
        e = make_event(ts=2**63 - 1)
        assert e.timestamp_ns == 2**63 - 1

    def test_very_small_prices(self):
        e = make_event(bid=0.00000001, ask=0.00000002)
        assert e.bid_price == pytest.approx(0.00000001)
        assert e.ask_price == pytest.approx(0.00000002)

    def test_very_large_prices(self):
        e = make_event(bid=1e9, ask=1e9 + 1)
        assert e.bid_price == pytest.approx(1e9)
        assert e.ask_price == pytest.approx(1e9 + 1)

    def test_very_large_sizes(self):
        e = make_event(bsize=2**63 - 1, asize=2**63 - 1)
        assert e.bid_size == 2**63 - 1
        assert e.ask_size == 2**63 - 1

    def test_event_equality(self):
        assert make_event() == make_event()
        assert make_event() != make_event(symbol="ETHUSDT")

    def test_event_hash(self):
        assert hash(make_event()) == hash(make_event())

    def test_event_repr(self):
        assert "BTCUSDT" in repr(make_event())
        assert "BINANCE" in repr(make_event())

    def test_event_str(self):
        assert "BTCUSDT" in str(make_event())
        assert "BINANCE" in str(make_event())

    def test_ring_buffer_len(self):
        rb = RingBuffer(capacity=10)
        assert len(rb) == 0
        rb.push(make_event())
        assert len(rb) == 1

    def test_ring_buffer_bool(self):
        rb = RingBuffer(capacity=10)
        assert not rb
        rb.push(make_event())
        assert rb

    def test_ring_buffer_iter(self):
        rb = RingBuffer(capacity=10)
        for i in range(3):
            rb.push(make_event(symbol=f"SYM{i}", seq=i + 1))
        assert [e.symbol for e in rb] == ["SYM0", "SYM1", "SYM2"]

    def test_ring_buffer_contains(self):
        rb = RingBuffer(capacity=10)
        e = make_event()
        rb.push(e)
        assert e in rb
        assert make_event(symbol="ETHUSDT") not in rb

    def test_ring_buffer_getitem(self):
        rb = RingBuffer(capacity=10)
        for i in range(3):
            rb.push(make_event(symbol=f"SYM{i}", seq=i + 1))
        assert rb[0].symbol == "SYM0"
        assert rb[2].symbol == "SYM2"

    def test_ring_buffer_getitem_out_of_range(self):
        rb = RingBuffer(capacity=10)
        rb.push(make_event())
        with pytest.raises(IndexError):
            _ = rb[5]

    def test_ring_buffer_slice(self):
        rb = RingBuffer(capacity=10)
        for i in range(5):
            rb.push(make_event(symbol=f"SYM{i}", seq=i + 1))
        assert [e.symbol for e in rb[1:3]] == ["SYM1", "SYM2"]

    def test_ring_buffer_reversed(self):
        rb = RingBuffer(capacity=10)
        for i in range(3):
            rb.push(make_event(symbol=f"SYM{i}", seq=i + 1))
        assert [e.symbol for e in reversed(rb)] == ["SYM2", "SYM1", "SYM0"]

    def test_ring_buffer_count(self):
        rb = RingBuffer(capacity=10)
        e = make_event()
        rb.push(e)
        rb.push(e)
        assert rb.count(e) == 2

    def test_ring_buffer_index(self):
        rb = RingBuffer(capacity=10)
        e = make_event()
        rb.push(e)
        assert rb.index(e) == 0

    def test_ring_buffer_index_not_found(self):
        rb = RingBuffer(capacity=10)
        rb.push(make_event())
        with pytest.raises(ValueError):
            rb.index(make_event(symbol="ETHUSDT"))

    def test_ring_buffer_extend(self):
        rb = RingBuffer(capacity=10)
        events = [make_event(symbol=f"SYM{i}", seq=i + 1) for i in range(5)]
        rb.extend(events)
        assert len(rb) == 5

    def test_ring_buffer_extend_overflow(self):
        rb = RingBuffer(capacity=3)
        events = [make_event(symbol=f"SYM{i}", seq=i + 1) for i in range(5)]
        rb.extend(events)
        assert len(rb) == 3
        assert rb[0].symbol == "SYM2"

    def test_ring_buffer_popleft(self):
        rb = RingBuffer(capacity=10)
        for i in range(3):
            rb.push(make_event(symbol=f"SYM{i}", seq=i + 1))
        assert rb.popleft().symbol == "SYM0"
        assert len(rb) == 2

    def test_ring_buffer_pop_right(self):
        rb = RingBuffer(capacity=10)
        for i in range(3):
            rb.push(make_event(symbol=f"SYM{i}", seq=i + 1))
        assert rb.pop().symbol == "SYM2"
        assert len(rb) == 2

    def test_ring_buffer_pop_right_empty(self):
        assert RingBuffer(capacity=10).pop() is None

    def test_ring_buffer_remove(self):
        rb = RingBuffer(capacity=10)
        e = make_event()
        rb.push(e)
        rb.remove(e)
        assert len(rb) == 0

    def test_ring_buffer_remove_not_found(self):
        rb = RingBuffer(capacity=10)
        rb.push(make_event())
        with pytest.raises(ValueError):
            rb.remove(make_event(symbol="ETHUSDT"))

    def test_ring_buffer_rotate(self):
        rb = RingBuffer(capacity=10)
        for i in range(5):
            rb.push(make_event(symbol=f"SYM{i}", seq=i + 1))
        rb.rotate(2)
        assert rb[0].symbol == "SYM3"

    def test_ring_buffer_rotate_negative(self):
        rb = RingBuffer(capacity=10)
        for i in range(5):
            rb.push(make_event(symbol=f"SYM{i}", seq=i + 1))
        rb.rotate(-2)
        assert rb[0].symbol == "SYM2"

    def test_ring_buffer_reverse(self):
        rb = RingBuffer(capacity=10)
        for i in range(3):
            rb.push(make_event(symbol=f"SYM{i}", seq=i + 1))
        rb.reverse()
        assert rb[0].symbol == "SYM2"

    def test_ring_buffer_copy(self):
        rb = RingBuffer(capacity=10)
        for i in range(3):
            rb.push(make_event(symbol=f"SYM{i}", seq=i + 1))
        c = rb.copy()
        assert len(c) == 3
        rb.clear()
        assert len(c) == 3

    def test_ring_buffer_maxlen(self):
        assert RingBuffer(capacity=100).maxlen == 100

    def test_ring_buffer_maxlen_readonly(self):
        rb = RingBuffer(capacity=100)
        with pytest.raises(AttributeError):
            rb.maxlen = 200

    def test_ring_buffer_full_behavior(self):
        rb = RingBuffer(capacity=3)
        for i in range(3):
            rb.push(make_event(symbol=f"SYM{i}", seq=i + 1))
        assert rb.is_full()
        rb.push(make_event(symbol="SYM3", seq=4))
        assert rb.size == 3
        assert rb[0].symbol == "SYM1"

    def test_ring_buffer_empty_behavior(self):
        rb = RingBuffer(capacity=10)
        assert rb.is_empty()
        assert rb.pop() is None
        assert rb.peek() is None
        assert len(rb) == 0

    def test_ring_buffer_single_element(self):
        rb = RingBuffer(capacity=10)
        e = make_event()
        rb.push(e)
        assert rb.size == 1
        assert rb.peek() == e
        assert rb.pop() == e
        assert rb.size == 0

    def test_ring_buffer_two_elements(self):
        rb = RingBuffer(capacity=10)
        e1 = make_event(symbol="BTCUSDT", seq=1)
        e2 = make_event(symbol="ETHUSDT", seq=2)
        rb.push(e1)
        rb.push(e2)
        assert rb.size == 2
        assert rb.pop() == e1
        assert rb.pop() == e2

    def test_ring_buffer_capacity_one(self):
        rb = RingBuffer(capacity=1)
        e1 = make_event(symbol="BTCUSDT", seq=1)
        e2 = make_event(symbol="ETHUSDT", seq=2)
        rb.push(e1)
        assert rb.is_full()
        rb.push(e2)
        assert rb.size == 1
        assert rb.pop() == e2

    def test_ring_buffer_capacity_two(self):
        rb = RingBuffer(capacity=2)
        for i in range(4):
            rb.push(make_event(symbol=f"SYM{i}", seq=i + 1))
        assert rb.size == 2
        assert rb[0].symbol == "SYM2"
        assert rb[1].symbol == "SYM3"

    def test_ring_buffer_large_capacity(self):
        rb = RingBuffer(capacity=1_000_000)
        assert rb.capacity == 1_048_576
        rb.push(make_event())
        assert rb.size == 1

    def test_ring_buffer_throughput(self):
        rb = RingBuffer(capacity=100000)
        start = time.monotonic()
        for i in range(50000):
            rb.push(make_event(symbol=f"S{i % 100}", seq=i + 1))
        elapsed = time.monotonic() - start
        assert 50000 / elapsed > 100000

    def test_ring_buffer_memory_efficiency(self):
        import sys
        rb = RingBuffer(capacity=1000)
        rb.push(make_event())
        assert sys.getsizeof(rb._buffer) < 10_000_000

    def test_ring_buffer_thread_safety_stress(self):
        rb = RingBuffer(capacity=10000)
        errors = []

        def producer(tid):
            try:
                for i in range(1000):
                    rb.push(make_event(symbol=f"S{tid}_{i}", seq=i + 1))
            except Exception as e:
                errors.append(e)

        def consumer():
            try:
                count = 0
                while count < 4000:
                    if rb.pop() is not None:
                        count += 1
                    else:
                        time.sleep(0.001)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=producer, args=(i,)) for i in range(4)]
        threads.append(threading.Thread(target=consumer))
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
        assert not errors

    def test_ring_buffer_concurrent_push_pop(self):
        rb = RingBuffer(capacity=1000)
        errors = []
        stop = threading.Event()

        def pusher():
            try:
                i = 0
                while not stop.is_set():
                    rb.push(make_event(symbol=f"S{i % 10}", seq=i + 1))
                    i += 1
            except Exception as e:
                errors.append(e)

        def popper():
            try:
                while not stop.is_set():
                    rb.pop()
            except Exception as e:
                errors.append(e)

        t1 = threading.Thread(target=pusher)
        t2 = threading.Thread(target=popper)
        t1.start()
        t2.start()
        time.sleep(0.5)
        stop.set()
        t1.join(timeout=5)
        t2.join(timeout=5)
        assert not errors

    def test_ring_buffer_event_validation(self):
        rb = RingBuffer(capacity=10)
        with pytest.raises((TypeError, AttributeError)):
            rb.push("not an event")

    def test_ring_buffer_none_event(self):
        rb = RingBuffer(capacity=10)
        with pytest.raises((TypeError, AttributeError)):
            rb.push(None)

    def test_ring_buffer_invalid_type(self):
        rb = RingBuffer(capacity=10)
        with pytest.raises((TypeError, AttributeError)):
            rb.push(123)

    def test_ring_buffer_int_price_accepted(self):
        rb = RingBuffer(capacity=10)
        rb.push(make_event(bid=1, ask=2))
        assert rb.size == 1

    def test_ring_buffer_float_size_rejected(self):
        with pytest.raises((TypeError, AttributeError)):
            make_event(bsize=1.5)

    def test_ring_buffer_negative_size_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(bsize=-1)

    def test_ring_buffer_zero_sequence_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(seq=0)

    def test_ring_buffer_negative_sequence_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(seq=-1)

    def test_ring_buffer_empty_venue_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(venue="")

    def test_ring_buffer_empty_event_type_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(etype="")

    def test_ring_buffer_invalid_event_type_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(etype="INVALID")

    def test_ring_buffer_lowercase_event_type_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(etype="quote")

    def test_ring_buffer_mixed_case_event_type_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(etype="Quote")

    def test_ring_buffer_whitespace_symbol_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(symbol="   ")

    def test_ring_buffer_whitespace_venue_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(venue="   ")

    def test_ring_buffer_whitespace_event_type_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(etype="   ")

    def test_ring_buffer_special_chars_symbol(self):
        rb = RingBuffer(capacity=10)
        rb.push(make_event(symbol="BTC-USDT"))
        assert rb.size == 1

    def test_ring_buffer_unicode_symbol(self):
        rb = RingBuffer(capacity=10)
        rb.push(make_event(symbol="BTCUSDT🚀"))
        assert rb.size == 1

    def test_ring_buffer_unicode_venue(self):
        rb = RingBuffer(capacity=10)
        rb.push(make_event(venue="BİNANCE"))
        assert rb.size == 1

    def test_ring_buffer_unicode_event_type_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(etype="QUOTE🚀")

    def test_ring_buffer_newline_symbol_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(symbol="BTC\nUSDT")

    def test_ring_buffer_tab_symbol_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(symbol="BTC\tUSDT")

    def test_ring_buffer_carriage_return_symbol_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(symbol="BTC\rUSDT")

    def test_ring_buffer_null_byte_symbol_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(symbol="BTC\x00USDT")

    def test_ring_buffer_control_chars_symbol_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(symbol="BTC\x01USDT")

    def test_ring_buffer_high_control_chars_symbol_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(symbol="BTC\x1fUSDT")

    def test_ring_buffer_delete_char_symbol_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(symbol="BTC\x7fUSDT")

    def test_ring_buffer_newline_venue_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(venue="BINANCE\n")

    def test_ring_buffer_tab_venue_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(venue="BINANCE\t")

    def test_ring_buffer_carriage_return_venue_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(venue="BINANCE\r")

    def test_ring_buffer_null_byte_venue_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(venue="BINANCE\x00")

    def test_ring_buffer_control_chars_venue_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(venue="BINANCE\x01")

    def test_ring_buffer_high_control_chars_venue_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(venue="BINANCE\x1f")

    def test_ring_buffer_delete_char_venue_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(venue="BINANCE\x7f")

    def test_ring_buffer_newline_event_type_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(etype="QUOTE\n")

    def test_ring_buffer_tab_event_type_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(etype="QUOTE\t")

    def test_ring_buffer_carriage_return_event_type_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(etype="QUOTE\r")

    def test_ring_buffer_null_byte_event_type_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(etype="QUOTE\x00")

    def test_ring_buffer_control_chars_event_type_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(etype="QUOTE\x01")

    def test_ring_buffer_high_control_chars_event_type_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(etype="QUOTE\x1f")

    def test_ring_buffer_delete_char_event_type_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(etype="QUOTE\x7f")

    def test_ring_buffer_leading_whitespace_symbol_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(symbol=" BTCUSDT")

    def test_ring_buffer_trailing_whitespace_symbol_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(symbol="BTCUSDT ")

    def test_ring_buffer_leading_whitespace_venue_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(venue=" BINANCE")

    def test_ring_buffer_trailing_whitespace_venue_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(venue="BINANCE ")

    def test_ring_buffer_leading_whitespace_event_type_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(etype=" QUOTE")

    def test_ring_buffer_trailing_whitespace_event_type_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(etype="QUOTE ")

    def test_ring_buffer_multiple_whitespace_symbol_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(symbol="BTC  USDT")

    def test_ring_buffer_multiple_whitespace_venue_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(venue="BINANCE  ")

    def test_ring_buffer_multiple_whitespace_event_type_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(etype="QUOTE  ")

    def test_ring_buffer_only_whitespace_symbol_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(symbol=" ")

    def test_ring_buffer_only_whitespace_venue_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(venue=" ")

    def test_ring_buffer_only_whitespace_event_type_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(etype=" ")

    def test_ring_buffer_only_tab_symbol_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(symbol="\t")

    def test_ring_buffer_only_tab_venue_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(venue="\t")

    def test_ring_buffer_only_tab_event_type_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(etype="\t")

    def test_ring_buffer_only_newline_symbol_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(symbol="\n")

    def test_ring_buffer_only_newline_venue_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(venue="\n")

    def test_ring_buffer_only_newline_event_type_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(etype="\n")

    def test_ring_buffer_only_carriage_return_symbol_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(symbol="\r")

    def test_ring_buffer_only_carriage_return_venue_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(venue="\r")

    def test_ring_buffer_only_carriage_return_event_type_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(etype="\r")

    def test_ring_buffer_only_null_byte_symbol_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(symbol="\x00")

    def test_ring_buffer_only_null_byte_venue_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(venue="\x00")

    def test_ring_buffer_only_null_byte_event_type_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(etype="\x00")

    def test_ring_buffer_only_control_char_symbol_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(symbol="\x01")

    def test_ring_buffer_only_control_char_venue_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(venue="\x01")

    def test_ring_buffer_only_control_char_event_type_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(etype="\x01")

    def test_ring_buffer_only_high_control_char_symbol_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(symbol="\x1f")

    def test_ring_buffer_only_high_control_char_venue_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(venue="\x1f")

    def test_ring_buffer_only_high_control_char_event_type_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(etype="\x1f")

    def test_ring_buffer_only_delete_char_symbol_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(symbol="\x7f")

    def test_ring_buffer_only_delete_char_venue_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(venue="\x7f")

    def test_ring_buffer_only_delete_char_event_type_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(etype="\x7f")

    def test_ring_buffer_mixed_whitespace_symbol_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(symbol=" \t\n\r")

    def test_ring_buffer_mixed_whitespace_venue_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(venue=" \t\n\r")

    def test_ring_buffer_mixed_whitespace_event_type_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(etype=" \t\n\r")

    def test_ring_buffer_mixed_control_chars_symbol_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(symbol="\x00\x01\x1f\x7f")

    def test_ring_buffer_mixed_control_chars_venue_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(venue="\x00\x01\x1f\x7f")

    def test_ring_buffer_mixed_control_chars_event_type_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(etype="\x00\x01\x1f\x7f")

    def test_ring_buffer_all_whitespace_types_symbol_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(symbol=" \t\n\r\x0b\x0c")

    def test_ring_buffer_all_whitespace_types_venue_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(venue=" \t\n\r\x0b\x0c")

    def test_ring_buffer_all_whitespace_types_event_type_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(etype=" \t\n\r\x0b\x0c")

    def test_ring_buffer_vertical_tab_symbol_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(symbol="BTC\x0bUSDT")

    def test_ring_buffer_vertical_tab_venue_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(venue="BINANCE\x0b")

    def test_ring_buffer_vertical_tab_event_type_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(etype="QUOTE\x0b")

    def test_ring_buffer_form_feed_symbol_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(symbol="BTC\x0cUSDT")

    def test_ring_buffer_form_feed_venue_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(venue="BINANCE\x0c")

    def test_ring_buffer_form_feed_event_type_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(etype="QUOTE\x0c")

    def test_ring_buffer_escape_char_symbol_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(symbol="BTC\x1bUSDT")

    def test_ring_buffer_escape_char_venue_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(venue="BINANCE\x1b")

    def test_ring_buffer_escape_char_event_type_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(etype="QUOTE\x1b")

    def test_ring_buffer_bell_char_symbol_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(symbol="BTC\x07USDT")

    def test_ring_buffer_bell_char_venue_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(venue="BINANCE\x07")

    def test_ring_buffer_bell_char_event_type_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(etype="QUOTE\x07")

    def test_ring_buffer_backspace_char_symbol_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(symbol="BTC\x08USDT")

    def test_ring_buffer_backspace_char_venue_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(venue="BINANCE\x08")

    def test_ring_buffer_backspace_char_event_type_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(etype="QUOTE\x08")

    def test_ring_buffer_shift_out_char_symbol_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(symbol="BTC\x0eUSDT")

    def test_ring_buffer_shift_out_char_venue_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(venue="BINANCE\x0e")

    def test_ring_buffer_shift_out_char_event_type_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(etype="QUOTE\x0e")

    def test_ring_buffer_shift_in_char_symbol_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(symbol="BTC\x0fUSDT")

    def test_ring_buffer_shift_in_char_venue_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(venue="BINANCE\x0f")

    def test_ring_buffer_shift_in_char_event_type_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(etype="QUOTE\x0f")

    def test_ring_buffer_data_link_escape_char_symbol_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(symbol="BTC\x10USDT")

    def test_ring_buffer_data_link_escape_char_venue_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(venue="BINANCE\x10")

    def test_ring_buffer_data_link_escape_char_event_type_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(etype="QUOTE\x10")

    def test_ring_buffer_device_control_1_char_symbol_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(symbol="BTC\x11USDT")

    def test_ring_buffer_device_control_1_char_venue_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(venue="BINANCE\x11")

    def test_ring_buffer_device_control_1_char_event_type_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(etype="QUOTE\x11")

    def test_ring_buffer_device_control_2_char_symbol_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(symbol="BTC\x12USDT")

    def test_ring_buffer_device_control_2_char_venue_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(venue="BINANCE\x12")

    def test_ring_buffer_device_control_2_char_event_type_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(etype="QUOTE\x12")

    def test_ring_buffer_device_control_3_char_symbol_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(symbol="BTC\x13USDT")

    def test_ring_buffer_device_control_3_char_venue_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(venue="BINANCE\x13")

    def test_ring_buffer_device_control_3_char_event_type_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(etype="QUOTE\x13")

    def test_ring_buffer_device_control_4_char_symbol_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(symbol="BTC\x14USDT")

    def test_ring_buffer_device_control_4_char_venue_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(venue="BINANCE\x14")

    def test_ring_buffer_device_control_4_char_event_type_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(etype="QUOTE\x14")

    def test_ring_buffer_negative_acknowledge_char_symbol_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(symbol="BTC\x15USDT")

    def test_ring_buffer_negative_acknowledge_char_venue_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(venue="BINANCE\x15")

    def test_ring_buffer_negative_acknowledge_char_event_type_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(etype="QUOTE\x15")

    def test_ring_buffer_synchronous_idle_char_symbol_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(symbol="BTC\x16USDT")

    def test_ring_buffer_synchronous_idle_char_venue_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(venue="BINANCE\x16")

    def test_ring_buffer_synchronous_idle_char_event_type_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(etype="QUOTE\x16")

    def test_ring_buffer_end_of_transmission_block_char_symbol_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(symbol="BTC\x17USDT")

    def test_ring_buffer_end_of_transmission_block_char_venue_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(venue="BINANCE\x17")

    def test_ring_buffer_end_of_transmission_block_char_event_type_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(etype="QUOTE\x17")

    def test_ring_buffer_cancel_char_symbol_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(symbol="BTC\x18USDT")

    def test_ring_buffer_cancel_char_venue_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(venue="BINANCE\x18")

    def test_ring_buffer_cancel_char_event_type_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(etype="QUOTE\x18")

    def test_ring_buffer_end_of_medium_char_symbol_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(symbol="BTC\x19USDT")

    def test_ring_buffer_end_of_medium_char_venue_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(venue="BINANCE\x19")

    def test_ring_buffer_end_of_medium_char_event_type_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(etype="QUOTE\x19")

    def test_ring_buffer_substitute_char_symbol_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(symbol="BTC\x1aUSDT")

    def test_ring_buffer_substitute_char_venue_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(venue="BINANCE\x1a")

    def test_ring_buffer_substitute_char_event_type_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(etype="QUOTE\x1a")

    def test_ring_buffer_information_separator_4_char_symbol_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(symbol="BTC\x1cUSDT")

    def test_ring_buffer_information_separator_4_char_venue_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(venue="BINANCE\x1c")

    def test_ring_buffer_information_separator_4_char_event_type_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(etype="QUOTE\x1c")

    def test_ring_buffer_information_separator_3_char_symbol_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(symbol="BTC\x1dUSDT")

    def test_ring_buffer_information_separator_3_char_venue_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(venue="BINANCE\x1d")

    def test_ring_buffer_information_separator_3_char_event_type_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(etype="QUOTE\x1d")

    def test_ring_buffer_information_separator_2_char_symbol_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(symbol="BTC\x1eUSDT")

    def test_ring_buffer_information_separator_2_char_venue_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(venue="BINANCE\x1e")

    def test_ring_buffer_information_separator_2_char_event_type_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(etype="QUOTE\x1e")

    def test_ring_buffer_information_separator_1_char_symbol_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(symbol="BTC\x1fUSDT")

    def test_ring_buffer_information_separator_1_char_venue_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(venue="BINANCE\x1f")

    def test_ring_buffer_information_separator_1_char_event_type_rejected(self):
        with pytest.raises(EventValidationError):
            make_event(etype="QUOTE\x1f")
