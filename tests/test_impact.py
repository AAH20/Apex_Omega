"""Tests for market impact, slippage estimation, and execution quality — TDD enforced."""
import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from order_book.impact import (
    BookLevel,
    ImpactEstimate,
    SlippageEstimate,
    ExecutionQuality,
    SquareRootImpactModel,
    AlmgrenChrissModel,
    estimate_slippage_from_book,
    compute_vwap,
    analyze_execution_quality,
    compute_participation_rate,
    compute_arrival_price_slippage,
)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _buy_book():
    """Standard ask-side book for buy slippage estimation."""
    return [
        BookLevel(price=100.0, volume=10),
        BookLevel(price=101.0, volume=20),
        BookLevel(price=102.0, volume=30),
    ]


def _sell_book():
    """Standard bid-side book for sell slippage estimation."""
    return [
        BookLevel(price=100.0, volume=10),
        BookLevel(price=99.0, volume=20),
        BookLevel(price=98.0, volume=30),
    ]


# ── VWAP Computation ─────────────────────────────────────────────────────────

class TestComputeVWAP:
    def test_vwap_single_level(self):
        levels = [BookLevel(price=100.0, volume=10)]
        assert compute_vwap(levels) == pytest.approx(100.0)

    def test_vwap_multiple_levels(self):
        levels = [
            BookLevel(price=100.0, volume=10),
            BookLevel(price=110.0, volume=30),
        ]
        # VWAP = (100*10 + 110*30) / 40 = 4300/40 = 107.5
        assert compute_vwap(levels) == pytest.approx(107.5)

    def test_vwap_empty_levels(self):
        assert compute_vwap([]) == 0.0

    def test_vwap_zero_total_volume(self):
        levels = [BookLevel(price=100.0, volume=0)]
        assert compute_vwap(levels) == 0.0


# ── Participation Rate ───────────────────────────────────────────────────────

class TestParticipationRate:
    def test_participation_rate_basic(self):
        assert compute_participation_rate(quantity=50, daily_volume=1000) == pytest.approx(0.05)

    def test_participation_rate_zero_daily_volume(self):
        assert compute_participation_rate(quantity=50, daily_volume=0) == 0.0

    def test_participation_rate_over_100_percent(self):
        assert compute_participation_rate(quantity=2000, daily_volume=1000) == pytest.approx(2.0)


# ── Square-Root Impact Model ─────────────────────────────────────────────────

class TestSquareRootImpactModel:
    def test_temporary_impact_increases_with_quantity(self):
        model = SquareRootImpactModel(eta=0.5)
        small = model.estimate_temporary_impact(
            quantity=10, daily_volume=1000, volatility=0.02
        )
        large = model.estimate_temporary_impact(
            quantity=100, daily_volume=1000, volatility=0.02
        )
        assert large > small

    def test_temporary_impact_increases_with_volatility(self):
        model = SquareRootImpactModel(eta=0.5)
        low_vol = model.estimate_temporary_impact(
            quantity=50, daily_volume=1000, volatility=0.01
        )
        high_vol = model.estimate_temporary_impact(
            quantity=50, daily_volume=1000, volatility=0.04
        )
        assert high_vol > low_vol

    def test_temporary_impact_decreases_with_daily_volume(self):
        model = SquareRootImpactModel(eta=0.5)
        low_liq = model.estimate_temporary_impact(
            quantity=50, daily_volume=500, volatility=0.02
        )
        high_liq = model.estimate_temporary_impact(
            quantity=50, daily_volume=2000, volatility=0.02
        )
        assert high_liq < low_liq

    def test_temporary_impact_zero_quantity(self):
        model = SquareRootImpactModel(eta=0.5)
        result = model.estimate_temporary_impact(
            quantity=0, daily_volume=1000, volatility=0.02
        )
        assert result == pytest.approx(0.0)

    def test_permanent_impact_proportional_to_temporary(self):
        model = SquareRootImpactModel(eta=0.5, gamma=0.3)
        temp = model.estimate_temporary_impact(
            quantity=50, daily_volume=1000, volatility=0.02
        )
        perm = model.estimate_permanent_impact(
            quantity=50, daily_volume=1000, volatility=0.02
        )
        assert perm < temp
        assert perm > 0

    def test_total_impact_is_sum(self):
        model = SquareRootImpactModel(eta=0.5, gamma=0.3)
        temp = model.estimate_temporary_impact(
            quantity=50, daily_volume=1000, volatility=0.02
        )
        perm = model.estimate_permanent_impact(
            quantity=50, daily_volume=1000, volatility=0.02
        )
        total = model.estimate_total_impact(
            quantity=50, daily_volume=1000, volatility=0.02
        )
        assert total == pytest.approx(temp + perm)


