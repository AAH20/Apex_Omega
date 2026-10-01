"""Unit tests for feed compression, binary protocol, and low-latency optimization."""
from __future__ import annotations

import struct
import time

import pytest

from src.feed.compression import (
    BinaryProtocol,
    CompressionError,
    LowLatencyBuffer,
    TickCompressor,
    TickDecompressor,
    compress_batch,
    decompress_batch,
)


# ── Helpers ──────────────────────────────────────────────────────────────


def make_tick(
    symbol: str = "BTC-USD",
    price: float = 100.0,
    quantity: float = 1.0,
    side: str = "buy",
    timestamp: int = 1_000_000,
    venue: str = "NYSE",
) -> dict:
    """Factory for a raw tick dict."""
    return {
        "symbol": symbol,
        "price": price,
        "quantity": quantity,
        "side": side,
        "timestamp": timestamp,
        "venue": venue,
    }


# ── Delta Encoding Compression ──────────────────────────────────────────


def test_delta_compression_basic():
    """Delta encoding should compress a sequence of similar ticks."""
    compressor = TickCompressor()
    ticks = [
        make_tick(price=100.0, timestamp=1000),
        make_tick(price=100.5, timestamp=1001),
        make_tick(price=101.0, timestamp=1002),
    ]
    compressed = compressor.compress(ticks)
    assert isinstance(compressed, bytes)
    assert len(compressed) > 0


def test_delta_compression_reduces_size_for_similar_ticks():
    """Delta encoding should produce smaller output for similar ticks vs raw."""
    compressor = TickCompressor()
    ticks = [make_tick(price=100.0 + i * 0.01, timestamp=1000 + i) for i in range(100)]
    compressed = compressor.compress(ticks)
    # Raw would be ~100 * 50 bytes = 5000 bytes; delta should be much smaller
    assert len(compressed) < 2000


def test_delta_compression_empty_raises():
    """Compressing empty tick list should raise CompressionError."""
    compressor = TickCompressor()
    with pytest.raises(CompressionError):
        compressor.compress([])


def test_delta_compression_single_tick():
    """Single tick should compress without error."""
    compressor = TickCompressor()
    compressed = compressor.compress([make_tick()])
    assert isinstance(compressed, bytes)
    assert len(compressed) > 0


def test_delta_roundtrip_preserves_data():
    """Compress then decompress should preserve all tick data."""
    compressor = TickCompressor()
    decompressor = TickDecompressor()
    ticks = [
        make_tick(price=100.0, quantity=1.5, timestamp=1000),
        make_tick(price=100.5, quantity=2.0, timestamp=1001),
        make_tick(price=101.0, quantity=1.0, timestamp=1002),
    ]
    compressed = compressor.compress(ticks)
    restored = decompressor.decompress(compressed)
    assert len(restored) == len(ticks)
    for orig, rest in zip(ticks, restored):
        assert orig["symbol"] == rest["symbol"]
        assert orig["price"] == pytest.approx(rest["price"], rel=1e-4)
        assert orig["quantity"] == pytest.approx(rest["quantity"], rel=1e-4)
        assert orig["side"] == rest["side"]
        assert orig["timestamp"] == rest["timestamp"]
        assert orig["venue"] == rest["venue"]


def test_delta_roundtrip_large_batch():
    """Round-trip should work for a large batch of ticks."""
    compressor = TickCompressor()
    decompressor = TickDecompressor()
    ticks = [
        make_tick(
            price=100.0 + (i % 100) * 0.01,
            quantity=1.0 + (i % 10) * 0.1,
            timestamp=1000 + i,
        )
        for i in range(1000)
    ]
    compressed = compressor.compress(ticks)
    restored = decompressor.decompress(compressed)
    assert len(restored) == 1000
    # Spot-check first, middle, last
    for idx in [0, 500, 999]:
        assert restored[idx]["price"] == pytest.approx(ticks[idx]["price"], rel=1e-4)
        assert restored[idx]["timestamp"] == ticks[idx]["timestamp"]


# ── Quantization ────────────────────────────────────────────────────────


def test_quantization_reduces_precision():
    """Quantization should reduce float precision to save space."""
    compressor = TickCompressor(quantization_bits=16)
    ticks = [make_tick(price=100.123456789, quantity=1.987654321)]
    compressed = compressor.compress(ticks)
    decompressor = TickDecompressor()
    restored = decompressor.decompress(compressed)
    # With 16-bit quantization, we lose some precision
    assert restored[0]["price"] == pytest.approx(100.123456789, rel=1e-3)
    assert restored[0]["quantity"] == pytest.approx(1.987654321, rel=1e-3)


