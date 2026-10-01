"""Feed compression, binary protocol, and low-latency optimization.

Provides:
- TickCompressor / TickDecompressor: delta encoding with quantization
- BinaryProtocol: efficient binary serialization with magic header
- LowLatencyBuffer: pre-allocated thread-safe circular buffer
- compress_batch / decompress_batch: convenience functions
"""
from __future__ import annotations

import math
import struct
import threading
from typing import Any, Optional


# ── Constants ────────────────────────────────────────────────────────────

MAGIC = 0x41504558  # "APEX"
VERSION = 1
HEADER_FMT = ">IBI"  # magic(4) + version(1) + count(4) = 9 bytes
HEADER_SIZE = struct.calcsize(HEADER_FMT)

# Flags
FLAG_QUANTIZED = 0x01


class CompressionError(Exception):
    """Raised when compression or decompression fails."""
    pass


# ── Delta Encoding Compression ──────────────────────────────────────────


class TickCompressor:
    """Compresses a sequence of market data ticks using delta encoding.

    The first tick is stored in full; subsequent ticks store only the
    delta from the previous tick. String fields (symbol, venue, side)
    are deduplicated via dictionaries. Optional quantization reduces
    float precision to save additional space.
    """

    def __init__(self, quantization_bits: int = 0):
        """
        Args:
            quantization_bits: Number of bits for float quantization.
                0 disables quantization. Typical values: 16, 24, 32.
        """
        self.quantization_bits = quantization_bits

    def compress(self, ticks: list[dict[str, Any]]) -> bytes:
        """Compress a list of tick dicts into bytes.

        Each tick must have: symbol, price, quantity, side, timestamp, venue.
        """
        if not ticks:
            raise CompressionError("Cannot compress empty tick list")

        # Validate all ticks first
        for i, tick in enumerate(ticks):
            self._validate_tick(tick)

        flags = 0
        if self.quantization_bits > 0:
            flags |= FLAG_QUANTIZED

        # Build header
        header = struct.pack(HEADER_FMT, MAGIC, VERSION, len(ticks))
        header += struct.pack(">B", flags)

        # Build string dictionaries
        symbols: list[str] = []
        venues: list[str] = []
        sides: list[str] = []
        sym_idx_map: dict[str, int] = {}
        ven_idx_map: dict[str, int] = {}
        side_idx_map: dict[str, int] = {}

        for tick in ticks:
            s = tick["symbol"]
            if s not in sym_idx_map:
                sym_idx_map[s] = len(symbols)
                symbols.append(s)
            v = tick["venue"]
            if v not in ven_idx_map:
                ven_idx_map[v] = len(venues)
                venues.append(v)
            sd = tick["side"]
            if sd not in side_idx_map:
                side_idx_map[sd] = len(sides)
                sides.append(sd)

        # Serialize dictionaries
        dict_data = self._serialize_dictionaries(symbols, venues, sides)

        # Serialize first tick in full
        first = ticks[0]
        first_data = self._serialize_full(first, sym_idx_map, ven_idx_map, side_idx_map)

        # Delta-encode subsequent ticks
        parts = [header, dict_data, first_data]
        prev = first
        for i in range(1, len(ticks)):
            delta = self._compute_delta(prev, ticks[i])
            parts.append(self._serialize_delta(delta, sym_idx_map, ven_idx_map, side_idx_map))
            prev = ticks[i]

        return b"".join(parts)

    def _validate_tick(self, tick: dict[str, Any]) -> None:
        """Validate that a tick has all required fields."""
        required = {"symbol", "price", "quantity", "side", "timestamp", "venue"}
        missing = required - set(tick.keys())
        if missing:
            raise CompressionError(f"Tick missing required fields: {missing}")
        if tick["price"] < 0:
            raise CompressionError(f"Price must be non-negative, got {tick['price']}")
        if tick["quantity"] < 0:
            raise CompressionError(f"Quantity must be non-negative, got {tick['quantity']}")

    def _serialize_dictionaries(
        self, symbols: list[str], venues: list[str], sides: list[str]
    ) -> bytes:
        """Serialize string dictionaries."""
        parts = []
        for strings in [symbols, venues, sides]:
            parts.append(struct.pack(">H", len(strings)))
            for s in strings:
                encoded = s.encode("utf-8")
                parts.append(struct.pack(">B", len(encoded)))
                parts.append(encoded)
        return b"".join(parts)

    def _deserialize_dictionaries(self, data: bytes, offset: int) -> tuple[list[str], list[str], list[str], int]:
        """Deserialize string dictionaries."""
        result = []
        for _ in range(3):
            count = struct.unpack_from(">H", data, offset)[0]
            offset += 2
            strings = []
            for _ in range(count):
                length = struct.unpack_from(">B", data, offset)[0]
                offset += 1
                strings.append(data[offset:offset + length].decode("utf-8"))
                offset += length
            result.append(strings)
        return result[0], result[1], result[2], offset

    def _serialize_full(
        self,
        tick: dict[str, Any],
        sym_idx_map: dict[str, int],
        ven_idx_map: dict[str, int],
        side_idx_map: dict[str, int],
    ) -> bytes:
        """Serialize a complete tick with dictionary indices."""
        price = tick["price"]
        quantity = tick["quantity"]
        timestamp = tick["timestamp"]

        if self.quantization_bits > 0:
            price = self._quantize(price, self.quantization_bits)
            quantity = self._quantize(quantity, self.quantization_bits)

        # Format: sym_idx(2) + ven_idx(2) + side_idx(2) + price(8) + quantity(8) + timestamp(8)
        fmt = ">HHHddd"
        return struct.pack(
            fmt,
            sym_idx_map[tick["symbol"]],
            ven_idx_map[tick["venue"]],
            side_idx_map[tick["side"]],
            price, quantity, timestamp,
        )

    def _compute_delta(
        self, prev: dict[str, Any], curr: dict[str, Any]
    ) -> dict[str, Any]:
        """Compute delta between two ticks."""
        return {
            "symbol": curr["symbol"],
            "venue": curr["venue"],
            "side": curr["side"],
            "price_delta": curr["price"] - prev["price"],
            "quantity_delta": curr["quantity"] - prev["quantity"],
            "timestamp_delta": curr["timestamp"] - prev["timestamp"],
        }

    def _serialize_delta(
        self,
        delta: dict[str, Any],
        sym_idx_map: dict[str, int],
        ven_idx_map: dict[str, int],
        side_idx_map: dict[str, int],
    ) -> bytes:
        """Serialize a delta record with dictionary indices."""
        price_delta = delta["price_delta"]
        quantity_delta = delta["quantity_delta"]
        timestamp_delta = delta["timestamp_delta"]

        if self.quantization_bits > 0:
            price_delta = self._quantize(price_delta, self.quantization_bits)
            quantity_delta = self._quantize(quantity_delta, self.quantization_bits)

        # Use smaller types for deltas when possible
        # Format: sym_idx(2) + ven_idx(2) + side_idx(2) + price_delta(4) + quantity_delta(4) + ts_delta(4)
        fmt = ">HHHfff"
        return struct.pack(
            fmt,
            sym_idx_map[delta["symbol"]],
            ven_idx_map[delta["venue"]],
            side_idx_map[delta["side"]],
            price_delta, quantity_delta, float(timestamp_delta),
        )

    def _quantize(self, value: float, bits: int) -> float:
        """Quantize a float to the given number of significant bits."""
        if bits <= 0:
            return value
        if value == 0.0:
            return 0.0
        # Find the order of magnitude
        order = math.floor(math.log2(abs(value)))
        # Quantize to `bits` significant bits
        quantum = 2 ** (order - bits + 1)
        return round(value / quantum) * quantum


