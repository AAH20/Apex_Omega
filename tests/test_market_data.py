"""Unit tests for Venue Market Data Aggregator."""
from __future__ import annotations

import threading
import time

import pytest

from src.venues.market_data import (
    AggregatedQuote,
    AggregationStrategy,
    ArbitrageOpportunity,
    DataQuality,
    VenueMarketDataAggregator,
    VenueQuote,
)


# ── Helpers ──────────────────────────────────────────────────────────────


def make_quote(
    venue: str = "venue_a",
    symbol: str = "BTC-USD",
    bid: float = 100.0,
    ask: float = 101.0,
    bid_size: float = 1.0,
    ask_size: float = 1.0,
    timestamp: float | None = None,
    quality: DataQuality = DataQuality.REALTIME,
) -> VenueQuote:
    """Factory for VenueQuote with sensible defaults."""
    return VenueQuote(
        venue=venue,
        symbol=symbol,
        bid=bid,
        ask=ask,
        bid_size=bid_size,
        ask_size=ask_size,
        timestamp=timestamp if timestamp is not None else time.time(),
        quality=quality,
    )


# ── VenueQuote ───────────────────────────────────────────────────────────


def test_venue_quote_creation():
    q = make_quote()
    assert q.venue == "venue_a"
    assert q.symbol == "BTC-USD"
    assert q.bid == 100.0
    assert q.ask == 101.0
    assert q.bid_size == 1.0
    assert q.ask_size == 1.0
    assert q.quality == DataQuality.REALTIME


def test_venue_quote_spread():
    q = make_quote(bid=100.0, ask=102.0)
    assert q.spread == pytest.approx(2.0)


def test_venue_quote_mid_price():
    q = make_quote(bid=100.0, ask=102.0)
    assert q.mid_price == pytest.approx(101.0)


def test_venue_quote_zero_spread_when_missing_bid_or_ask():
    q = make_quote(bid=0.0, ask=100.0)
    assert q.spread == 0.0
    q2 = make_quote(bid=100.0, ask=0.0)
    assert q2.spread == 0.0


def test_venue_quote_is_frozen():
    q = make_quote()
    with pytest.raises(AttributeError):
        q.bid = 999.0  # type: ignore[misc]


# ── AggregatedQuote ───────────────────────────────────────────────────────


def test_aggregated_quote_spread_and_mid():
    aq = AggregatedQuote(
        symbol="BTC-USD",
        best_bid=100.0,
        best_ask=101.0,
        best_bid_venue="venue_a",
        best_ask_venue="venue_b",
        vwap_bid=99.5,
        vwap_ask=100.5,
        total_bid_size=10.0,
        total_ask_size=8.0,
        venue_count=3,
        timestamp=time.time(),
    )
    assert aq.spread == pytest.approx(1.0)
    assert aq.mid_price == pytest.approx(100.5)


def test_aggregated_quote_zero_spread_when_no_bid_or_ask():
    aq = AggregatedQuote(
        symbol="BTC-USD",
        best_bid=0.0,
        best_ask=100.0,
        best_bid_venue="",
        best_ask_venue="venue_a",
        vwap_bid=0.0,
        vwap_ask=100.0,
        total_bid_size=0.0,
        total_ask_size=5.0,
        venue_count=1,
        timestamp=time.time(),
    )
    assert aq.spread == 0.0
    assert aq.mid_price == 0.0


# ── Basic Aggregation ────────────────────────────────────────────────────


def test_single_venue_aggregation():
    agg = VenueMarketDataAggregator()
    agg.add_venue_quote(make_quote(venue="venue_a", bid=100.0, ask=101.0))
    result = agg.get_aggregated_quote("BTC-USD")
    assert result is not None
    assert result.best_bid == pytest.approx(100.0)
    assert result.best_ask == pytest.approx(101.0)
    assert result.best_bid_venue == "venue_a"
    assert result.best_ask_venue == "venue_a"
    assert result.venue_count == 1


def test_multiple_venues_best_bid_ask():
    agg = VenueMarketDataAggregator()
    agg.add_venue_quote(make_quote(venue="venue_a", bid=100.0, ask=101.0))
    agg.add_venue_quote(make_quote(venue="venue_b", bid=100.5, ask=101.5))
    agg.add_venue_quote(make_quote(venue="venue_c", bid=99.5, ask=100.5))
    result = agg.get_aggregated_quote("BTC-USD")
    assert result is not None
    assert result.best_bid == pytest.approx(100.5)
    assert result.best_ask == pytest.approx(100.5)
    assert result.best_bid_venue == "venue_b"
    assert result.best_ask_venue == "venue_c"
    assert result.venue_count == 3


