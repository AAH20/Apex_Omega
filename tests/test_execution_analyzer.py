"""Tests for Venue Execution Analyzer — TDD: written before implementation."""

import pytest

from venues.execution_analyzer import Fill, ExecutionAnalyzer, VenuePerformance


def _make_fill(venue="BINANCE", symbol="BTCUSDT", side="buy", quantity=1.0,
               price=51_000.0, arrival_price=50_000.0, fees=2.5, timestamp=None):
    return Fill(venue=venue, symbol=symbol, side=side, quantity=quantity,
                price=price, arrival_price=arrival_price, fees=fees, timestamp=timestamp)


class TestFillSlippage:
    def test_buy_slippage_positive_when_paid_above_arrival(self):
        fill = Fill(venue="BINANCE", symbol="BTCUSDT", side="buy",
                    quantity=1.0, price=51_000.0, arrival_price=50_000.0)
        assert fill.slippage_bps == pytest.approx(200.0)

    def test_sell_slippage_positive_when_sold_below_arrival(self):
        fill = Fill(venue="BINANCE", symbol="BTCUSDT", side="sell",
                    quantity=1.0, price=49_000.0, arrival_price=50_000.0)
        assert fill.slippage_bps == pytest.approx(200.0)

    def test_buy_slippage_negative_when_paid_below_arrival(self):
        fill = Fill(venue="BINANCE", symbol="BTCUSDT", side="buy",
                    quantity=2.0, price=49_500.0, arrival_price=50_000.0)
        assert fill.slippage_bps == pytest.approx(-100.0)

    def test_sell_slippage_negative_when_sold_above_arrival(self):
        fill = Fill(venue="BINANCE", symbol="BTCUSDT", side="sell",
                    quantity=2.0, price=50_500.0, arrival_price=50_000.0)
        assert fill.slippage_bps == pytest.approx(-100.0)

    def test_slippage_zero_when_price_equals_arrival(self):
        fill = Fill(venue="BINANCE", symbol="BTCUSDT", side="buy",
                    quantity=1.0, price=50_000.0, arrival_price=50_000.0)
        assert fill.slippage_bps == pytest.approx(0.0)

    def test_slippage_raises_on_non_positive_arrival_price(self):
        fill = Fill(venue="BINANCE", symbol="BTCUSDT", side="buy",
                    quantity=1.0, price=50_000.0, arrival_price=0.0)
        with pytest.raises(ValueError, match="arrival_price"):
            _ = fill.slippage_bps

    def test_slippage_raises_on_unknown_side(self):
        fill = Fill(venue="BINANCE", symbol="BTCUSDT", side="hold",
                    quantity=1.0, price=50_000.0, arrival_price=50_000.0)
        with pytest.raises(ValueError, match="side"):
            _ = fill.slippage_bps


class TestFillEconomics:
    def test_notional_is_quantity_times_price(self):
        fill = Fill(venue="BINANCE", symbol="BTCUSDT", side="buy",
                    quantity=2.5, price=40_000.0, arrival_price=40_000.0)
        assert fill.notional == pytest.approx(100_000.0)

    def test_fee_bps_computation(self):
        fill = Fill(venue="BINANCE", symbol="BTCUSDT", side="buy",
                    quantity=1.0, price=50_000.0, arrival_price=50_000.0, fees=25.0)
        assert fill.fee_bps == pytest.approx(5.0)

    def test_fee_bps_zero_when_no_notional(self):
        fill = Fill(venue="BINANCE", symbol="BTCUSDT", side="buy",
                    quantity=0.0, price=50_000.0, arrival_price=50_000.0, fees=1.0)
        assert fill.fee_bps == 0.0


