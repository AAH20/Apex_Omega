"""Unit tests for Smart Order Router — liquidity aggregation, venue selection, execution optimization."""
from __future__ import annotations

import time

import pytest

from src.venues.smart_routing import (
    ExecutionPlan,
    ExecutionSlice,
    LiquiditySnapshot,
    OrderSide,
    SmartOrderRouter,
    VenueLiquidity,
    VenueScore,
)


# ── Helpers ──────────────────────────────────────────────────────────────


def make_venue_liquidity(
    name: str = "VENUE_A",
    symbol: str = "AAPL",
    bid: float = 100.0,
    ask: float = 100.10,
    bid_size: float = 1000.0,
    ask_size: float = 1000.0,
    latency_ms: float = 1.0,
    fee_bps: float = 5.0,
    depth_levels: int = 5,
) -> VenueLiquidity:
    return VenueLiquidity(
        name=name,
        symbol=symbol,
        bid=bid,
        ask=ask,
        bid_size=bid_size,
        ask_size=ask_size,
        latency_ms=latency_ms,
        fee_bps=fee_bps,
        depth_levels=depth_levels,
    )


def make_buy_order(symbol: str = "AAPL", quantity: float = 100.0):
    return {"symbol": symbol, "side": OrderSide.BUY, "quantity": quantity}


def make_sell_order(symbol: str = "AAPL", quantity: float = 100.0):
    return {"symbol": symbol, "side": OrderSide.SELL, "quantity": quantity}


# ── VenueLiquidity ───────────────────────────────────────────────────────


def test_venue_liquidity_creation():
    vl = make_venue_liquidity()
    assert vl.name == "VENUE_A"
    assert vl.symbol == "AAPL"
    assert vl.bid == 100.0
    assert vl.ask == 100.10
    assert vl.bid_size == 1000.0
    assert vl.ask_size == 1000.0


def test_venue_liquidity_mid_price():
    vl = make_venue_liquidity(bid=99.0, ask=101.0)
    assert vl.mid_price == pytest.approx(100.0)


def test_venue_liquidity_spread():
    vl = make_venue_liquidity(bid=99.0, ask=101.0)
    assert vl.spread == pytest.approx(2.0)


def test_venue_liquidity_spread_bps():
    vl = make_venue_liquidity(bid=99.0, ask=101.0)
    assert vl.spread_bps == pytest.approx(200.0)


def test_venue_liquidity_available_size_buy():
    vl = make_venue_liquidity(ask_size=500.0)
    assert vl.available_size(OrderSide.BUY) == 500.0


def test_venue_liquidity_available_size_sell():
    vl = make_venue_liquidity(bid_size=750.0)
    assert vl.available_size(OrderSide.SELL) == 750.0


# ── LiquiditySnapshot ────────────────────────────────────────────────────


def test_liquidity_snapshot_creation():
    vl = make_venue_liquidity()
    snapshot = LiquiditySnapshot(symbol="AAPL", venues=[vl])
    assert snapshot.symbol == "AAPL"
    assert len(snapshot.venues) == 1


def test_liquidity_snapshot_total_bid_size():
    vls = [
        make_venue_liquidity("A", bid_size=100.0),
        make_venue_liquidity("B", bid_size=200.0),
    ]
    snapshot = LiquiditySnapshot(symbol="AAPL", venues=vls)
    assert snapshot.total_bid_size == 300.0


def test_liquidity_snapshot_total_ask_size():
    vls = [
        make_venue_liquidity("A", ask_size=100.0),
        make_venue_liquidity("B", ask_size=200.0),
    ]
    snapshot = LiquiditySnapshot(symbol="AAPL", venues=vls)
    assert snapshot.total_ask_size == 300.0


def test_liquidity_snapshot_best_bid():
    vls = [
        make_venue_liquidity("A", bid=99.5),
        make_venue_liquidity("B", bid=100.0),
        make_venue_liquidity("C", bid=99.8),
    ]
    snapshot = LiquiditySnapshot(symbol="AAPL", venues=vls)
    assert snapshot.best_bid == 100.0
    assert snapshot.best_bid_venue == "B"


def test_liquidity_snapshot_best_ask():
    vls = [
        make_venue_liquidity("A", ask=100.5),
        make_venue_liquidity("B", ask=100.1),
        make_venue_liquidity("C", ask=100.3),
    ]
    snapshot = LiquiditySnapshot(symbol="AAPL", venues=vls)
    assert snapshot.best_ask == 100.1
    assert snapshot.best_venue == "B"