class TickDecompressor:
    """Decompresses delta-encoded tick data back into tick dicts."""

    def decompress(self, data: bytes) -> list[dict[str, Any]]:
        """Decompress bytes back into a list of tick dicts."""
        if len(data) < HEADER_SIZE + 1:
            raise CompressionError("Data too short to contain header")

        magic, version, count = struct.unpack_from(HEADER_FMT, data, 0)
        if magic != MAGIC:
            raise CompressionError(f"Invalid magic: 0x{magic:08X}")
        if version != VERSION:
            raise CompressionError(f"Unsupported version: {version}")

        flags = struct.unpack_from(">B", data, HEADER_SIZE)[0]
        quantized = bool(flags & FLAG_QUANTIZED)

        offset = HEADER_SIZE + 1

        # Deserialize dictionaries
        symbols, venues, sides, offset = self._deserialize_dictionaries(data, offset)

        ticks: list[dict[str, Any]] = []

        # Deserialize first tick
        tick, offset = self._deserialize_full(data, offset, symbols, venues, sides)
        ticks.append(tick)

        # Delta-decode subsequent ticks
        prev = tick
        for _ in range(1, count):
            delta, offset = self._deserialize_delta(data, offset, symbols, venues, sides)
            curr = self._apply_delta(prev, delta)
            ticks.append(curr)
            prev = curr

        return ticks

    def _deserialize_dictionaries(self, data: bytes, offset: int) -> tuple[list[str], list[str], list[str], int]:
        """Deserialize string dictionaries."""
        result = []
        for _ in range(3):
            count = struct.unpack_from(">H", data, offset)[0]
            offset += 2
            strings = []
            for _ in range(count):
                length = struct.unpack_from(">B", data, offset)[0]
                offset += 1
                strings.append(data[offset:offset + length].decode("utf-8"))
                offset += length
            result.append(strings)
        return result[0], result[1], result[2], offset

    def _deserialize_full(
        self, data: bytes, offset: int, symbols: list[str], venues: list[str], sides: list[str]
    ) -> tuple[dict[str, Any], int]:
        """Deserialize a complete tick from data."""
        sym_idx, ven_idx, side_idx = struct.unpack_from(">HHH", data, offset)
        offset += 6

        price, quantity, timestamp = struct.unpack_from(">ddd", data, offset)
        offset += 24

        return {
            "symbol": symbols[sym_idx],
            "price": price,
            "quantity": quantity,
            "side": sides[side_idx],
            "timestamp": int(timestamp),
            "venue": venues[ven_idx],
        }, offset

    def _deserialize_delta(
        self, data: bytes, offset: int, symbols: list[str], venues: list[str], sides: list[str]
    ) -> tuple[dict[str, Any], int]:
        """Deserialize a delta record from data."""
        sym_idx, ven_idx, side_idx = struct.unpack_from(">HHH", data, offset)
        offset += 6

        price_delta, quantity_delta, timestamp_delta = struct.unpack_from(">fff", data, offset)
        offset += 12

        return {
            "symbol": symbols[sym_idx],
            "venue": venues[ven_idx],
            "side": sides[side_idx],
            "price_delta": price_delta,
            "quantity_delta": quantity_delta,
            "timestamp_delta": int(timestamp_delta),
        }, offset

    def _apply_delta(self, prev: dict[str, Any], delta: dict[str, Any]) -> dict[str, Any]:
        """Apply a delta to a previous tick to reconstruct the current tick."""
        return {
            "symbol": delta["symbol"],
            "price": prev["price"] + delta["price_delta"],
            "quantity": prev["quantity"] + delta["quantity_delta"],
            "side": delta["side"],
            "timestamp": prev["timestamp"] + delta["timestamp_delta"],
            "venue": delta["venue"],
        }