def test_vwap_aggregation():
    agg = VenueMarketDataAggregator(strategy=AggregationStrategy.VWAP)
    agg.add_venue_quote(make_quote(venue="venue_a", bid=100.0, ask=101.0, bid_size=2.0, ask_size=1.0))
    agg.add_venue_quote(make_quote(venue="venue_b", bid=102.0, ask=103.0, bid_size=3.0, ask_size=2.0))
    result = agg.get_aggregated_quote("BTC-USD")
    assert result is not None
    # VWAP bid = (100*2 + 102*3) / (2+3) = 506/5 = 101.2
    assert result.vwap_bid == pytest.approx(101.2)
    # VWAP ask = (101*1 + 103*2) / (1+2) = 307/3 ≈ 102.333
    assert result.vwap_ask == pytest.approx(307.0 / 3.0)


def test_total_size_aggregation():
    agg = VenueMarketDataAggregator()
    agg.add_venue_quote(make_quote(venue="venue_a", bid_size=5.0, ask_size=3.0))
    agg.add_venue_quote(make_quote(venue="venue_b", bid_size=7.0, ask_size=4.0))
    result = agg.get_aggregated_quote("BTC-USD")
    assert result is not None
    assert result.total_bid_size == pytest.approx(12.0)
    assert result.total_ask_size == pytest.approx(7.0)


# ── Symbol & Venue Management ─────────────────────────────────────────────


def test_get_all_aggregated_quotes():
    agg = VenueMarketDataAggregator()
    agg.add_venue_quote(make_quote(symbol="BTC-USD"))
    agg.add_venue_quote(make_quote(symbol="ETH-USD", bid=2000.0, ask=2001.0))
    all_quotes = agg.get_all_aggregated_quotes()
    assert len(all_quotes) == 2
    assert "BTC-USD" in all_quotes
    assert "ETH-USD" in all_quotes


def test_get_symbols():
    agg = VenueMarketDataAggregator()
    agg.add_venue_quote(make_quote(symbol="BTC-USD"))
    agg.add_venue_quote(make_quote(symbol="ETH-USD"))
    agg.add_venue_quote(make_quote(symbol="BTC-USD"))  # duplicate symbol
    symbols = agg.get_symbols()
    assert symbols == {"BTC-USD", "ETH-USD"}


def test_get_venue_count():
    agg = VenueMarketDataAggregator()
    assert agg.get_venue_count() == 0
    agg.add_venue_quote(make_quote(venue="venue_a"))
    agg.add_venue_quote(make_quote(venue="venue_b"))
    agg.add_venue_quote(make_quote(venue="venue_a"))  # same venue, different data
    assert agg.get_venue_count() == 2


def test_remove_venue():
    agg = VenueMarketDataAggregator()
    agg.add_venue_quote(make_quote(venue="venue_a", bid=100.0, ask=101.0))
    agg.add_venue_quote(make_quote(venue="venue_b", bid=100.5, ask=101.5))
    agg.remove_venue("venue_a")
    result = agg.get_aggregated_quote("BTC-USD")
    assert result is not None
    assert result.best_bid == pytest.approx(100.5)  # only venue_b remains
    assert result.venue_count == 1


def test_remove_nonexistent_venue_is_noop():
    agg = VenueMarketDataAggregator()
    agg.add_venue_quote(make_quote(venue="venue_a"))
    agg.remove_venue("nonexistent")
    assert agg.get_venue_count() == 1


def test_clear():
    agg = VenueMarketDataAggregator()
    agg.add_venue_quote(make_quote(venue="venue_a"))
    agg.add_venue_quote(make_quote(venue="venue_b"))
    agg.clear()
    assert agg.get_venue_count() == 0
    assert agg.get_symbols() == set()
    assert agg.get_all_aggregated_quotes() == {}


def test_get_aggregated_quote_returns_none_for_unknown_symbol():
    agg = VenueMarketDataAggregator()
    agg.add_venue_quote(make_quote(symbol="BTC-USD"))
    assert agg.get_aggregated_quote("UNKNOWN") is None


# ── Stale Data Handling ───────────────────────────────────────────────────


def test_stale_data_excluded():
    agg = VenueMarketDataAggregator(max_staleness_ms=100)
    now = time.time()
    agg.add_venue_quote(make_quote(venue="venue_a", timestamp=now))
    agg.add_venue_quote(make_quote(venue="venue_b", timestamp=now - 10.0))  # stale
    result = agg.get_aggregated_quote("BTC-USD")
    assert result is not None
    assert result.venue_count == 1
    assert result.best_bid_venue == "venue_a"