def test_quantization_zero_bits_disables():
    """quantization_bits=0 should disable quantization."""
    compressor = TickCompressor(quantization_bits=0)
    ticks = [make_tick(price=100.123456789)]
    compressed = compressor.compress(ticks)
    decompressor = TickDecompressor()
    restored = decompressor.decompress(compressed)
    assert restored[0]["price"] == pytest.approx(100.123456789, rel=1e-9)


# ── Binary Protocol ─────────────────────────────────────────────────────


def test_binary_protocol_pack_unpack():
    """BinaryProtocol should pack and unpack a tick correctly."""
    proto = BinaryProtocol()
    tick = make_tick(price=100.5, quantity=2.0, timestamp=12345)
    packed = proto.pack(tick)
    assert isinstance(packed, bytes)
    unpacked = proto.unpack(packed)
    assert unpacked["symbol"] == tick["symbol"]
    assert unpacked["price"] == pytest.approx(tick["price"])
    assert unpacked["quantity"] == pytest.approx(tick["quantity"])
    assert unpacked["side"] == tick["side"]
    assert unpacked["timestamp"] == tick["timestamp"]
    assert unpacked["venue"] == tick["venue"]


def test_binary_protocol_pack_batch():
    """BinaryProtocol should pack a batch of ticks."""
    proto = BinaryProtocol()
    ticks = [make_tick(price=100.0 + i, timestamp=1000 + i) for i in range(10)]
    packed = proto.pack_batch(ticks)
    assert isinstance(packed, bytes)
    unpacked = proto.unpack_batch(packed)
    assert len(unpacked) == 10
    for orig, rest in zip(ticks, unpacked):
        assert orig["symbol"] == rest["symbol"]
        assert orig["price"] == pytest.approx(rest["price"])


def test_binary_protocol_header_magic():
    """Binary protocol should include a magic header for validation."""
    proto = BinaryProtocol()
    tick = make_tick()
    packed = proto.pack(tick)
    # First 4 bytes should be the magic number
    magic = struct.unpack_from(">I", packed, 0)[0]
    assert magic == 0x41504558  # "APEX"


def test_binary_protocol_version_byte():
    """Binary protocol should include a version byte."""
    proto = BinaryProtocol()
    tick = make_tick()
    packed = proto.pack(tick)
    version = packed[4]
    assert version == 1


def test_binary_protocol_unpack_invalid_magic_raises():
    """Unpacking data with wrong magic should raise CompressionError."""
    proto = BinaryProtocol()
    with pytest.raises(CompressionError):
        proto.unpack(b"XXXX" + b"\x00" * 100)


def test_binary_protocol_unpack_truncated_raises():
    """Unpacking truncated data should raise CompressionError."""
    proto = BinaryProtocol()
    with pytest.raises(CompressionError):
        proto.unpack(b"\x00\x01")


def test_binary_protocol_roundtrip_preserves_types():
    """Round-trip should preserve int vs float types."""
    proto = BinaryProtocol()
    tick = make_tick(price=100.0, quantity=1.0, timestamp=1234567890)
    packed = proto.pack(tick)
    unpacked = proto.unpack(packed)
    assert isinstance(unpacked["timestamp"], int)
    assert isinstance(unpacked["price"], float)
    assert isinstance(unpacked["quantity"], float)


# ── Batch Compression Helpers ───────────────────────────────────────────


def test_compress_batch_function():
    """compress_batch should compress a list of ticks."""
    ticks = [make_tick(price=100.0 + i * 0.1, timestamp=1000 + i) for i in range(50)]
    compressed = compress_batch(ticks)
    assert isinstance(compressed, bytes)
    assert len(compressed) > 0


def test_decompress_batch_function():
    """decompress_batch should restore a list of ticks."""
    ticks = [make_tick(price=100.0 + i * 0.1, timestamp=1000 + i) for i in range(50)]
    compressed = compress_batch(ticks)
    restored = decompress_batch(compressed)
    assert len(restored) == 50
    for orig, rest in zip(ticks, restored):
        assert orig["price"] == pytest.approx(rest["price"], rel=1e-4)
        assert orig["timestamp"] == rest["timestamp"]


def test_compress_batch_empty_raises():
    """compress_batch with empty list should raise CompressionError."""
    with pytest.raises(CompressionError):
        compress_batch([])


# ── Low-Latency Buffer ──────────────────────────────────────────────────


def test_low_latency_buffer_put_get():
    """LowLatencyBuffer should store and retrieve items."""
    buf = LowLatencyBuffer(capacity=10)
    tick = make_tick()
    buf.put(tick)
    result = buf.get()
    assert result is not None
    assert result["symbol"] == tick["symbol"]