# ── Binary Protocol ─────────────────────────────────────────────────────


class BinaryProtocol:
    """Efficient binary serialization protocol for market data.

    Format:
        magic(4) + version(1) + payload_len(4) + payload(variable)
    """

    def pack(self, data: dict[str, Any]) -> bytes:
        """Pack a dict into binary format."""
        payload = self._encode_dict(data)
        header = struct.pack(">IBI", MAGIC, VERSION, len(payload))
        return header + payload

    def unpack(self, data: bytes) -> dict[str, Any]:
        """Unpack binary data back into a dict."""
        if len(data) < 9:
            raise CompressionError("Data too short for binary protocol header")

        magic, version, payload_len = struct.unpack_from(">IBI", data, 0)
        if magic != MAGIC:
            raise CompressionError(f"Invalid magic: 0x{magic:08X}")
        if version != VERSION:
            raise CompressionError(f"Unsupported version: {version}")

        payload = data[9:9 + payload_len]
        if len(payload) != payload_len:
            raise CompressionError("Payload length mismatch")

        return self._decode_dict(payload)

    def pack_batch(self, ticks: list[dict[str, Any]]) -> bytes:
        """Pack a batch of ticks into binary format."""
        parts = [struct.pack(">I", len(ticks))]
        for tick in ticks:
            encoded = self._encode_dict(tick)
            parts.append(struct.pack(">I", len(encoded)))
            parts.append(encoded)
        payload = b"".join(parts)
        header = struct.pack(">IBI", MAGIC, VERSION, len(payload))
        return header + payload

    def unpack_batch(self, data: bytes) -> list[dict[str, Any]]:
        """Unpack a batch of ticks from binary format."""
        if len(data) < 9:
            raise CompressionError("Data too short for binary protocol header")

        magic, version, payload_len = struct.unpack_from(">IBI", data, 0)
        if magic != MAGIC:
            raise CompressionError(f"Invalid magic: 0x{magic:08X}")

        payload = data[9:9 + payload_len]
        offset = 0
        count = struct.unpack_from(">I", payload, offset)[0]
        offset += 4

        ticks = []
        for _ in range(count):
            tick_len = struct.unpack_from(">I", payload, offset)[0]
            offset += 4
            tick_data = payload[offset:offset + tick_len]
            offset += tick_len
            ticks.append(self._decode_dict(tick_data))

        return ticks

    def _encode_dict(self, data: dict[str, Any]) -> bytes:
        """Encode a dict into bytes using a simple type-tagged format."""
        parts = []
        for key, value in data.items():
            key_bytes = key.encode("utf-8")
            parts.append(struct.pack(">B", len(key_bytes)))
            parts.append(key_bytes)

            if isinstance(value, str):
                val_bytes = value.encode("utf-8")
                parts.append(struct.pack(">BI", 0, len(val_bytes)))
                parts.append(val_bytes)
            elif isinstance(value, int):
                parts.append(struct.pack(">Bq", 1, value))
            elif isinstance(value, float):
                parts.append(struct.pack(">Bd", 2, value))
            elif isinstance(value, bytes):
                parts.append(struct.pack(">BI", 3, len(value)))
                parts.append(value)
            elif isinstance(value, dict):
                nested = self._encode_dict(value)
                parts.append(struct.pack(">BI", 4, len(nested)))
                parts.append(nested)
            else:
                raise CompressionError(f"Unsupported type for binary protocol: {type(value)}")

        return b"".join(parts)

    def _decode_dict(self, data: bytes) -> dict[str, Any]:
        """Decode bytes back into a dict."""
        result = {}
        offset = 0
        while offset < len(data):
            key_len = struct.unpack_from(">B", data, offset)[0]
            offset += 1
            key = data[offset:offset + key_len].decode("utf-8")
            offset += key_len

            type_tag = struct.unpack_from(">B", data, offset)[0]
            offset += 1

            if type_tag == 0:  # string
                val_len = struct.unpack_from(">I", data, offset)[0]
                offset += 4
                value = data[offset:offset + val_len].decode("utf-8")
                offset += val_len
            elif type_tag == 1:  # int
                value = struct.unpack_from(">q", data, offset)[0]
                offset += 8
            elif type_tag == 2:  # float
                value = struct.unpack_from(">d", data, offset)[0]
                offset += 8
            elif type_tag == 3:  # bytes
                val_len = struct.unpack_from(">I", data, offset)[0]
                offset += 4
                value = data[offset:offset + val_len]
                offset += val_len
            elif type_tag == 4:  # dict
                val_len = struct.unpack_from(">I", data, offset)[0]
                offset += 4
                value = self._decode_dict(data[offset:offset + val_len])
                offset += val_len
            else:
                raise CompressionError(f"Unknown type tag: {type_tag}")

            result[key] = value

        return result