def test_all_stale_returns_none():
    agg = VenueMarketDataAggregator(max_staleness_ms=100)
    now = time.time()
    agg.add_venue_quote(make_quote(venue="venue_a", timestamp=now - 10.0))
    agg.add_venue_quote(make_quote(venue="venue_b", timestamp=now - 20.0))
    result = agg.get_aggregated_quote("BTC-USD")
    assert result is None


# ── Price Discrepancy & Arbitrage ────────────────────────────────────────


def test_price_discrepancy():
    agg = VenueMarketDataAggregator()
    agg.add_venue_quote(make_quote(venue="venue_a", bid=100.0, ask=101.0))
    agg.add_venue_quote(make_quote(venue="venue_b", bid=105.0, ask=106.0))
    discrepancy = agg.get_price_discrepancy("BTC-USD")
    assert discrepancy == pytest.approx(4.0)


def test_price_discrepancy_single_venue_is_zero():
    agg = VenueMarketDataAggregator()
    agg.add_venue_quote(make_quote(venue="venue_a"))
    assert agg.get_price_discrepancy("BTC-USD") == pytest.approx(0.0)


def test_detect_arbitrage_opportunity():
    agg = VenueMarketDataAggregator()
    # venue_a ask < venue_b bid → arbitrage
    agg.add_venue_quote(make_quote(venue="venue_a", bid=100.0, ask=101.0))
    agg.add_venue_quote(make_quote(venue="venue_b", bid=102.0, ask=103.0))
    arb = agg.detect_arbitrage("BTC-USD", min_spread=0.5)
    assert arb is not None
    assert arb.buy_venue == "venue_a"
    assert arb.sell_venue == "venue_b"
    assert arb.spread == pytest.approx(1.0)
    assert arb.profit_per_unit == pytest.approx(1.0)


def test_no_arbitrage_when_no_opportunity():
    agg = VenueMarketDataAggregator()
    agg.add_venue_quote(make_quote(venue="venue_a", bid=100.0, ask=101.0))
    agg.add_venue_quote(make_quote(venue="venue_b", bid=99.0, ask=100.0))
    arb = agg.detect_arbitrage("BTC-USD", min_spread=0.5)
    assert arb is None


def test_arbitrage_respects_min_spread():
    agg = VenueMarketDataAggregator()
    agg.add_venue_quote(make_quote(venue="venue_a", bid=100.0, ask=101.0))
    agg.add_venue_quote(make_quote(venue="venue_b", bid=101.2, ask=102.0))
    # spread is 0.2, below min_spread of 0.5
    arb = agg.detect_arbitrage("BTC-USD", min_spread=0.5)
    assert arb is None
    # spread is 0.2, above min_spread of 0.1
    arb2 = agg.detect_arbitrage("BTC-USD", min_spread=0.1)
    assert arb2 is not None


# ── Quality Filtering ─────────────────────────────────────────────────────


def test_quality_filter_excludes_stale():
    agg = VenueMarketDataAggregator(min_quality=DataQuality.DELAYED)
    now = time.time()
    agg.add_venue_quote(make_quote(venue="venue_a", quality=DataQuality.REALTIME, timestamp=now))
    agg.add_venue_quote(make_quote(venue="venue_b", quality=DataQuality.STALE, timestamp=now))
    result = agg.get_aggregated_quote("BTC-USD")
    assert result is not None
    assert result.venue_count == 1
    assert result.best_bid_venue == "venue_a"


# ── Thread Safety ────────────────────────────────────────────────────────


def test_thread_safe_concurrent_adds():
    agg = VenueMarketDataAggregator()
    errors: list[Exception] = []

    def add_quotes(venue_id: int) -> None:
        try:
            for i in range(100):
                agg.add_venue_quote(
                    make_quote(
                        venue=f"venue_{venue_id}",
                        symbol="BTC-USD",
                        bid=100.0 + i,
                        ask=101.0 + i,
                    )
                )
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=add_quotes, args=(i,)) for i in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(errors) == 0
    result = agg.get_aggregated_quote("BTC-USD")
    assert result is not None
    assert result.venue_count == 10


# ── Edge Cases ───────────────────────────────────────────────────────────


def test_zero_size_quotes_still_counted():
    agg = VenueMarketDataAggregator()
    agg.add_venue_quote(make_quote(venue="venue_a", bid=100.0, ask=101.0, bid_size=0.0, ask_size=0.0))
    result = agg.get_aggregated_quote("BTC-USD")
    assert result is not None
    assert result.venue_count == 1
    assert result.total_bid_size == pytest.approx(0.0)


def test_negative_prices_rejected():
    agg = VenueMarketDataAggregator()
    with pytest.raises(ValueError):
        agg.add_venue_quote(make_quote(bid=-1.0))
    with pytest.raises(ValueError):
        agg.add_venue_quote(make_quote(ask=-1.0))