# ── Almgren-Chriss Model ─────────────────────────────────────────────────────

class TestAlmgrenChrissModel:
    def test_temporary_impact_positive(self):
        model = AlmgrenChrissModel(eta=0.5)
        result = model.estimate_temporary_impact(
            quantity=100, daily_volume=1000, volatility=0.02
        )
        assert result > 0

    def test_permanent_impact_positive(self):
        model = AlmgrenChrissModel(eta=0.5, gamma=0.3)
        result = model.estimate_permanent_impact(
            quantity=100, daily_volume=1000, volatility=0.02
        )
        assert result > 0

    def test_total_impact_combines_both(self):
        model = AlmgrenChrissModel(eta=0.5, gamma=0.3)
        temp = model.estimate_temporary_impact(
            quantity=100, daily_volume=1000, volatility=0.02
        )
        perm = model.estimate_permanent_impact(
            quantity=100, daily_volume=1000, volatility=0.02
        )
        total = model.estimate_total_impact(
            quantity=100, daily_volume=1000, volatility=0.02
        )
        assert total == pytest.approx(temp + perm)

    def test_impact_increases_with_quantity(self):
        model = AlmgrenChrissModel(eta=0.5)
        small = model.estimate_temporary_impact(
            quantity=10, daily_volume=1000, volatility=0.02
        )
        large = model.estimate_temporary_impact(
            quantity=100, daily_volume=1000, volatility=0.02
        )
        assert large > small


# ── Slippage Estimation from Book ────────────────────────────────────────────

class TestEstimateSlippageFromBook:
    def test_buy_slippage_positive_when_sweeping_asks(self):
        book = _buy_book()
        result = estimate_slippage_from_book(
            side="buy", quantity=15, book_levels=book, arrival_price=100.0
        )
        assert result.slippage_bps > 0
        assert result.filled_volume == 15
        assert result.requested_volume == 15

    def test_sell_slippage_positive_when_sweeping_bids(self):
        book = _sell_book()
        result = estimate_slippage_from_book(
            side="sell", quantity=15, book_levels=book, arrival_price=100.0
        )
        assert result.slippage_bps > 0
        assert result.filled_volume == 15

    def test_slippage_zero_when_quantity_fits_at_top(self):
        book = [BookLevel(price=100.0, volume=100)]
        result = estimate_slippage_from_book(
            side="buy", quantity=10, book_levels=book, arrival_price=100.0
        )
        assert result.slippage_bps == pytest.approx(0.0)

    def test_partial_fill_when_book_too_shallow(self):
        book = [BookLevel(price=100.0, volume=5)]
        result = estimate_slippage_from_book(
            side="buy", quantity=20, book_levels=book, arrival_price=100.0
        )
        assert result.filled_volume == 5
        assert result.requested_volume == 20

    def test_empty_book_no_fill(self):
        result = estimate_slippage_from_book(
            side="buy", quantity=10, book_levels=[], arrival_price=100.0
        )
        assert result.filled_volume == 0
        assert result.slippage_bps == 0.0

    def test_vwap_computed_correctly_for_partial_sweep(self):
        book = [
            BookLevel(price=100.0, volume=10),
            BookLevel(price=102.0, volume=10),
        ]
        result = estimate_slippage_from_book(
            side="buy", quantity=15, book_levels=book, arrival_price=100.0
        )
        # VWAP = (100*10 + 102*5) / 15 = 1510/15 ≈ 100.667
        assert result.expected_vwap == pytest.approx(100.6667, rel=1e-3)

    def test_sell_side_vwap(self):
        book = [
            BookLevel(price=100.0, volume=10),
            BookLevel(price=98.0, volume=10),
        ]
        result = estimate_slippage_from_book(
            side="sell", quantity=15, book_levels=book, arrival_price=100.0
        )
        # VWAP = (100*10 + 98*5) / 15 = 1490/15 ≈ 99.333
        assert result.expected_vwap == pytest.approx(99.3333, rel=1e-3)
        assert result.slippage_bps > 0