def test_liquidity_snapshot_empty():
    snapshot = LiquiditySnapshot(symbol="AAPL", venues=[])
    assert snapshot.total_bid_size == 0.0
    assert snapshot.total_ask_size == 0.0
    assert snapshot.best_bid == 0.0
    assert snapshot.best_ask == 0.0


# ── VenueScore ───────────────────────────────────────────────────────────


def test_venue_score_creation():
    vs = VenueScore(venue_name="A", score=95.5, reason="best price")
    assert vs.venue_name == "A"
    assert vs.score == 95.5
    assert vs.reason == "best price"


# ── SmartOrderRouter initialization ──────────────────────────────────────


def test_router_initializes_empty():
    router = SmartOrderRouter()
    assert router.venues == []


def test_router_with_venues():
    vls = [make_venue_liquidity("A"), make_venue_liquidity("B")]
    router = SmartOrderRouter(venues=vls)
    assert len(router.venues) == 2


def test_router_add_venue():
    router = SmartOrderRouter()
    router.add_venue(make_venue_liquidity("A"))
    assert len(router.venues) == 1


def test_router_add_duplicate_venue_raises():
    router = SmartOrderRouter()
    router.add_venue(make_venue_liquidity("A"))
    with pytest.raises(ValueError, match="already exists"):
        router.add_venue(make_venue_liquidity("A"))


def test_router_remove_venue():
    router = SmartOrderRouter(venues=[make_venue_liquidity("A"), make_venue_liquidity("B")])
    router.remove_venue("A")
    assert len(router.venues) == 1
    assert router.venues[0].name == "B"


def test_router_remove_nonexistent_venue_raises():
    router = SmartOrderRouter()
    with pytest.raises(ValueError, match="not found"):
        router.remove_venue("NONEXISTENT")


# ── Liquidity aggregation ────────────────────────────────────────────────


def test_aggregate_liquidity_single_venue():
    router = SmartOrderRouter(venues=[make_venue_liquidity("A")])
    snapshot = router.aggregate_liquidity("AAPL")
    assert snapshot is not None
    assert snapshot.symbol == "AAPL"
    assert len(snapshot.venues) == 1


def test_aggregate_liquidity_multiple_venues():
    router = SmartOrderRouter(
        venues=[
            make_venue_liquidity("A", bid=100.0, ask=100.10),
            make_venue_liquidity("B", bid=100.05, ask=100.15),
        ]
    )
    snapshot = router.aggregate_liquidity("AAPL")
    assert snapshot is not None
    assert len(snapshot.venues) == 2
    assert snapshot.best_bid == 100.05
    assert snapshot.best_ask == 100.10


def test_aggregate_liquidity_no_venues_returns_none():
    router = SmartOrderRouter()
    snapshot = router.aggregate_liquidity("AAPL")
    assert snapshot is None


def test_aggregate_liquidity_filters_by_symbol():
    router = SmartOrderRouter(
        venues=[
            make_venue_liquidity("A", symbol="AAPL"),
            make_venue_liquidity("B", symbol="GOOG"),
        ]
    )
    snapshot = router.aggregate_liquidity("AAPL")
    assert snapshot is not None
    assert len(snapshot.venues) == 1
    assert snapshot.venues[0].name == "A"


# ── Venue selection ──────────────────────────────────────────────────────


def test_select_best_venue_buy_by_price():
    router = SmartOrderRouter(
        venues=[
            make_venue_liquidity("A", ask=100.50, ask_size=500),
            make_venue_liquidity("B", ask=100.10, ask_size=500),
            make_venue_liquidity("C", ask=100.30, ask_size=500),
        ]
    )
    order = make_buy_order()
    decision = router.select_venue(order)
    assert decision.venue_name == "B"


def test_select_best_venue_sell_by_price():
    router = SmartOrderRouter(
        venues=[
            make_venue_liquidity("A", bid=99.50, bid_size=500),
            make_venue_liquidity("B", bid=99.90, bid_size=500),
            make_venue_liquidity("C", bid=99.70, bid_size=500),
        ]
    )
    order = make_sell_order()
    decision = router.select_venue(order)
    assert decision.venue_name == "B"


def test_select_venue_filters_insufficient_liquidity():
    router = SmartOrderRouter(
        venues=[
            make_venue_liquidity("A", ask=100.10, ask_size=50),
            make_venue_liquidity("B", ask=100.20, ask_size=500),
        ]
    )
    order = make_buy_order(quantity=100)
    decision = router.select_venue(order)
    assert decision.venue_name == "B"


