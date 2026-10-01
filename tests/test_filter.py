"""Tests for feed filter."""

import pytest

from feed.filter import (
    FeedFilter,
    FilterConfig,
    MarketData,
    MatchMode,
    PriceRule,
    SymbolRule,
    VenueRule,
)


def make_data(symbol="AAPL", price=150.0, venue="NYSE"):
    return MarketData(symbol=symbol, price=price, venue=venue)


class TestEmptyFilter:
    def test_no_rules_passes_everything(self):
        config = FilterConfig()
        f = FeedFilter(config)
        data = [make_data("AAPL"), make_data("GOOG"), make_data("MSFT")]
        assert f.filter(data) == data

    def test_empty_data_returns_empty(self):
        config = FilterConfig()
        f = FeedFilter(config)
        assert f.filter([]) == []


class TestSymbolFilter:
    def test_include_single_symbol(self):
        config = FilterConfig(symbol_rule=SymbolRule(symbols={"AAPL"}))
        f = FeedFilter(config)
        data = [make_data("AAPL"), make_data("GOOG"), make_data("MSFT")]
        result = f.filter(data)
        assert len(result) == 1
        assert result[0].symbol == "AAPL"

    def test_include_multiple_symbols(self):
        config = FilterConfig(symbol_rule=SymbolRule(symbols={"AAPL", "GOOG"}))
        f = FeedFilter(config)
        data = [make_data("AAPL"), make_data("GOOG"), make_data("MSFT")]
        result = f.filter(data)
        assert len(result) == 2
        assert {d.symbol for d in result} == {"AAPL", "GOOG"}

    def test_exclude_single_symbol(self):
        config = FilterConfig(symbol_rule=SymbolRule(symbols={"AAPL"}, mode=MatchMode.EXCLUDE))
        f = FeedFilter(config)
        data = [make_data("AAPL"), make_data("GOOG"), make_data("MSFT")]
        result = f.filter(data)
        assert len(result) == 2
        assert "AAPL" not in {d.symbol for d in result}

    def test_exclude_multiple_symbols(self):
        config = FilterConfig(symbol_rule=SymbolRule(symbols={"AAPL", "GOOG"}, mode=MatchMode.EXCLUDE))
        f = FeedFilter(config)
        data = [make_data("AAPL"), make_data("GOOG"), make_data("MSFT")]
        result = f.filter(data)
        assert len(result) == 1
        assert result[0].symbol == "MSFT"

    def test_empty_include_set_matches_nothing(self):
        config = FilterConfig(symbol_rule=SymbolRule(symbols=set()))
        f = FeedFilter(config)
        data = [make_data("AAPL"), make_data("GOOG")]
        assert f.filter(data) == []

    def test_empty_exclude_set_matches_everything(self):
        config = FilterConfig(symbol_rule=SymbolRule(symbols=set(), mode=MatchMode.EXCLUDE))
        f = FeedFilter(config)
        data = [make_data("AAPL"), make_data("GOOG")]
        assert f.filter(data) == data

    def test_case_sensitive_by_default(self):
        config = FilterConfig(symbol_rule=SymbolRule(symbols={"AAPL"}))
        f = FeedFilter(config)
        data = [make_data("AAPL"), make_data("aapl")]
        result = f.filter(data)
        assert len(result) == 1
        assert result[0].symbol == "AAPL"

    def test_case_insensitive(self):
        config = FilterConfig(symbol_rule=SymbolRule(symbols={"AAPL"}, case_sensitive=False))
        f = FeedFilter(config)
        data = [make_data("AAPL"), make_data("aapl"), make_data("Aapl")]
        result = f.filter(data)
        assert len(result) == 3


class TestPriceFilter:
    def test_min_price(self):
        config = FilterConfig(price_rule=PriceRule(min_price=100.0))
        f = FeedFilter(config)
        data = [make_data(price=50.0), make_data(price=100.0), make_data(price=150.0)]
        result = f.filter(data)
        assert len(result) == 2
        assert all(d.price >= 100.0 for d in result)

    def test_max_price(self):
        config = FilterConfig(price_rule=PriceRule(max_price=100.0))
        f = FeedFilter(config)
        data = [make_data(price=50.0), make_data(price=100.0), make_data(price=150.0)]
        result = f.filter(data)
        assert len(result) == 2
        assert all(d.price <= 100.0 for d in result)

    def test_price_range(self):
        config = FilterConfig(price_rule=PriceRule(min_price=100.0, max_price=200.0))
        f = FeedFilter(config)
        data = [make_data(price=50.0), make_data(price=150.0), make_data(price=250.0)]
        result = f.filter(data)
        assert len(result) == 1
        assert result[0].price == 150.0

    def test_boundary_min_price_inclusive(self):
        config = FilterConfig(price_rule=PriceRule(min_price=100.0))
        f = FeedFilter(config)
        data = [make_data(price=100.0)]
        assert f.filter(data) == data

    def test_boundary_max_price_inclusive(self):
        config = FilterConfig(price_rule=PriceRule(max_price=100.0))
        f = FeedFilter(config)
        data = [make_data(price=100.0)]
        assert f.filter(data) == data

    def test_no_price_rule_passes_all(self):
        config = FilterConfig()
        f = FeedFilter(config)
        data = [make_data(price=0.0), make_data(price=999999.0)]
        assert f.filter(data) == data