def test_low_latency_buffer_capacity():
    """Buffer should respect its capacity limit."""
    buf = LowLatencyBuffer(capacity=3)
    for i in range(5):
        buf.put(make_tick(price=float(i)))
    # Should only keep the last 3
    assert buf.size() == 3


def test_low_latency_buffer_empty_get_returns_none():
    """Getting from empty buffer should return None."""
    buf = LowLatencyBuffer(capacity=10)
    assert buf.get() is None


def test_low_latency_buffer_is_thread_safe():
    """LowLatencyBuffer should handle concurrent put/get."""
    buf = LowLatencyBuffer(capacity=1000)
    errors: list[Exception] = []

    def producer():
        try:
            for i in range(100):
                buf.put(make_tick(price=float(i)))
        except Exception as e:
            errors.append(e)

    def consumer():
        try:
            for _ in range(100):
                buf.get()
        except Exception as e:
            errors.append(e)

    import threading

    t1 = threading.Thread(target=producer)
    t2 = threading.Thread(target=consumer)
    t1.start()
    t2.start()
    t1.join()
    t2.join()
    assert len(errors) == 0


def test_low_latency_buffer_zero_allocation():
    """Buffer should reuse pre-allocated slots."""
    buf = LowLatencyBuffer(capacity=5)
    # Fill and drain multiple times
    for cycle in range(3):
        for i in range(5):
            buf.put(make_tick(price=float(cycle * 10 + i)))
        for _ in range(5):
            buf.get()
    # Should not have grown beyond capacity
    assert buf.size() == 0


def test_low_latency_buffer_peek():
    """Peek should return item without removing it."""
    buf = LowLatencyBuffer(capacity=10)
    tick = make_tick(price=42.0)
    buf.put(tick)
    peeked = buf.peek()
    assert peeked is not None
    assert peeked["price"] == pytest.approx(42.0)
    # Item should still be there
    assert buf.size() == 1


def test_low_latency_buffer_clear():
    """Clear should empty the buffer."""
    buf = LowLatencyBuffer(capacity=10)
    for i in range(5):
        buf.put(make_tick(price=float(i)))
    buf.clear()
    assert buf.size() == 0
    assert buf.get() is None


# ── Performance / Low-Latency Characteristics ──────────────────────────


def test_compression_speed():
    """Compression should be fast enough for low-latency use."""
    compressor = TickCompressor()
    ticks = [make_tick(price=100.0 + i * 0.01, timestamp=1000 + i) for i in range(1000)]
    start = time.perf_counter()
    for _ in range(10):
        compressed = compressor.compress(ticks)
    elapsed = time.perf_counter() - start
    # Should compress 1000 ticks in under 1 second (very generous)
    assert elapsed < 1.0


def test_binary_protocol_faster_than_json():
    """Binary protocol should be faster than JSON for packing."""
    import json

    proto = BinaryProtocol()
    tick = make_tick()

    # Warm up
    for _ in range(100):
        proto.pack(tick)
        json.dumps(tick)

    iterations = 1000

    start = time.perf_counter()
    for _ in range(iterations):
        proto.pack(tick)
    binary_time = time.perf_counter() - start

    start = time.perf_counter()
    for _ in range(iterations):
        json.dumps(tick)
    json_time = time.perf_counter() - start

    # Binary should be faster (or at least not significantly slower)
    assert binary_time < json_time * 2


# ── Error Handling ──────────────────────────────────────────────────────


def test_decompress_invalid_data_raises():
    """Decompressing garbage data should raise CompressionError."""
    decompressor = TickDecompressor()
    with pytest.raises(CompressionError):
        decompressor.decompress(b"not valid compressed data")


def test_compressor_invalid_tick_raises():
    """Compressing a tick with missing fields should raise CompressionError."""
    compressor = TickCompressor()
    with pytest.raises(CompressionError):
        compressor.compress([{"invalid": "tick"}])


def test_compressor_negative_price_raises():
    """Compressing a tick with negative price should raise CompressionError."""
    compressor = TickCompressor()
    with pytest.raises(CompressionError):
        compressor.compress([make_tick(price=-1.0)])


# ── Integration: Compression + Binary Protocol ─────────────────────────


def test_full_pipeline_compress_then_binary_pack():
    """Ticks can be delta-compressed then binary-packed for transmission."""
    compressor = TickCompressor()
    proto = BinaryProtocol()
    ticks = [make_tick(price=100.0 + i * 0.1, timestamp=1000 + i) for i in range(20)]

    compressed = compressor.compress(ticks)
    # Wrap in binary protocol envelope
    envelope = proto.pack({"payload": compressed, "count": len(ticks)})
    unpacked = proto.unpack(envelope)

    assert unpacked["count"] == 20
    decompressor = TickDecompressor()
    restored = decompressor.decompress(unpacked["payload"])
    assert len(restored) == 20