def test_select_venue_all_insufficient_liquidity_raises():
    router = SmartOrderRouter(
        venues=[
            make_venue_liquidity("A", ask=100.10, ask_size=50),
            make_venue_liquidity("B", ask=100.20, ask_size=50),
        ]
    )
    order = make_buy_order(quantity=100)
    with pytest.raises(ValueError, match="Insufficient liquidity"):
        router.select_venue(order)


def test_select_venue_no_venues_raises():
    router = SmartOrderRouter()
    order = make_buy_order()
    with pytest.raises(ValueError, match="No venues"):
        router.select_venue(order)


def test_select_venue_prefers_low_latency_on_tie():
    router = SmartOrderRouter(
        venues=[
            make_venue_liquidity("A", ask=100.10, ask_size=500, latency_ms=10.0),
            make_venue_liquidity("B", ask=100.10, ask_size=500, latency_ms=1.0),
        ]
    )
    order = make_buy_order()
    decision = router.select_venue(order)
    assert decision.venue_name == "B"


def test_select_venue_prefers_low_fees_on_tie():
    router = SmartOrderRouter(
        venues=[
            make_venue_liquidity("A", ask=100.10, ask_size=500, fee_bps=10.0),
            make_venue_liquidity("B", ask=100.10, ask_size=500, fee_bps=2.0),
        ]
    )
    order = make_buy_order()
    decision = router.select_venue(order)
    assert decision.venue_name == "B"


def test_select_venue_with_allowed_list():
    router = SmartOrderRouter(
        venues=[
            make_venue_liquidity("A", ask=100.10),
            make_venue_liquidity("B", ask=100.05),
            make_venue_liquidity("C", ask=100.00),
        ]
    )
    order = make_buy_order()
    decision = router.select_venue(order, allowed_venues=["A", "B"])
    assert decision.venue_name == "B"


def test_select_venue_with_disallowed_list_raises():
    router = SmartOrderRouter(venues=[make_venue_liquidity("A")])
    order = make_buy_order()
    with pytest.raises(ValueError, match="No venues"):
        router.select_venue(order, allowed_venues=["C"])


# ── Execution optimization ───────────────────────────────────────────────


def test_create_execution_plan_single_venue():
    router = SmartOrderRouter(
        venues=[make_venue_liquidity("A", ask=100.10, ask_size=1000)]
    )
    order = make_buy_order(quantity=100)
    plan = router.create_execution_plan(order)
    assert isinstance(plan, ExecutionPlan)
    assert plan.total_quantity == 100.0
    assert len(plan.slices) == 1
    assert plan.slices[0].venue_name == "A"
    assert plan.slices[0].quantity == 100.0


def test_create_execution_plan_splits_across_venues():
    router = SmartOrderRouter(
        venues=[
            make_venue_liquidity("A", ask=100.10, ask_size=500),
            make_venue_liquidity("B", ask=100.15, ask_size=500),
        ]
    )
    order = make_buy_order(quantity=800)
    plan = router.create_execution_plan(order)
    assert plan.total_quantity == 800.0
    assert len(plan.slices) == 2
    total = sum(s.quantity for s in plan.slices)
    assert total == pytest.approx(800.0)


def test_create_execution_plan_respects_venue_capacity():
    router = SmartOrderRouter(
        venues=[
            make_venue_liquidity("A", ask=100.10, ask_size=100),
            make_venue_liquidity("B", ask=100.20, ask_size=1000),
        ]
    )
    order = make_buy_order(quantity=500)
    plan = router.create_execution_plan(order)
    # A can only provide 100, B provides the rest
    slice_a = next(s for s in plan.slices if s.venue_name == "A")
    slice_b = next(s for s in plan.slices if s.venue_name == "B")
    assert slice_a.quantity == pytest.approx(100.0)
    assert slice_b.quantity == pytest.approx(400.0)


def test_create_execution_plan_no_venues_raises():
    router = SmartOrderRouter()
    order = make_buy_order()
    with pytest.raises(ValueError, match="No venues"):
        router.create_execution_plan(order)


def test_create_execution_plan_insufficient_total_liquidity_raises():
    router = SmartOrderRouter(
        venues=[
            make_venue_liquidity("A", ask=100.10, ask_size=50),
            make_venue_liquidity("B", ask=100.20, ask_size=50),
        ]
    )
    order = make_buy_order(quantity=200)
    with pytest.raises(ValueError, match="Insufficient liquidity"):
        router.create_execution_plan(order)


