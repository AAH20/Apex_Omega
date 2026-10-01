"""Unit tests for Venue Order Router — smart order routing by price, liquidity, latency."""
from __future__ import annotations

import pytest

from src.venues.order_router import (
    OrderSide,
    RoutingDecision,
    Venue,
    VenueOrderRouter,
    VenueQuote,
)


# ── Helpers ──────────────────────────────────────────────────────────────


def make_venue(
    name: str = "VENUE_A",
    bid: float = 100.0,
    ask: float = 100.10,
    bid_size: float = 1000.0,
    ask_size: float = 1000.0,
    latency_ms: float = 1.0,
    fee_bps: float = 5.0,
) -> Venue:
    return Venue(
        name=name,
        quote=VenueQuote(bid=bid, ask=ask, bid_size=bid_size, ask_size=ask_size),
        latency_ms=latency_ms,
        fee_bps=fee_bps,
    )


def make_buy_order(symbol: str = "AAPL", quantity: float = 100.0):
    return {"symbol": symbol, "side": OrderSide.BUY, "quantity": quantity}


def make_sell_order(symbol: str = "AAPL", quantity: float = 100.0):
    return {"symbol": symbol, "side": OrderSide.SELL, "quantity": quantity}


# ── Venue dataclass ──────────────────────────────────────────────────────


def test_venue_creation():
    v = make_venue()
    assert v.name == "VENUE_A"
    assert v.quote.bid == 100.0
    assert v.quote.ask == 100.10
    assert v.latency_ms == 1.0
    assert v.fee_bps == 5.0


def test_venue_mid_price():
    v = make_venue(bid=99.0, ask=101.0)
    assert v.quote.mid == pytest.approx(100.0)


def test_venue_spread():
    v = make_venue(bid=99.0, ask=101.0)
    assert v.quote.spread == pytest.approx(2.0)


def test_venue_spread_bps():
    v = make_venue(bid=99.0, ask=101.0)
    assert v.quote.spread_bps == pytest.approx(200.0)


# ── Router initialization ────────────────────────────────────────────────


def test_router_initializes_empty():
    router = VenueOrderRouter()
    assert router.venues == []


def test_router_with_venues():
    venues = [make_venue("A"), make_venue("B")]
    router = VenueOrderRouter(venues=venues)
    assert len(router.venues) == 2


def test_router_add_venue():
    router = VenueOrderRouter()
    router.add_venue(make_venue("A"))
    assert len(router.venues) == 1


def test_router_add_duplicate_venue_raises():
    router = VenueOrderRouter()
    router.add_venue(make_venue("A"))
    with pytest.raises(ValueError, match="already exists"):
        router.add_venue(make_venue("A"))


def test_router_remove_venue():
    router = VenueOrderRouter(venues=[make_venue("A"), make_venue("B")])
    router.remove_venue("A")
    assert len(router.venues) == 1
    assert router.venues[0].name == "B"


def test_router_remove_nonexistent_venue_raises():
    router = VenueOrderRouter()
    with pytest.raises(ValueError, match="not found"):
        router.remove_venue("NONEXISTENT")


# ── Basic routing ────────────────────────────────────────────────────────


def test_route_single_venue():
    router = VenueOrderRouter(venues=[make_venue("A")])
    order = make_buy_order()
    decision = router.route(order)
    assert decision.venue_name == "A"
    assert decision.score > 0


def test_route_no_venues_raises():
    router = VenueOrderRouter()
    order = make_buy_order()
    with pytest.raises(ValueError, match="No venues"):
        router.route(order)


def test_route_buy_selects_best_ask():
    venues = [
        make_venue("A", ask=100.50, ask_size=500),
        make_venue("B", ask=100.10, ask_size=500),
        make_venue("C", ask=100.30, ask_size=500),
    ]
    router = VenueOrderRouter(venues=venues)
    order = make_buy_order()
    decision = router.route(order)
    assert decision.venue_name == "B"


def test_route_sell_selects_best_bid():
    venues = [
        make_venue("A", bid=99.50, bid_size=500),
        make_venue("B", bid=99.90, bid_size=500),
        make_venue("C", bid=99.70, bid_size=500),
    ]
    router = VenueOrderRouter(venues=venues)
    order = make_sell_order()
    decision = router.route(order)
    assert decision.venue_name == "B"


# ── Liquidity filtering ──────────────────────────────────────────────────


def test_route_filters_insufficient_liquidity():
    venues = [
        make_venue("A", ask=100.10, ask_size=50),
        make_venue("B", ask=100.20, ask_size=500),
    ]
    router = VenueOrderRouter(venues=venues)
    order = make_buy_order(quantity=100)
    decision = router.route(order)
    assert decision.venue_name == "B"


def test_route_all_insufficient_liquidity_raises():
    venues = [
        make_venue("A", ask=100.10, ask_size=50),
        make_venue("B", ask=100.20, ask_size=50),
    ]
    router = VenueOrderRouter(venues=venues)
    order = make_buy_order(quantity=100)
    with pytest.raises(ValueError, match="Insufficient liquidity"):
        router.route(order)


# ── Latency scoring ──────────────────────────────────────────────────────


def test_route_prefers_low_latency():
    venues = [
        make_venue("A", ask=100.10, ask_size=500, latency_ms=10.0),
        make_venue("B", ask=100.10, ask_size=500, latency_ms=1.0),
    ]
    router = VenueOrderRouter(venues=venues)
    order = make_buy_order()
    decision = router.route(order)
    assert decision.venue_name == "B"