# ── Execution Quality Analysis ───────────────────────────────────────────────

class TestExecutionQuality:
    def test_implementation_shortfall_buy(self):
        fills = [
            {"price": 101.0, "quantity": 10},
            {"price": 102.0, "quantity": 5},
        ]
        result = analyze_execution_quality(
            fills=fills, arrival_price=100.0, side="buy"
        )
        # VWAP = (101*10 + 102*5) / 15 = 1520/15 ≈ 101.333
        # IS = (101.333 - 100) / 100 * 10000 = 133.3 bps
        assert result.implementation_shortfall_bps == pytest.approx(133.33, rel=1e-2)

    def test_implementation_shortfall_sell(self):
        fills = [
            {"price": 99.0, "quantity": 10},
            {"price": 98.0, "quantity": 5},
        ]
        result = analyze_execution_quality(
            fills=fills, arrival_price=100.0, side="sell"
        )
        # VWAP = (99*10 + 98*5) / 15 = 1480/15 ≈ 98.667
        # IS = (100 - 98.667) / 100 * 10000 = 133.3 bps
        assert result.implementation_shortfall_bps == pytest.approx(133.33, rel=1e-2)

    def test_zero_shortfall_when_price_equals_arrival(self):
        fills = [{"price": 100.0, "quantity": 10}]
        result = analyze_execution_quality(
            fills=fills, arrival_price=100.0, side="buy"
        )
        assert result.implementation_shortfall_bps == pytest.approx(0.0)

    def test_fill_rate_complete(self):
        fills = [{"price": 100.0, "quantity": 10}]
        result = analyze_execution_quality(
            fills=fills, arrival_price=100.0, side="buy", requested_quantity=10
        )
        assert result.fill_rate == pytest.approx(1.0)

    def test_fill_rate_partial(self):
        fills = [{"price": 100.0, "quantity": 5}]
        result = analyze_execution_quality(
            fills=fills, arrival_price=100.0, side="buy", requested_quantity=10
        )
        assert result.fill_rate == pytest.approx(0.5)

    def test_empty_fills_zero_shortfall(self):
        result = analyze_execution_quality(
            fills=[], arrival_price=100.0, side="buy"
        )
        assert result.implementation_shortfall_bps == 0.0
        assert result.fill_rate == 0.0


# ── Arrival Price Slippage ───────────────────────────────────────────────────

class TestArrivalPriceSlippage:
    def test_buy_slippage_positive(self):
        result = compute_arrival_price_slippage(
            side="buy", execution_price=101.0, arrival_price=100.0
        )
        assert result == pytest.approx(100.0)

    def test_sell_slippage_positive(self):
        result = compute_arrival_price_slippage(
            side="sell", execution_price=99.0, arrival_price=100.0
        )
        assert result == pytest.approx(100.0)

    def test_buy_slippage_negative_favorable(self):
        result = compute_arrival_price_slippage(
            side="buy", execution_price=99.0, arrival_price=100.0
        )
        assert result == pytest.approx(-100.0)

    def test_sell_slippage_negative_favorable(self):
        result = compute_arrival_price_slippage(
            side="sell", execution_price=101.0, arrival_price=100.0
        )
        assert result == pytest.approx(-100.0)

    def test_zero_slippage(self):
        result = compute_arrival_price_slippage(
            side="buy", execution_price=100.0, arrival_price=100.0
        )
        assert result == pytest.approx(0.0)

    def test_invalid_side_raises(self):
        with pytest.raises(ValueError, match="side"):
            compute_arrival_price_slippage(
                side="hold", execution_price=100.0, arrival_price=100.0
            )

    def test_non_positive_arrival_raises(self):
        with pytest.raises(ValueError, match="arrival_price"):
            compute_arrival_price_slippage(
                side="buy", execution_price=100.0, arrival_price=0.0
            )
