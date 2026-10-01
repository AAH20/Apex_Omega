"""Unit tests for Feed Normalizer — TDD: write tests first, watch them fail."""
import pytest
from datetime import datetime, timezone

from src.feed.normalizer import (
    FeedNormalizer,
    NormalizedTick,
    VenueFormat,
    NormalizationError,
)


# ---------------------------------------------------------------------------
# Basic normalization tests
# ---------------------------------------------------------------------------


class TestBasicNormalization:
    """Test basic normalization from a single venue."""

    def test_normalize_nyse_tick(self):
        raw = {
            "symbol": "AAPL",
            "price": "150.25",
            "size": "100",
            "side": "buy",
            "timestamp": 1700000000,
            "venue": "NYSE",
        }
        norm = FeedNormalizer()
        tick = norm.normalize(raw)
        assert tick.symbol == "AAPL"
        assert tick.price == 150.25
        assert tick.quantity == 100
        assert tick.side == "buy"
        assert tick.timestamp == 1700000000
        assert tick.venue == "NYSE"

    def test_normalize_nasdaq_tick(self):
        raw = {
            "sym": "MSFT",
            "px": 300.50,
            "sz": 200,
            "sd": "sell",
            "ts": 1700000001,
            "ven": "NASDAQ",
        }
        norm = FeedNormalizer()
        tick = norm.normalize(raw)
        assert tick.symbol == "MSFT"
        assert tick.price == 300.50
        assert tick.quantity == 200
        assert tick.side == "sell"
        assert tick.venue == "NASDAQ"

    def test_normalize_bats_tick(self):
        raw = {
            "ticker": "GOOG",
            "last": "2800.00",
            "volume": "50",
            "side": "B",
            "epoch_ms": 1700000002000,
            "exchange": "BATS",
        }
        norm = FeedNormalizer()
        tick = norm.normalize(raw)
        assert tick.symbol == "GOOG"
        assert tick.price == 2800.00
        assert tick.quantity == 50
        assert tick.side == "buy"
        assert tick.timestamp == 1700000002

    def test_normalize_coinbase_tick(self):
        raw = {
            "product_id": "BTC-USD",
            "price": "42000.00",
            "size": "0.5",
            "side": "buy",
            "time": "2023-11-14T22:13:20Z",
            "exchange": "Coinbase",
        }
        norm = FeedNormalizer()
        tick = norm.normalize(raw)
        assert tick.symbol == "BTC-USD"
        assert tick.price == 42000.00
        assert tick.quantity == 0.5
        assert tick.side == "buy"
        assert tick.venue == "Coinbase"

    def test_normalize_binance_tick(self):
        raw = {
            "symbol": "ETHUSDT",
            "p": "2200.50",
            "q": "1.5",
            "S": "SELL",
            "T": 1700000003000,
            "exchange": "Binance",
        }
        norm = FeedNormalizer()
        tick = norm.normalize(raw)
        assert tick.symbol == "ETHUSDT"
        assert tick.price == 2200.50
        assert tick.quantity == 1.5
        assert tick.side == "sell"
        assert tick.venue == "Binance"


# ---------------------------------------------------------------------------
# Timestamp normalization tests
# ---------------------------------------------------------------------------


class TestTimestampNormalization:
    """Test timestamp normalization from various formats."""

    def test_epoch_seconds(self):
        raw = {"symbol": "AAPL", "price": "100", "size": "10", "side": "buy",
               "timestamp": 1700000000, "venue": "NYSE"}
        norm = FeedNormalizer()
        tick = norm.normalize(raw)
        assert tick.timestamp == 1700000000

    def test_epoch_millis_converted_to_seconds(self):
        raw = {"symbol": "AAPL", "price": "100", "size": "10", "side": "buy",
               "epoch_ms": 1700000000000, "venue": "NYSE"}
        norm = FeedNormalizer()
        tick = norm.normalize(raw)
        assert tick.timestamp == 1700000000

    def test_iso_string_converted_to_epoch(self):
        raw = {"symbol": "AAPL", "price": "100", "size": "10", "side": "buy",
               "time": "2023-11-14T22:13:20Z", "venue": "NYSE"}
        norm = FeedNormalizer()
        tick = norm.normalize(raw)
        expected = int(datetime(2023, 11, 14, 22, 13, 20, tzinfo=timezone.utc).timestamp())
        assert tick.timestamp == expected

    def test_missing_timestamp_raises(self):
        raw = {"symbol": "AAPL", "price": "100", "size": "10", "side": "buy",
               "venue": "NYSE"}
        norm = FeedNormalizer()
        with pytest.raises(NormalizationError):
            norm.normalize(raw)