class TestVenueFilter:
    def test_include_single_venue(self):
        config = FilterConfig(venue_rule=VenueRule(venues={"NYSE"}))
        f = FeedFilter(config)
        data = [make_data(venue="NYSE"), make_data(venue="NASDAQ"), make_data(venue="BATS")]
        result = f.filter(data)
        assert len(result) == 1
        assert result[0].venue == "NYSE"

    def test_include_multiple_venues(self):
        config = FilterConfig(venue_rule=VenueRule(venues={"NYSE", "NASDAQ"}))
        f = FeedFilter(config)
        data = [make_data(venue="NYSE"), make_data(venue="NASDAQ"), make_data(venue="BATS")]
        result = f.filter(data)
        assert len(result) == 2
        assert {d.venue for d in result} == {"NYSE", "NASDAQ"}

    def test_exclude_single_venue(self):
        config = FilterConfig(venue_rule=VenueRule(venues={"NYSE"}, mode=MatchMode.EXCLUDE))
        f = FeedFilter(config)
        data = [make_data(venue="NYSE"), make_data(venue="NASDAQ"), make_data(venue="BATS")]
        result = f.filter(data)
        assert len(result) == 2
        assert "NYSE" not in {d.venue for d in result}

    def test_empty_include_venues_matches_nothing(self):
        config = FilterConfig(venue_rule=VenueRule(venues=set()))
        f = FeedFilter(config)
        data = [make_data(venue="NYSE"), make_data(venue="NASDAQ")]
        assert f.filter(data) == []

    def test_empty_exclude_venues_matches_everything(self):
        config = FilterConfig(venue_rule=VenueRule(venues=set(), mode=MatchMode.EXCLUDE))
        f = FeedFilter(config)
        data = [make_data(venue="NYSE"), make_data(venue="NASDAQ")]
        assert f.filter(data) == data


class TestCombinedFilters:
    def test_symbol_and_price(self):
        config = FilterConfig(
            symbol_rule=SymbolRule(symbols={"AAPL", "GOOG"}),
            price_rule=PriceRule(min_price=100.0),
        )
        f = FeedFilter(config)
        data = [
            make_data("AAPL", 50.0),
            make_data("AAPL", 150.0),
            make_data("GOOG", 200.0),
            make_data("MSFT", 300.0),
        ]
        result = f.filter(data)
        assert len(result) == 2
        assert {d.symbol for d in result} == {"AAPL", "GOOG"}

    def test_symbol_and_venue(self):
        config = FilterConfig(
            symbol_rule=SymbolRule(symbols={"AAPL"}),
            venue_rule=VenueRule(venues={"NYSE"}),
        )
        f = FeedFilter(config)
        data = [
            make_data("AAPL", venue="NYSE"),
            make_data("AAPL", venue="NASDAQ"),
            make_data("GOOG", venue="NYSE"),
        ]
        result = f.filter(data)
        assert len(result) == 1
        assert result[0].symbol == "AAPL"
        assert result[0].venue == "NYSE"

    def test_all_three_filters(self):
        config = FilterConfig(
            symbol_rule=SymbolRule(symbols={"AAPL", "GOOG"}),
            price_rule=PriceRule(min_price=100.0, max_price=200.0),
            venue_rule=VenueRule(venues={"NYSE", "NASDAQ"}),
        )
        f = FeedFilter(config)
        data = [
            make_data("AAPL", 150.0, "NYSE"),
            make_data("AAPL", 250.0, "NYSE"),
            make_data("GOOG", 150.0, "BATS"),
            make_data("GOOG", 150.0, "NASDAQ"),
            make_data("MSFT", 150.0, "NYSE"),
        ]
        result = f.filter(data)
        assert len(result) == 2
        assert {d.symbol for d in result} == {"AAPL", "GOOG"}


class TestFilterBehavior:
    def test_filter_returns_new_list(self):
        config = FilterConfig(symbol_rule=SymbolRule(symbols={"AAPL"}))
        f = FeedFilter(config)
        data = [make_data("AAPL"), make_data("GOOG")]
        result = f.filter(data)
        assert result is not data
        assert len(data) == 2  # original unchanged

    def test_matches_single_item(self):
        config = FilterConfig(symbol_rule=SymbolRule(symbols={"AAPL"}))
        f = FeedFilter(config)
        assert f.matches(make_data("AAPL")) is True
        assert f.matches(make_data("GOOG")) is False

    def test_no_matches_returns_empty(self):
        config = FilterConfig(symbol_rule=SymbolRule(symbols={"AAPL"}))
        f = FeedFilter(config)
        data = [make_data("GOOG"), make_data("MSFT")]
        assert f.filter(data) == []

    def test_all_match_returns_all(self):
        config = FilterConfig(symbol_rule=SymbolRule(symbols={"AAPL", "GOOG"}))
        f = FeedFilter(config)
        data = [make_data("AAPL"), make_data("GOOG")]
        assert f.filter(data) == data