def test_max_venues_limit():
    agg = VenueMarketDataAggregator(max_venues=3)
    agg.add_venue_quote(make_quote(venue="venue_a"))
    agg.add_venue_quote(make_quote(venue="venue_b"))
    agg.add_venue_quote(make_quote(venue="venue_c"))
    agg.add_venue_quote(make_quote(venue="venue_d"))  # should be rejected or evict oldest
    assert agg.get_venue_count() <= 3


def test_aggregated_quote_is_frozen():
    aq = AggregatedQuote(
        symbol="BTC-USD",
        best_bid=100.0,
        best_ask=101.0,
        best_bid_venue="a",
        best_ask_venue="b",
        vwap_bid=100.0,
        vwap_ask=101.0,
        total_bid_size=1.0,
        total_ask_size=1.0,
        venue_count=1,
        timestamp=time.time(),
    )
    with pytest.raises(AttributeError):
        aq.best_bid = 999.0  # type: ignore[misc]


def test_arbitrage_opportunity_is_frozen():
    arb = ArbitrageOpportunity(
        symbol="BTC-USD",
        buy_venue="a",
        sell_venue="b",
        buy_price=100.0,
        sell_price=101.0,
        spread=1.0,
        profit_per_unit=1.0,
        timestamp=time.time(),
    )
    assert arb.symbol == "BTC-USD"
    assert arb.profit_per_unit == pytest.approx(1.0)
    with pytest.raises(AttributeError):
        arb.spread = 999.0  # type: ignore[misc]


def test_best_strategy_selects_extremes():
    agg = VenueMarketDataAggregator(strategy=AggregationStrategy.BEST)
    agg.add_venue_quote(make_quote(venue="v1", bid=99.0, ask=102.0))
    agg.add_venue_quote(make_quote(venue="v2", bid=101.0, ask=100.0))
    agg.add_venue_quote(make_quote(venue="v3", bid=100.0, ask=101.0))
    result = agg.get_aggregated_quote("BTC-USD")
    assert result is not None
    assert result.best_bid == pytest.approx(101.0)
    assert result.best_ask == pytest.approx(100.0)
    assert result.best_bid_venue == "v2"
    assert result.best_ask_venue == "v2"


def test_vwap_strategy_computes_weighted_average():
    agg = VenueMarketDataAggregator(strategy=AggregationStrategy.VWAP)
    agg.add_venue_quote(make_quote(venue="v1", bid=100.0, ask=110.0, bid_size=1.0, ask_size=1.0))
    agg.add_venue_quote(make_quote(venue="v2", bid=102.0, ask=108.0, bid_size=3.0, ask_size=3.0))
    result = agg.get_aggregated_quote("BTC-USD")
    assert result is not None
    # VWAP bid = (100*1 + 102*3) / 4 = 406/4 = 101.5
    assert result.vwap_bid == pytest.approx(101.5)
    # VWAP ask = (110*1 + 108*3) / 4 = 434/4 = 108.5
    assert result.vwap_ask == pytest.approx(108.5)


def test_multiple_symbols_independent():
    agg = VenueMarketDataAggregator()
    agg.add_venue_quote(make_quote(symbol="BTC-USD", bid=100.0, ask=101.0))
    agg.add_venue_quote(make_quote(symbol="ETH-USD", bid=2000.0, ask=2001.0))
    agg.add_venue_quote(make_quote(symbol="BTC-USD", venue="venue_b", bid=100.5, ask=101.5))

    btc = agg.get_aggregated_quote("BTC-USD")
    eth = agg.get_aggregated_quote("ETH-USD")
    assert btc is not None
    assert eth is not None
    assert btc.venue_count == 2
    assert eth.venue_count == 1
    assert btc.best_bid == pytest.approx(100.5)
    assert eth.best_bid == pytest.approx(2000.0)


def test_update_existing_venue_quote():
    agg = VenueMarketDataAggregator()
    agg.add_venue_quote(make_quote(venue="venue_a", bid=100.0, ask=101.0))
    agg.add_venue_quote(make_quote(venue="venue_a", bid=102.0, ask=103.0))  # update
    result = agg.get_aggregated_quote("BTC-USD")
    assert result is not None
    assert result.venue_count == 1
    assert result.best_bid == pytest.approx(102.0)
    assert result.best_ask == pytest.approx(103.0)


def test_empty_aggregator_returns_empty():
    agg = VenueMarketDataAggregator()
    assert agg.get_all_aggregated_quotes() == {}
    assert agg.get_symbols() == set()
    assert agg.get_venue_count() == 0
    assert agg.get_aggregated_quote("ANY") is None
    assert agg.get_price_discrepancy("ANY") == 0.0
    assert agg.detect_arbitrage("ANY") is None