# ---------------------------------------------------------------------------
# Symbol normalization tests
# ---------------------------------------------------------------------------


class TestSymbolNormalization:
    """Test symbol normalization across venues."""

    def test_symbol_uppercased(self):
        raw = {"symbol": "aapl", "price": "100", "size": "10", "side": "buy",
               "timestamp": 1700000000, "venue": "NYSE"}
        norm = FeedNormalizer()
        tick = norm.normalize(raw)
        assert tick.symbol == "AAPL"

    def test_symbol_stripped(self):
        raw = {"symbol": "  MSFT  ", "price": "100", "size": "10", "side": "buy",
               "timestamp": 1700000000, "venue": "NYSE"}
        norm = FeedNormalizer()
        tick = norm.normalize(raw)
        assert tick.symbol == "MSFT"

    def test_missing_symbol_raises(self):
        raw = {"price": "100", "size": "10", "side": "buy",
               "timestamp": 1700000000, "venue": "NYSE"}
        norm = FeedNormalizer()
        with pytest.raises(NormalizationError):
            norm.normalize(raw)


# ---------------------------------------------------------------------------
# Side normalization tests
# ---------------------------------------------------------------------------


class TestSideNormalization:
    """Test side normalization to buy/sell."""

    def test_buy_side(self):
        raw = {"symbol": "AAPL", "price": "100", "size": "10", "side": "buy",
               "timestamp": 1700000000, "venue": "NYSE"}
        norm = FeedNormalizer()
        tick = norm.normalize(raw)
        assert tick.side == "buy"

    def test_sell_side(self):
        raw = {"symbol": "AAPL", "price": "100", "size": "10", "side": "sell",
               "timestamp": 1700000000, "venue": "NYSE"}
        norm = FeedNormalizer()
        tick = norm.normalize(raw)
        assert tick.side == "sell"

    def test_b_normalized_to_buy(self):
        raw = {"symbol": "AAPL", "price": "100", "size": "10", "side": "B",
               "timestamp": 1700000000, "venue": "NYSE"}
        norm = FeedNormalizer()
        tick = norm.normalize(raw)
        assert tick.side == "buy"

    def test_s_normalized_to_sell(self):
        raw = {"symbol": "AAPL", "price": "100", "size": "10", "side": "S",
               "timestamp": 1700000000, "venue": "NYSE"}
        norm = FeedNormalizer()
        tick = norm.normalize(raw)
        assert tick.side == "sell"

    def test_BUY_uppercase_normalized(self):
        raw = {"symbol": "AAPL", "price": "100", "size": "10", "side": "BUY",
               "timestamp": 1700000000, "venue": "NYSE"}
        norm = FeedNormalizer()
        tick = norm.normalize(raw)
        assert tick.side == "buy"

    def test_invalid_side_raises(self):
        raw = {"symbol": "AAPL", "price": "100", "size": "10", "side": "hold",
               "timestamp": 1700000000, "venue": "NYSE"}
        norm = FeedNormalizer()
        with pytest.raises(NormalizationError):
            norm.normalize(raw)


# ---------------------------------------------------------------------------
# Price and quantity coercion tests
# ---------------------------------------------------------------------------


class TestPriceQuantityCoercion:
    """Test price and quantity type coercion."""

    def test_string_price_coerced_to_float(self):
        raw = {"symbol": "AAPL", "price": "150.25", "size": "100", "side": "buy",
               "timestamp": 1700000000, "venue": "NYSE"}
        norm = FeedNormalizer()
        tick = norm.normalize(raw)
        assert isinstance(tick.price, float)
        assert tick.price == 150.25

    def test_string_quantity_coerced_to_float(self):
        raw = {"symbol": "AAPL", "price": "150.25", "size": "100.5", "side": "buy",
               "timestamp": 1700000000, "venue": "NYSE"}
        norm = FeedNormalizer()
        tick = norm.normalize(raw)
        assert isinstance(tick.quantity, float)
        assert tick.quantity == 100.5

    def test_int_price_coerced_to_float(self):
        raw = {"symbol": "AAPL", "price": 150, "size": 100, "side": "buy",
               "timestamp": 1700000000, "venue": "NYSE"}
        norm = FeedNormalizer()
        tick = norm.normalize(raw)
        assert isinstance(tick.price, float)
        assert tick.price == 150.0

    def test_negative_price_raises(self):
        raw = {"symbol": "AAPL", "price": "-100", "size": "10", "side": "buy",
               "timestamp": 1700000000, "venue": "NYSE"}
        norm = FeedNormalizer()
        with pytest.raises(NormalizationError):
            norm.normalize(raw)

    def test_zero_quantity_raises(self):
        raw = {"symbol": "AAPL", "price": "100", "size": "0", "side": "buy",
               "timestamp": 1700000000, "venue": "NYSE"}
        norm = FeedNormalizer()
        with pytest.raises(NormalizationError):
            norm.normalize(raw)

    def test_missing_price_raises(self):
        raw = {"symbol": "AAPL", "size": "10", "side": "buy",
               "timestamp": 1700000000, "venue": "NYSE"}
        norm = FeedNormalizer()
        with pytest.raises(NormalizationError):
            norm.normalize(raw)