class TestVenuePerformance:
    def test_avg_slippage_bps_computes_mean(self):
        vp = VenuePerformance(venue="BINANCE")
        vp.slippage_bps_values = [10.0, 20.0, 30.0]
        assert vp.avg_slippage_bps == pytest.approx(20.0)

    def test_avg_slippage_bps_zero_when_no_fills(self):
        vp = VenuePerformance(venue="BINANCE")
        assert vp.avg_slippage_bps == 0.0

    def test_std_slippage_bps_requires_at_least_two_values(self):
        vp = VenuePerformance(venue="BINANCE")
        vp.slippage_bps_values = [10.0]
        assert vp.std_slippage_bps == 0.0

    def test_std_slippage_bps_computes_std_dev(self):
        vp = VenuePerformance(venue="BINANCE")
        vp.slippage_bps_values = [10.0, 20.0, 30.0]
        assert vp.std_slippage_bps == pytest.approx(10.0)

    def test_total_fee_bps_computation(self):
        vp = VenuePerformance(venue="BINANCE")
        vp.total_notional = 100_000.0
        vp.total_fees = 10.0
        assert vp.total_fee_bps == pytest.approx(1.0)

    def test_total_fee_bps_zero_when_no_notional(self):
        vp = VenuePerformance(venue="BINANCE")
        assert vp.total_fee_bps == 0.0

    def test_adverse_slippage_pct_computation(self):
        vp = VenuePerformance(venue="BINANCE")
        vp.slippage_bps_values = [10.0, -5.0, 20.0, -1.0]
        assert vp.adverse_slippage_pct == pytest.approx(50.0)

    def test_adverse_slippage_pct_zero_when_no_fills(self):
        vp = VenuePerformance(venue="BINANCE")
        assert vp.adverse_slippage_pct == 0.0


class TestExecutionAnalyzerBasics:
    def test_add_fill_appends_to_fills(self):
        analyzer = ExecutionAnalyzer()
        analyzer.add_fill(_make_fill())
        assert len(analyzer.fills) == 1

    def test_add_fills_appends_multiple(self):
        analyzer = ExecutionAnalyzer()
        analyzer.add_fills([_make_fill(), _make_fill()])
        assert len(analyzer.fills) == 2

    def test_fills_returns_copy_not_reference(self):
        analyzer = ExecutionAnalyzer()
        analyzer.add_fill(_make_fill())
        fills = analyzer.fills
        fills.clear()
        assert len(analyzer.fills) == 1

    def test_overall_slippage_bps_zero_when_no_fills(self):
        analyzer = ExecutionAnalyzer()
        assert analyzer.overall_slippage_bps() == 0.0

    def test_total_fees_sums_all_fees(self):
        analyzer = ExecutionAnalyzer()
        analyzer.add_fills([_make_fill(fees=1.0), _make_fill(fees=2.5)])
        assert analyzer.total_fees() == pytest.approx(3.5)

    def test_total_notional_sums_all_notionals(self):
        analyzer = ExecutionAnalyzer()
        analyzer.add_fills([_make_fill(quantity=1.0, price=50_000.0),
                            _make_fill(quantity=2.0, price=30_000.0)])
        assert analyzer.total_notional() == pytest.approx(110_000.0)

    def test_best_venue_none_when_no_fills(self):
        analyzer = ExecutionAnalyzer()
        assert analyzer.best_venue() is None

    def test_worst_venue_none_when_no_fills(self):
        analyzer = ExecutionAnalyzer()
        assert analyzer.worst_venue() is None


class TestExecutionAnalyzerVenuePerformance:
    def test_venue_performance_groups_by_venue(self):
        analyzer = ExecutionAnalyzer()
        analyzer.add_fills([
            _make_fill(venue="BINANCE", price=51_000.0, arrival_price=50_000.0),
            _make_fill(venue="BINANCE", price=52_000.0, arrival_price=50_000.0),
            _make_fill(venue="COINBASE", price=49_500.0, arrival_price=50_000.0),
        ])
        perf = analyzer.venue_performance()
        assert set(perf.keys()) == {"BINANCE", "COINBASE"}
        assert perf["BINANCE"].total_fills == 2
        assert perf["COINBASE"].total_fills == 1

    def test_venue_performance_filter_by_venue(self):
        analyzer = ExecutionAnalyzer()
        analyzer.add_fills([
            _make_fill(venue="BINANCE"),
            _make_fill(venue="COINBASE"),
        ])
        perf = analyzer.venue_performance(venue="BINANCE")
        assert set(perf.keys()) == {"BINANCE"}
        assert perf["BINANCE"].total_fills == 1

    def test_venue_performance_avg_slippage(self):
        analyzer = ExecutionAnalyzer()
        analyzer.add_fills([
            _make_fill(venue="BINANCE", price=51_000.0, arrival_price=50_000.0),
            _make_fill(venue="BINANCE", price=52_000.0, arrival_price=50_000.0),
        ])
        perf = analyzer.venue_performance()
        assert perf["BINANCE"].avg_slippage_bps == pytest.approx(300.0)

    def test_venue_performance_counts_by_symbol(self):
        analyzer = ExecutionAnalyzer()
        analyzer.add_fills([
            _make_fill(venue="BINANCE", symbol="BTCUSDT"),
            _make_fill(venue="BINANCE", symbol="BTCUSDT"),
            _make_fill(venue="BINANCE", symbol="ETHUSDT"),
        ])
        perf = analyzer.venue_performance()
        assert perf["BINANCE"].fill_count_by_symbol["BTCUSDT"] == 2
        assert perf["BINANCE"].fill_count_by_symbol["ETHUSDT"] == 1

    def test_venue_performance_total_notional_and_fees(self):
        analyzer = ExecutionAnalyzer()
        analyzer.add_fills([
            _make_fill(venue="BINANCE", quantity=1.0, price=50_000.0, fees=5.0),
            _make_fill(venue="BINANCE", quantity=2.0, price=25_000.0, fees=2.5),
        ])
        perf = analyzer.venue_performance()
        assert perf["BINANCE"].total_notional == pytest.approx(100_000.0)
        assert perf["BINANCE"].total_fees == pytest.approx(7.5)