def test_execution_plan_slices_have_valid_prices():
    router = SmartOrderRouter(
        venues=[
            make_venue_liquidity("A", ask=100.10, ask_size=500),
            make_venue_liquidity("B", ask=100.15, ask_size=500),
        ]
    )
    order = make_buy_order(quantity=300)
    plan = router.create_execution_plan(order)
    for s in plan.slices:
        assert s.price > 0
        assert s.quantity > 0


def test_execution_plan_total_cost():
    router = SmartOrderRouter(
        venues=[
            make_venue_liquidity("A", ask=100.0, ask_size=500),
            make_venue_liquidity("B", ask=100.0, ask_size=500),
        ]
    )
    order = make_buy_order(quantity=200)
    plan = router.create_execution_plan(order)
    expected_cost = sum(s.price * s.quantity for s in plan.slices)
    assert plan.total_cost == pytest.approx(expected_cost)


def test_create_execution_plan_with_max_participation():
    router = SmartOrderRouter(
        venues=[
            make_venue_liquidity("A", ask=100.10, ask_size=10000),
            make_venue_liquidity("B", ask=100.15, ask_size=10000),
        ]
    )
    order = make_buy_order(quantity=1000)
    # With 10% max participation, each venue gets at most 1000 (10% of 10000)
    plan = router.create_execution_plan(order, max_participation=0.10)
    for s in plan.slices:
        assert s.quantity <= 1000.0 + 1e-9


# ── TWAP slicing ─────────────────────────────────────────────────────────


def test_twap_slicing_even_distribution():
    router = SmartOrderRouter(
        venues=[make_venue_liquidity("A", ask=100.10, ask_size=10000)]
    )
    order = make_buy_order(quantity=1000)
    slices = router.twap_slices(order, num_slices=5, interval_seconds=60)
    assert len(slices) == 5
    total = sum(s.quantity for s in slices)
    assert total == pytest.approx(1000.0)
    # Each slice should be roughly equal
    for s in slices:
        assert s.quantity == pytest.approx(200.0)


def test_twap_slicing_single_slice():
    router = SmartOrderRouter(
        venues=[make_venue_liquidity("A", ask=100.10, ask_size=10000)]
    )
    order = make_buy_order(quantity=100)
    slices = router.twap_slices(order, num_slices=1, interval_seconds=60)
    assert len(slices) == 1
    assert slices[0].quantity == pytest.approx(100.0)


def test_twap_slicing_zero_slices_raises():
    router = SmartOrderRouter(
        venues=[make_venue_liquidity("A", ask=100.10, ask_size=10000)]
    )
    order = make_buy_order(quantity=100)
    with pytest.raises(ValueError, match="num_slices must be positive"):
        router.twap_slices(order, num_slices=0, interval_seconds=60)


# ── VWAP slicing ─────────────────────────────────────────────────────────


def test_vwap_slicing_proportional_to_liquidity():
    router = SmartOrderRouter(
        venues=[
            make_venue_liquidity("A", ask=100.10, ask_size=1000),
            make_venue_liquidity("B", ask=100.15, ask_size=3000),
        ]
    )
    order = make_buy_order(quantity=800)
    slices = router.vwap_slices(order)
    assert len(slices) == 2
    # B has 3x the liquidity of A, so B should get 3x the quantity
    slice_a = next(s for s in slices if s.venue_name == "A")
    slice_b = next(s for s in slices if s.venue_name == "B")
    assert slice_b.quantity == pytest.approx(3.0 * slice_a.quantity)


def test_vwap_slicing_single_venue():
    router = SmartOrderRouter(
        venues=[make_venue_liquidity("A", ask=100.10, ask_size=1000)]
    )
    order = make_buy_order(quantity=500)
    slices = router.vwap_slices(order)
    assert len(slices) == 1
    assert slices[0].quantity == pytest.approx(500.0)


def test_vwap_slicing_no_venues_raises():
    router = SmartOrderRouter()
    order = make_buy_order()
    with pytest.raises(ValueError, match="No venues"):
        router.vwap_slices(order)


# ── End-to-end routing ───────────────────────────────────────────────────


def test_route_order_end_to_end():
    router = SmartOrderRouter(
        venues=[
            make_venue_liquidity("A", ask=100.10, ask_size=500, latency_ms=2.0),
            make_venue_liquidity("B", ask=100.05, ask_size=500, latency_ms=5.0),
        ]
    )
    order = make_buy_order(quantity=200)
    plan = router.route_order(order)
    assert isinstance(plan, ExecutionPlan)
    assert plan.total_quantity == 200.0
    assert len(plan.slices) >= 1