# ---------------------------------------------------------------------------
# Batch normalization tests
# ---------------------------------------------------------------------------


class TestBatchNormalization:
    """Test batch normalization of multiple ticks."""

    def test_normalize_batch(self):
        raw_ticks = [
            {"symbol": "AAPL", "price": "100", "size": "10", "side": "buy",
             "timestamp": 1700000000, "venue": "NYSE"},
            {"symbol": "MSFT", "price": "200", "size": "20", "side": "sell",
             "timestamp": 1700000001, "venue": "NASDAQ"},
        ]
        norm = FeedNormalizer()
        ticks = norm.normalize_batch(raw_ticks)
        assert len(ticks) == 2
        assert ticks[0].symbol == "AAPL"
        assert ticks[1].symbol == "MSFT"

    def test_normalize_empty_batch(self):
        norm = FeedNormalizer()
        ticks = norm.normalize_batch([])
        assert ticks == []

    def test_normalize_batch_skips_invalid(self):
        raw_ticks = [
            {"symbol": "AAPL", "price": "100", "size": "10", "side": "buy",
             "timestamp": 1700000000, "venue": "NYSE"},
            {"symbol": "", "price": "200", "size": "20", "side": "sell",
             "timestamp": 1700000001, "venue": "NASDAQ"},  # invalid
            {"symbol": "GOOG", "price": "300", "size": "30", "side": "buy",
             "timestamp": 1700000002, "venue": "BATS"},
        ]
        norm = FeedNormalizer()
        ticks = norm.normalize_batch(raw_ticks, skip_invalid=True)
        assert len(ticks) == 2
        assert ticks[0].symbol == "AAPL"
        assert ticks[1].symbol == "GOOG"

    def test_normalize_batch_raises_on_invalid_by_default(self):
        raw_ticks = [
            {"symbol": "AAPL", "price": "100", "size": "10", "side": "buy",
             "timestamp": 1700000000, "venue": "NYSE"},
            {"symbol": "", "price": "200", "size": "20", "side": "sell",
             "timestamp": 1700000001, "venue": "NASDAQ"},  # invalid
        ]
        norm = FeedNormalizer()
        with pytest.raises(NormalizationError):
            norm.normalize_batch(raw_ticks)


# ---------------------------------------------------------------------------
# Venue detection tests
# ---------------------------------------------------------------------------


class TestVenueDetection:
    """Test automatic venue detection from field names."""

    def test_detect_nyse_by_field_names(self):
        raw = {"symbol": "AAPL", "price": "100", "size": "10", "side": "buy",
               "timestamp": 1700000000, "venue": "NYSE"}
        norm = FeedNormalizer()
        tick = norm.normalize(raw)
        assert tick.venue == "NYSE"

    def test_detect_nasdaq_by_field_names(self):
        raw = {"sym": "MSFT", "px": "200", "sz": "20", "sd": "sell",
               "ts": 1700000001, "ven": "NASDAQ"}
        norm = FeedNormalizer()
        tick = norm.normalize(raw)
        assert tick.venue == "NASDAQ"

    def test_detect_binance_by_field_names(self):
        raw = {"symbol": "ETHUSDT", "p": "2200", "q": "1.5", "S": "SELL",
               "T": 1700000003000, "exchange": "Binance"}
        norm = FeedNormalizer()
        tick = norm.normalize(raw)
        assert tick.venue == "Binance"

    def test_unknown_venue_defaults_to_unknown(self):
        raw = {"symbol": "AAPL", "price": "100", "size": "10", "side": "buy",
               "timestamp": 1700000000, "venue": "UNKNOWN"}
        norm = FeedNormalizer()
        tick = norm.normalize(raw)
        assert tick.venue == "UNKNOWN"