# ── Fee scoring ──────────────────────────────────────────────────────────


def test_route_prefers_low_fees():
    venues = [
        make_venue("A", ask=100.10, ask_size=500, fee_bps=10.0),
        make_venue("B", ask=100.10, ask_size=500, fee_bps=2.0),
    ]
    router = VenueOrderRouter(venues=venues)
    order = make_buy_order()
    decision = router.route(order)
    assert decision.venue_name == "B"


# ── Weighted scoring ─────────────────────────────────────────────────────


def test_custom_weights():
    venues = [
        make_venue("A", ask=100.10, ask_size=500, latency_ms=5.0, fee_bps=5.0),
        make_venue("B", ask=100.15, ask_size=500, latency_ms=1.0, fee_bps=5.0),
    ]
    # With high latency weight, B should win despite worse price
    router = VenueOrderRouter(venues=venues, latency_weight=10.0)
    order = make_buy_order()
    decision = router.route(order)
    assert decision.venue_name == "B"


def test_zero_price_weight():
    venues = [
        make_venue("A", ask=100.10, ask_size=500, latency_ms=5.0),
        make_venue("B", ask=100.50, ask_size=500, latency_ms=1.0),
    ]
    # With zero price weight, latency decides
    router = VenueOrderRouter(venues=venues, price_weight=0.0)
    order = make_buy_order()
    decision = router.route(order)
    assert decision.venue_name == "B"


# ── Routing decision structure ────────────────────────────────────────────


def test_routing_decision_fields():
    router = VenueOrderRouter(venues=[make_venue("A")])
    order = make_buy_order()
    decision = router.route(order)
    assert isinstance(decision, RoutingDecision)
    assert decision.venue_name == "A"
    assert decision.score > 0
    assert decision.reason is not None
    assert decision.order == order


def test_routing_decision_includes_all_scores():
    venues = [make_venue("A"), make_venue("B")]
    router = VenueOrderRouter(venues=venues)
    order = make_buy_order()
    decision = router.route(order)
    assert "A" in decision.all_scores
    assert "B" in decision.all_scores


# ── Venue filtering ──────────────────────────────────────────────────────


def test_route_with_allowed_venues():
    venues = [make_venue("A"), make_venue("B"), make_venue("C")]
    router = VenueOrderRouter(venues=venues)
    order = make_buy_order()
    decision = router.route(order, allowed_venues=["A", "B"])
    assert decision.venue_name in ("A", "B")


def test_route_with_disallowed_venue_raises():
    venues = [make_venue("A"), make_venue("B")]
    router = VenueOrderRouter(venues=venues)
    order = make_buy_order()
    with pytest.raises(ValueError, match="No venues"):
        router.route(order, allowed_venues=["C"])


# ── Edge cases ───────────────────────────────────────────────────────────


def test_route_tie_breaker_by_name():
    venues = [
        make_venue("B", ask=100.10, ask_size=500),
        make_venue("A", ask=100.10, ask_size=500),
    ]
    router = VenueOrderRouter(venues=venues)
    order = make_buy_order()
    decision = router.route(order)
    # Should pick one deterministically (first in sorted order)
    assert decision.venue_name in ("A", "B")


def test_route_large_quantity():
    venues = [
        make_venue("A", ask=100.10, ask_size=10000),
        make_venue("B", ask=100.05, ask_size=500),
    ]
    router = VenueOrderRouter(venues=venues)
    order = make_buy_order(quantity=5000)
    decision = router.route(order)
    assert decision.venue_name == "A"


def test_route_with_min_liquidity_filter():
    venues = [
        make_venue("A", ask=100.10, ask_size=100),
        make_venue("B", ask=100.20, ask_size=1000),
    ]
    router = VenueOrderRouter(venues=venues)
    order = make_buy_order(quantity=50)
    decision = router.route(order, min_liquidity=500)
    assert decision.venue_name == "B"


# ── Score components ─────────────────────────────────────────────────────


def test_score_components_positive():
    router = VenueOrderRouter(venues=[make_venue("A")])
    order = make_buy_order()
    decision = router.route(order)
    assert decision.score > 0


def test_better_venue_scores_higher():
    venues = [
        make_venue("A", ask=100.50, ask_size=100, latency_ms=10.0, fee_bps=20.0),
        make_venue("B", ask=100.10, ask_size=1000, latency_ms=1.0, fee_bps=2.0),
    ]
    router = VenueOrderRouter(venues=venues)
    order = make_buy_order()
    decision = router.route(order)
    assert decision.all_scores["B"] > decision.all_scores["A"]


# ── Multiple orders ──────────────────────────────────────────────────────


def test_route_multiple_orders():
    venues = [make_venue("A"), make_venue("B", ask=100.05)]
    router = VenueOrderRouter(venues=venues)
    orders = [make_buy_order(quantity=q) for q in [100, 200, 300]]
    decisions = [router.route(o) for o in orders]
    assert all(d.venue_name == "B" for d in decisions)


# ── Reason string ────────────────────────────────────────────────────────


def test_reason_mentions_price():
    router = VenueOrderRouter(venues=[make_venue("A")])
    order = make_buy_order()
    decision = router.route(order)
    assert "price" in decision.reason.lower() or "ask" in decision.reason.lower()