def test_route_order_sell_side():
    router = SmartOrderRouter(
        venues=[
            make_venue_liquidity("A", bid=99.90, bid_size=500),
            make_venue_liquidity("B", bid=99.95, bid_size=500),
        ]
    )
    order = make_sell_order(quantity=200)
    plan = router.route_order(order)
    assert isinstance(plan, ExecutionPlan)
    assert plan.total_quantity == 200.0


def test_route_order_with_allowed_venues():
    router = SmartOrderRouter(
        venues=[
            make_venue_liquidity("A", ask=100.10, ask_size=500),
            make_venue_liquidity("B", ask=100.05, ask_size=500),
            make_venue_liquidity("C", ask=100.00, ask_size=500),
        ]
    )
    order = make_buy_order(quantity=100)
    plan = router.route_order(order, allowed_venues=["A", "B"])
    for s in plan.slices:
        assert s.venue_name in ("A", "B")


# ── Scoring weights ──────────────────────────────────────────────────────


def test_custom_price_weight():
    router = SmartOrderRouter(
        venues=[
            make_venue_liquidity("A", ask=100.10, ask_size=500, latency_ms=5.0),
            make_venue_liquidity("B", ask=100.15, ask_size=500, latency_ms=1.0),
        ],
        price_weight=10.0,
    )
    order = make_buy_order()
    decision = router.select_venue(order)
    # With high price weight, A wins despite higher latency
    assert decision.venue_name == "A"


def test_custom_latency_weight():
    router = SmartOrderRouter(
        venues=[
            make_venue_liquidity("A", ask=100.10, ask_size=500, latency_ms=5.0),
            make_venue_liquidity("B", ask=100.15, ask_size=500, latency_ms=1.0),
        ],
        latency_weight=10.0,
    )
    order = make_buy_order()
    decision = router.select_venue(order)
    # With high latency weight, B wins despite worse price
    assert decision.venue_name == "B"


def test_custom_liquidity_weight():
    router = SmartOrderRouter(
        venues=[
            make_venue_liquidity("A", ask=100.10, ask_size=100),
            make_venue_liquidity("B", ask=100.10, ask_size=1000),
        ],
        liquidity_weight=10.0,
    )
    order = make_buy_order()
    decision = router.select_venue(order)
    # With high liquidity weight, B wins due to deeper book
    assert decision.venue_name == "B"


def test_custom_fee_weight():
    router = SmartOrderRouter(
        venues=[
            make_venue_liquidity("A", ask=100.10, ask_size=500, fee_bps=10.0),
            make_venue_liquidity("B", ask=100.10, ask_size=500, fee_bps=2.0),
        ],
        fee_weight=10.0,
    )
    order = make_buy_order()
    decision = router.select_venue(order)
    # With high fee weight, B wins due to lower fees
    assert decision.venue_name == "B"


# ── Edge cases ───────────────────────────────────────────────────────────


def test_route_large_order_across_venues():
    router = SmartOrderRouter(
        venues=[
            make_venue_liquidity("A", ask=100.10, ask_size=10000),
            make_venue_liquidity("B", ask=100.05, ask_size=5000),
        ]
    )
    order = make_buy_order(quantity=12000)
    plan = router.create_execution_plan(order)
    total = sum(s.quantity for s in plan.slices)
    assert total == pytest.approx(12000.0)


def test_route_with_min_liquidity_filter():
    router = SmartOrderRouter(
        venues=[
            make_venue_liquidity("A", ask=100.10, ask_size=100),
            make_venue_liquidity("B", ask=100.20, ask_size=1000),
        ]
    )
    order = make_buy_order(quantity=50)
    decision = router.select_venue(order, min_liquidity=500)
    assert decision.venue_name == "B"


def test_execution_plan_preserves_order_info():
    router = SmartOrderRouter(
        venues=[make_venue_liquidity("A", symbol="TSLA", ask=100.10, ask_size=1000)]
    )
    order = make_buy_order(symbol="TSLA", quantity=50)
    plan = router.create_execution_plan(order)
    assert plan.order == order


def test_multiple_orders_sequential_routing():
    router = SmartOrderRouter(
        venues=[
            make_venue_liquidity("A", ask=100.10, ask_size=5000),
            make_venue_liquidity("B", ask=100.05, ask_size=5000),
        ]
    )
    orders = [make_buy_order(quantity=q) for q in [100, 200, 300]]
    plans = [router.route_order(o) for o in orders]
    assert all(isinstance(p, ExecutionPlan) for p in plans)
    assert [p.total_quantity for p in plans] == [100.0, 200.0, 300.0]