# ---------------------------------------------------------------------------
# Custom field preservation tests
# ---------------------------------------------------------------------------


class TestCustomFieldPreservation:
    """Test that custom/extra fields are preserved."""

    def test_custom_fields_preserved(self):
        raw = {"symbol": "AAPL", "price": "100", "size": "10", "side": "buy",
               "timestamp": 1700000000, "venue": "NYSE",
               "order_id": "ORD123", "trader": "TRADER1"}
        norm = FeedNormalizer()
        tick = norm.normalize(raw)
        assert tick.metadata["order_id"] == "ORD123"
        assert tick.metadata["trader"] == "TRADER1"

    def test_no_custom_fields_gives_empty_metadata(self):
        raw = {"symbol": "AAPL", "price": "100", "size": "10", "side": "buy",
               "timestamp": 1700000000, "venue": "NYSE"}
        norm = FeedNormalizer()
        tick = norm.normalize(raw)
        assert tick.metadata == {}


# ---------------------------------------------------------------------------
# Filtering and sorting tests
# ---------------------------------------------------------------------------


class TestFilteringAndSorting:
    """Test filtering and sorting of normalized ticks."""

    def test_filter_by_venue(self):
        raw_ticks = [
            {"symbol": "AAPL", "price": "100", "size": "10", "side": "buy",
             "timestamp": 1700000000, "venue": "NYSE"},
            {"symbol": "MSFT", "price": "200", "size": "20", "side": "sell",
             "timestamp": 1700000001, "venue": "NASDAQ"},
            {"symbol": "GOOG", "price": "300", "size": "30", "side": "buy",
             "timestamp": 1700000002, "venue": "NYSE"},
        ]
        norm = FeedNormalizer()
        ticks = norm.normalize_batch(raw_ticks)
        nyse_ticks = norm.filter_by_venue(ticks, "NYSE")
        assert len(nyse_ticks) == 2
        assert all(t.venue == "NYSE" for t in nyse_ticks)

    def test_sort_by_timestamp(self):
        raw_ticks = [
            {"symbol": "AAPL", "price": "100", "size": "10", "side": "buy",
             "timestamp": 1700000002, "venue": "NYSE"},
            {"symbol": "MSFT", "price": "200", "size": "20", "side": "sell",
             "timestamp": 1700000000, "venue": "NASDAQ"},
            {"symbol": "GOOG", "price": "300", "size": "30", "side": "buy",
             "timestamp": 1700000001, "venue": "BATS"},
        ]
        norm = FeedNormalizer()
        ticks = norm.normalize_batch(raw_ticks)
        sorted_ticks = norm.sort_by_timestamp(ticks)
        assert sorted_ticks[0].timestamp == 1700000000
        assert sorted_ticks[1].timestamp == 1700000001
        assert sorted_ticks[2].timestamp == 1700000002


# ---------------------------------------------------------------------------
# Statistics tests
# ---------------------------------------------------------------------------


class TestStatistics:
    """Test statistics aggregation."""

    def test_compute_vwap(self):
        raw_ticks = [
            {"symbol": "AAPL", "price": "100", "size": "10", "side": "buy",
             "timestamp": 1700000000, "venue": "NYSE"},
            {"symbol": "AAPL", "price": "200", "size": "20", "side": "sell",
             "timestamp": 1700000001, "venue": "NYSE"},
        ]
        norm = FeedNormalizer()
        ticks = norm.normalize_batch(raw_ticks)
        vwap = norm.compute_vwap(ticks)
        expected = (100.0 * 10 + 200.0 * 20) / (10 + 20)
        assert vwap == pytest.approx(expected)

    def test_compute_vwap_empty_raises(self):
        norm = FeedNormalizer()
        with pytest.raises(NormalizationError):
            norm.compute_vwap([])

    def test_count_by_venue(self):
        raw_ticks = [
            {"symbol": "AAPL", "price": "100", "size": "10", "side": "buy",
             "timestamp": 1700000000, "venue": "NYSE"},
            {"symbol": "MSFT", "price": "200", "size": "20", "side": "sell",
             "timestamp": 1700000001, "venue": "NASDAQ"},
            {"symbol": "GOOG", "price": "300", "size": "30", "side": "buy",
             "timestamp": 1700000002, "venue": "NYSE"},
        ]
        norm = FeedNormalizer()
        ticks = norm.normalize_batch(raw_ticks)
        counts = norm.count_by_venue(ticks)
        assert counts == {"NYSE": 2, "NASDAQ": 1}