class TestExecutionAnalyzerSlippage:
    def test_overall_slippage_bps_averages_all_fills(self):
        analyzer = ExecutionAnalyzer()
        analyzer.add_fills([
            _make_fill(price=51_000.0, arrival_price=50_000.0),
            _make_fill(price=49_000.0, arrival_price=50_000.0),
        ])
        assert analyzer.overall_slippage_bps() == pytest.approx(0.0)

    def test_best_venue_lowest_avg_slippage(self):
        analyzer = ExecutionAnalyzer()
        analyzer.add_fills([
            _make_fill(venue="BINANCE", price=51_000.0, arrival_price=50_000.0),
            _make_fill(venue="COINBASE", price=49_500.0, arrival_price=50_000.0),
        ])
        assert analyzer.best_venue() == "COINBASE"

    def test_worst_venue_highest_avg_slippage(self):
        analyzer = ExecutionAnalyzer()
        analyzer.add_fills([
            _make_fill(venue="BINANCE", price=51_000.0, arrival_price=50_000.0),
            _make_fill(venue="COINBASE", price=49_500.0, arrival_price=50_000.0),
        ])
        assert analyzer.worst_venue() == "BINANCE"

    def test_slippage_distribution_buckets(self):
        analyzer = ExecutionAnalyzer()
        analyzer.add_fills([
            _make_fill(price=49_000.0, arrival_price=50_000.0),   # -200 bps -> favorable
            _make_fill(price=50_000.0, arrival_price=50_000.0),   # 0 bps -> neutral
            _make_fill(price=50_100.0, arrival_price=50_000.0),   # 20 bps -> adverse
            _make_fill(price=60_000.0, arrival_price=50_000.0),   # 2000 bps -> severe
        ])
        dist = analyzer.slippage_distribution()
        assert dist["favorable"] == 1
        assert dist["neutral"] == 1
        assert dist["adverse"] == 1
        assert dist["severe"] == 1

    def test_slippage_distribution_empty(self):
        analyzer = ExecutionAnalyzer()
        dist = analyzer.slippage_distribution()
        assert dist == {"favorable": 0, "neutral": 0, "adverse": 0, "severe": 0}

    def test_slippage_distribution_neutral_boundary(self):
        analyzer = ExecutionAnalyzer()
        analyzer.add_fills([
            _make_fill(price=50_005.0, arrival_price=50_000.0),  # 1 bps -> neutral
            _make_fill(price=49_995.0, arrival_price=50_000.0),  # -1 bps -> neutral
        ])
        dist = analyzer.slippage_distribution()
        assert dist["neutral"] == 2

    def test_slippage_distribution_adverse_boundary(self):
        analyzer = ExecutionAnalyzer()
        analyzer.add_fills([
            _make_fill(price=50_500.0, arrival_price=50_000.0),   # 100 bps -> severe
            _make_fill(price=50_005.0, arrival_price=50_000.0),   # 1 bps -> neutral
        ])
        dist = analyzer.slippage_distribution()
        assert dist["severe"] == 1
        assert dist["neutral"] == 1
        assert dist["adverse"] == 0