# ── Batch Compression Helpers ───────────────────────────────────────────


def compress_batch(ticks: list[dict[str, Any]], quantization_bits: int = 0) -> bytes:
    """Compress a batch of ticks using delta encoding.

    Args:
        ticks: List of tick dicts with symbol, price, quantity, side, timestamp, venue.
        quantization_bits: Optional quantization precision (0 to disable).

    Returns:
        Compressed bytes.
    """
    compressor = TickCompressor(quantization_bits=quantization_bits)
    return compressor.compress(ticks)


def decompress_batch(data: bytes) -> list[dict[str, Any]]:
    """Decompress a batch of ticks.

    Args:
        data: Compressed bytes from compress_batch.

    Returns:
        List of tick dicts.
    """
    decompressor = TickDecompressor()
    return decompressor.decompress(data)


# ── Low-Latency Buffer ──────────────────────────────────────────────────


class LowLatencyBuffer:
    """Pre-allocated thread-safe circular buffer for low-latency market data.

    Uses a fixed-size pre-allocated list to avoid GC pressure during
    high-frequency operations. Thread-safe for concurrent put/get.
    """

    def __init__(self, capacity: int = 1024):
        """
        Args:
            capacity: Maximum number of items the buffer can hold.
        """
        if capacity <= 0:
            raise ValueError("Capacity must be positive")
        self._capacity = capacity
        self._buffer: list[Optional[dict[str, Any]]] = [None] * capacity
        self._write_idx = 0
        self._read_idx = 0
        self._count = 0
        self._lock = threading.Lock()

    def put(self, item: dict[str, Any]) -> None:
        """Add an item to the buffer. Overwrites oldest if full."""
        with self._lock:
            self._buffer[self._write_idx] = item
            self._write_idx = (self._write_idx + 1) % self._capacity
            if self._count < self._capacity:
                self._count += 1
            else:
                # Buffer full, advance read index (overwrite oldest)
                self._read_idx = (self._read_idx + 1) % self._capacity

    def get(self) -> Optional[dict[str, Any]]:
        """Remove and return the oldest item, or None if empty."""
        with self._lock:
            if self._count == 0:
                return None
            item = self._buffer[self._read_idx]
            self._buffer[self._read_idx] = None
            self._read_idx = (self._read_idx + 1) % self._capacity
            self._count -= 1
            return item

    def peek(self) -> Optional[dict[str, Any]]:
        """Return the oldest item without removing it, or None if empty."""
        with self._lock:
            if self._count == 0:
                return None
            return self._buffer[self._read_idx]

    def size(self) -> int:
        """Return the current number of items in the buffer."""
        with self._lock:
            return self._count

    def clear(self) -> None:
        """Remove all items from the buffer."""
        with self._lock:
            self._buffer = [None] * self._capacity
            self._write_idx = 0
            self._read_idx = 0
            self._count = 0