# ---------------------------------------------------------------------------
# Venue format configuration tests
# ---------------------------------------------------------------------------


class TestVenueFormatConfig:
    """Test custom venue format configuration."""

    def test_register_custom_venue_format(self):
        custom_format = VenueFormat(
            name="CUSTOM",
            symbol_fields=["ticker"],
            price_fields=["last_price"],
            quantity_fields=["qty"],
            side_fields=["side"],
            timestamp_fields=["ts"],
            venue_fields=["exchange"],
        )
        norm = FeedNormalizer()
        raw = {"ticker": "XYZ", "last_price": "50.25", "qty": "100",
               "side": "buy", "ts": 1700000000, "exchange": "CUSTOM"}
        tick = norm.normalize(raw, venue_format=custom_format)
        assert tick.symbol == "XYZ"
        assert tick.price == 50.25
        assert tick.quantity == 100
        assert tick.side == "buy"
        assert tick.venue == "CUSTOM"

    def test_normalize_with_explicit_venue_format(self):
        nasdaq_format = VenueFormat(
            name="NASDAQ",
            symbol_fields=["sym"],
            price_fields=["px"],
            quantity_fields=["sz"],
            side_fields=["sd"],
            timestamp_fields=["ts"],
            venue_fields=["ven"],
        )
        norm = FeedNormalizer()
        raw = {"sym": "MSFT", "px": "300.50", "sz": "200", "sd": "sell",
               "ts": 1700000001, "ven": "NASDAQ"}
        tick = norm.normalize(raw, venue_format=nasdaq_format)
        assert tick.symbol == "MSFT"
        assert tick.price == 300.50
        assert tick.quantity == 200
        assert tick.side == "sell"
        assert tick.venue == "NASDAQ"


# ---------------------------------------------------------------------------
# Edge case tests
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_very_large_price(self):
        raw = {"symbol": "AAPL", "price": "999999999.99", "size": "10", "side": "buy",
               "timestamp": 1700000000, "venue": "NYSE"}
        norm = FeedNormalizer()
        tick = norm.normalize(raw)
        assert tick.price == 999999999.99

    def test_very_small_quantity(self):
        raw = {"symbol": "AAPL", "price": "100", "size": "0.0001", "side": "buy",
               "timestamp": 1700000000, "venue": "NYSE"}
        norm = FeedNormalizer()
        tick = norm.normalize(raw)
        assert tick.quantity == 0.0001

    def test_none_values_raise(self):
        raw = {"symbol": None, "price": "100", "size": "10", "side": "buy",
               "timestamp": 1700000000, "venue": "NYSE"}
        norm = FeedNormalizer()
        with pytest.raises(NormalizationError):
            norm.normalize(raw)

    def test_non_dict_input_raises(self):
        norm = FeedNormalizer()
        with pytest.raises(NormalizationError):
            norm.normalize("not a dict")

    def test_normalized_tick_repr(self):
        raw = {"symbol": "AAPL", "price": "100", "size": "10", "side": "buy",
               "timestamp": 1700000000, "venue": "NYSE"}
        norm = FeedNormalizer()
        tick = norm.normalize(raw)
        repr_str = repr(tick)
        assert "AAPL" in repr_str
        assert "NYSE" in repr_str

    def test_normalized_tick_equality(self):
        raw = {"symbol": "AAPL", "price": "100", "size": "10", "side": "buy",
               "timestamp": 1700000000, "venue": "NYSE"}
        norm = FeedNormalizer()
        tick1 = norm.normalize(raw)
        tick2 = norm.normalize(raw)
        assert tick1 == tick2

    def test_normalized_tick_inequality_different_symbol(self):
        raw1 = {"symbol": "AAPL", "price": "100", "size": "10", "side": "buy",
                "timestamp": 1700000000, "venue": "NYSE"}
        raw2 = {"symbol": "MSFT", "price": "100", "size": "10", "side": "buy",
                "timestamp": 1700000000, "venue": "NYSE"}
        norm = FeedNormalizer()
        tick1 = norm.normalize(raw1)
        tick2 = norm.normalize(raw2)
        assert tick1 != tick2