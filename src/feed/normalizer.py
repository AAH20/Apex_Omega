"""Feed Normalizer — normalize multi-venue market data to unified format."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional


class NormalizationError(Exception):
    """Raised when a raw tick cannot be normalized."""
    pass


@dataclass(frozen=True)
class VenueFormat:
    """Field mapping configuration for a specific venue."""
    name: str
    symbol_fields: list[str]
    price_fields: list[str]
    quantity_fields: list[str]
    side_fields: list[str]
    timestamp_fields: list[str]
    venue_fields: list[str]


@dataclass(frozen=True)
class NormalizedTick:
    """Unified tick format across all venues."""
    symbol: str
    price: float
    quantity: float
    side: str
    timestamp: int
    venue: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def __repr__(self) -> str:
        return (
            f"NormalizedTick(symbol={self.symbol!r}, price={self.price}, "
            f"quantity={self.quantity}, side={self.side!r}, "
            f"timestamp={self.timestamp}, venue={self.venue!r})"
        )


# ── Default venue formats ──────────────────────────────────────────────

NYSE_FORMAT = VenueFormat(
    name="NYSE",
    symbol_fields=["symbol", "sym", "ticker"],
    price_fields=["price", "px", "last"],
    quantity_fields=["size", "sz", "volume"],
    side_fields=["side", "sd"],
    timestamp_fields=["timestamp", "ts", "epoch_ms", "time"],
    venue_fields=["venue", "ven", "exchange"],
)

NASDAQ_FORMAT = VenueFormat(
    name="NASDAQ",
    symbol_fields=["sym", "symbol", "ticker"],
    price_fields=["px", "price", "last"],
    quantity_fields=["sz", "size", "volume"],
    side_fields=["sd", "side"],
    timestamp_fields=["ts", "timestamp", "epoch_ms", "time"],
    venue_fields=["ven", "venue", "exchange"],
)

BATS_FORMAT = VenueFormat(
    name="BATS",
    symbol_fields=["ticker", "symbol", "sym"],
    price_fields=["last", "price", "px"],
    quantity_fields=["volume", "size", "sz"],
    side_fields=["side", "sd"],
    timestamp_fields=["epoch_ms", "timestamp", "ts", "time"],
    venue_fields=["exchange", "venue", "ven"],
)

COINBASE_FORMAT = VenueFormat(
    name="Coinbase",
    symbol_fields=["product_id", "symbol", "sym"],
    price_fields=["price", "px", "last"],
    quantity_fields=["size", "sz", "volume"],
    side_fields=["side", "sd"],
    timestamp_fields=["time", "timestamp", "ts", "epoch_ms"],
    venue_fields=["exchange", "venue", "ven"],
)

BINANCE_FORMAT = VenueFormat(
    name="Binance",
    symbol_fields=["symbol", "sym", "ticker"],
    price_fields=["p", "price", "px"],
    quantity_fields=["q", "size", "sz"],
    side_fields=["S", "side", "sd"],
    timestamp_fields=["T", "timestamp", "ts", "epoch_ms"],
    venue_fields=["exchange", "venue", "ven"],
)

DEFAULT_VENUE_FORMATS: list[VenueFormat] = [
    NYSE_FORMAT,
    NASDAQ_FORMAT,
    BATS_FORMAT,
    COINBASE_FORMAT,
    BINANCE_FORMAT,
]

# ── Side normalization map ─────────────────────────────────────────────

SIDE_MAP: dict[str, str] = {
    "buy": "buy",
    "b": "buy",
    "sell": "sell",
    "s": "sell",
}


class FeedNormalizer:
    """Normalizes market data from different venues into a unified format."""

    def __init__(self, venue_formats: Optional[list[VenueFormat]] = None):
        self.venue_formats = venue_formats or DEFAULT_VENUE_FORMATS

    def normalize(
        self,
        raw: dict[str, Any],
        venue_format: Optional[VenueFormat] = None,
    ) -> NormalizedTick:
        """Normalize a raw tick dict into a NormalizedTick."""
        if not isinstance(raw, dict):
            raise NormalizationError(f"Expected dict, got {type(raw).__name__}")

        fmt = venue_format or self._detect_venue_format(raw)

        symbol = self._extract_symbol(raw, fmt)
        price = self._extract_price(raw, fmt)
        quantity = self._extract_quantity(raw, fmt)
        side = self._extract_side(raw, fmt)
        timestamp = self._extract_timestamp(raw, fmt)
        venue = self._extract_venue(raw, fmt)
        metadata = self._extract_metadata(raw, fmt)

        return NormalizedTick(
            symbol=symbol,
            price=price,
            quantity=quantity,
            side=side,
            timestamp=timestamp,
            venue=venue,
            metadata=metadata,
        )

    def normalize_batch(
        self,
        raw_ticks: list[dict[str, Any]],
        skip_invalid: bool = False,
    ) -> list[NormalizedTick]:
        """Normalize a batch of raw ticks."""
        results: list[NormalizedTick] = []
        for raw in raw_ticks:
            try:
                tick = self.normalize(raw)
                results.append(tick)
            except NormalizationError:
                if not skip_invalid:
                    raise
        return results

    def filter_by_venue(self, ticks: list[NormalizedTick], venue: str) -> list[NormalizedTick]:
        """Filter ticks by venue."""
        return [t for t in ticks if t.venue == venue]

    def sort_by_timestamp(self, ticks: list[NormalizedTick]) -> list[NormalizedTick]:
        """Sort ticks by timestamp ascending."""
        return sorted(ticks, key=lambda t: t.timestamp)

    def compute_vwap(self, ticks: list[NormalizedTick]) -> float:
        """Compute volume-weighted average price."""
        if not ticks:
            raise NormalizationError("Cannot compute VWAP of empty tick list")
        total_value = sum(t.price * t.quantity for t in ticks)
        total_quantity = sum(t.quantity for t in ticks)
        if total_quantity == 0:
            raise NormalizationError("Cannot compute VWAP with zero total quantity")
        return total_value / total_quantity

    def count_by_venue(self, ticks: list[NormalizedTick]) -> dict[str, int]:
        """Count ticks per venue."""
        counts: dict[str, int] = {}
        for t in ticks:
            counts[t.venue] = counts.get(t.venue, 0) + 1
        return counts

    # ── Private helpers ─────────────────────────────────────────────────

    def _detect_venue_format(self, raw: dict[str, Any]) -> VenueFormat:
        """Detect venue format from field names in the raw tick."""
        for fmt in self.venue_formats:
            if self._matches_format(raw, fmt):
                return fmt
        # Default to NYSE format as fallback
        return NYSE_FORMAT

    def _matches_format(self, raw: dict[str, Any], fmt: VenueFormat) -> bool:
        """Check if raw tick fields match a venue format."""
        has_symbol = any(f in raw for f in fmt.symbol_fields)
        has_price = any(f in raw for f in fmt.price_fields)
        has_side = any(f in raw for f in fmt.side_fields)
        return has_symbol and has_price and has_side

    def _extract_symbol(self, raw: dict[str, Any], fmt: VenueFormat) -> str:
        """Extract and normalize symbol."""
        raw_val = self._get_first(raw, fmt.symbol_fields)
        if raw_val is None:
            raise NormalizationError("Missing symbol field")
        symbol = str(raw_val).strip().upper()
        if not symbol:
            raise NormalizationError("Empty symbol")
        return symbol

    def _extract_price(self, raw: dict[str, Any], fmt: VenueFormat) -> float:
        """Extract and normalize price."""
        raw_val = self._get_first(raw, fmt.price_fields)
        if raw_val is None:
            raise NormalizationError("Missing price field")
        try:
            price = float(raw_val)
        except (ValueError, TypeError):
            raise NormalizationError(f"Invalid price value: {raw_val!r}")
        if price <= 0:
            raise NormalizationError(f"Price must be positive, got {price}")
        return price

    def _extract_quantity(self, raw: dict[str, Any], fmt: VenueFormat) -> float:
        """Extract and normalize quantity."""
        raw_val = self._get_first(raw, fmt.quantity_fields)
        if raw_val is None:
            raise NormalizationError("Missing quantity field")
        try:
            quantity = float(raw_val)
        except (ValueError, TypeError):
            raise NormalizationError(f"Invalid quantity value: {raw_val!r}")
        if quantity <= 0:
            raise NormalizationError(f"Quantity must be positive, got {quantity}")
        return quantity

    def _extract_side(self, raw: dict[str, Any], fmt: VenueFormat) -> str:
        """Extract and normalize side to buy/sell."""
        raw_val = self._get_first(raw, fmt.side_fields)
        if raw_val is None:
            raise NormalizationError("Missing side field")
        side_key = str(raw_val).strip().lower()
        normalized = SIDE_MAP.get(side_key)
        if normalized is None:
            raise NormalizationError(f"Invalid side value: {raw_val!r}")
        return normalized

    def _extract_timestamp(self, raw: dict[str, Any], fmt: VenueFormat) -> int:
        """Extract and normalize timestamp to epoch seconds."""
        raw_val = self._get_first(raw, fmt.timestamp_fields)
        if raw_val is None:
            raise NormalizationError("Missing timestamp field")

        # Handle ISO string
        if isinstance(raw_val, str):
            try:
                dt = datetime.fromisoformat(raw_val.replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return int(dt.timestamp())
            except (ValueError, TypeError):
                raise NormalizationError(f"Invalid timestamp value: {raw_val!r}")

        # Handle numeric epoch
        try:
            ts = int(raw_val)
        except (ValueError, TypeError):
            raise NormalizationError(f"Invalid timestamp value: {raw_val!r}")

        # Heuristic: if timestamp is too large to be seconds, treat as millis
        if ts > 10_000_000_000:  # Beyond year 2286 in seconds
            ts = ts // 1000
        return ts

    def _extract_venue(self, raw: dict[str, Any], fmt: VenueFormat) -> str:
        """Extract venue name."""
        raw_val = self._get_first(raw, fmt.venue_fields)
        if raw_val is None:
            return fmt.name
        return str(raw_val).strip()

    def _extract_metadata(
        self, raw: dict[str, Any], fmt: VenueFormat
    ) -> dict[str, Any]:
        """Extract non-standard fields as metadata."""
        standard_fields = set(
            fmt.symbol_fields
            + fmt.price_fields
            + fmt.quantity_fields
            + fmt.side_fields
            + fmt.timestamp_fields
            + fmt.venue_fields
        )
        return {k: v for k, v in raw.items() if k not in standard_fields}

    @staticmethod
    def _get_first(raw: dict[str, Any], fields: list[str]) -> Any:
        """Get the first non-None value from raw dict matching the field list."""
        for f in fields:
            if f in raw and raw[f] is not None:
                return raw[f]
        return None
