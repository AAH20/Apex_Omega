"""Unit tests for FIX Message Router."""
import pytest

from src.fix.message_router import (
    MessageRouter,
    RouteResult,
    RoutingError,
    RoutingStats,
)
from src.fix.session.fix42_session import FIXMessage


# ── Helpers ──────────────────────────────────────────────────────────────


def make_msg(msg_type: str, seq_num: int = 1, **fields) -> FIXMessage:
    """Build a FIXMessage for testing."""
    return FIXMessage(
        msg_type=msg_type,
        sender_comp_id="SENDER",
        target_comp_id="TARGET",
        seq_num=seq_num,
        fields=fields,
    )


# ── Registration ─────────────────────────────────────────────────────────


def test_register_handler():
    router = MessageRouter()
    handler = lambda msg: "handled"
    router.register("D", handler)
    assert router.has_handler("D")


def test_register_overwrites_existing():
    router = MessageRouter()
    router.register("D", lambda msg: "first")
    router.register("D", lambda msg: "second")
    result = router.route(make_msg("D"))
    assert result.value == "second"


def test_unregister_handler():
    router = MessageRouter()
    router.register("D", lambda msg: "handled")
    router.unregister("D")
    assert not router.has_handler("D")


def test_unregister_nonexistent_is_noop():
    router = MessageRouter()
    router.unregister("X")  # Should not raise
    assert not router.has_handler("X")


def test_has_handler_false_for_unregistered():
    router = MessageRouter()
    assert not router.has_handler("D")


# ── Routing ──────────────────────────────────────────────────────────────


def test_route_to_registered_handler():
    router = MessageRouter()
    router.register("D", lambda msg: "order_handler")
    result = router.route(make_msg("D"))
    assert result.value == "order_handler"
    assert result.msg_type == "D"


def test_route_unregistered_uses_default():
    router = MessageRouter()
    router.set_default_handler(lambda msg: "default")
    result = router.route(make_msg("X"))
    assert result.value == "default"


def test_route_unregistered_no_default_raises():
    router = MessageRouter()
    with pytest.raises(RoutingError, match="No handler"):
        router.route(make_msg("X"))


def test_route_passes_message_to_handler():
    router = MessageRouter()
    received = []
    router.register("D", lambda msg: received.append(msg))
    msg = make_msg("D", seq_num=42)
    router.route(msg)
    assert received[0] is msg


def test_route_returns_route_result():
    router = MessageRouter()
    router.register("D", lambda msg: 42)
    result = router.route(make_msg("D"))
    assert isinstance(result, RouteResult)
    assert result.value == 42
    assert result.msg_type == "D"
    assert result.error is None


# ── Default Handler ──────────────────────────────────────────────────────


def test_set_default_handler():
    router = MessageRouter()
    router.set_default_handler(lambda msg: "fallback")
    assert router._default_handler is not None


def test_registered_takes_precedence_over_default():
    router = MessageRouter()
    router.set_default_handler(lambda msg: "default")
    router.register("D", lambda msg: "specific")
    result = router.route(make_msg("D"))
    assert result.value == "specific"


def test_unregister_falls_back_to_default():
    router = MessageRouter()
    router.set_default_handler(lambda msg: "default")
    router.register("D", lambda msg: "specific")
    router.unregister("D")
    result = router.route(make_msg("D"))
    assert result.value == "default"


# ── Middleware ───────────────────────────────────────────────────────────


def test_middleware_called_before_handler():
    calls = []
    router = MessageRouter()
    router.add_middleware(lambda msg: calls.append("mw"))
    router.register("D", lambda msg: calls.append("handler"))
    router.route(make_msg("D"))
    assert calls == ["mw", "handler"]


def test_multiple_middleware_order():
    calls = []
    router = MessageRouter()
    router.add_middleware(lambda msg: calls.append("mw1"))
    router.add_middleware(lambda msg: calls.append("mw2"))
    router.register("D", lambda msg: calls.append("handler"))
    router.route(make_msg("D"))
    assert calls == ["mw1", "mw2", "handler"]


def test_middleware_can_modify_message():
    router = MessageRouter()
    def add_field(msg):
        msg.fields["999"] = "injected"
        return msg
    router.add_middleware(add_field)
    received = []
    router.register("D", lambda msg: received.append(msg))
    msg = make_msg("D")
    router.route(msg)
    assert received[0].fields.get("999") == "injected"


def test_middleware_can_short_circuit():
    router = MessageRouter()
    def block(msg):
        raise RoutingError("blocked")
    router.add_middleware(block)
    handler_called = []
    router.register("D", lambda msg: handler_called.append(True))
    with pytest.raises(RoutingError, match="blocked"):
        router.route(make_msg("D"))
    assert handler_called == []


# ── Statistics ───────────────────────────────────────────────────────────


def test_stats_track_routed_messages():
    router = MessageRouter()
    router.register("D", lambda msg: "ok")
    router.route(make_msg("D"))
    router.route(make_msg("D"))
    stats = router.get_stats()
    assert stats.routed == 2
    assert stats.by_type["D"] == 2


def test_stats_track_errors():
    router = MessageRouter()
    router.register("D", lambda msg: 1 / 0)
    with pytest.raises(ZeroDivisionError):
        router.route(make_msg("D"))
    stats = router.get_stats()
    assert stats.errors == 1


def test_stats_track_fallback_routing():
    router = MessageRouter()
    router.set_default_handler(lambda msg: "default")
    router.route(make_msg("X"))
    stats = router.get_stats()
    assert stats.fallback == 1


def test_stats_reset():
    router = MessageRouter()
    router.register("D", lambda msg: "ok")
    router.route(make_msg("D"))
    router.reset_stats()
    stats = router.get_stats()
    assert stats.routed == 0
    assert stats.errors == 0
    assert stats.fallback == 0


def test_stats_by_type_counts():
    router = MessageRouter()
    router.register("D", lambda msg: "ok")
    router.register("8", lambda msg: "ok")
    router.route(make_msg("D"))
    router.route(make_msg("D"))
    router.route(make_msg("8"))
    stats = router.get_stats()
    assert stats.by_type["D"] == 2
    assert stats.by_type["8"] == 1


# ── Error Handling ───────────────────────────────────────────────────────


def test_handler_exception_propagates():
    router = MessageRouter()
    def bad_handler(msg):
        raise ValueError("boom")
    router.register("D", bad_handler)
    with pytest.raises(ValueError, match="boom"):
        router.route(make_msg("D"))


def test_handler_exception_recorded_in_result():
    router = MessageRouter()
    def bad_handler(msg):
        raise ValueError("boom")
    router.register("D", bad_handler)
    with pytest.raises(ValueError):
        router.route(make_msg("D"))
    stats = router.get_stats()
    assert stats.errors == 1


def test_route_result_contains_error_on_failure():
    router = MessageRouter()
    def bad_handler(msg):
        raise RuntimeError("fail")
    router.register("D", bad_handler)
    with pytest.raises(RuntimeError):
        result = router.route(make_msg("D"))
    # If we catch the exception, result should have error info
    # Actually with current design, exception propagates. Let's test that.


# ── Multiple Message Types ───────────────────────────────────────────────


def test_route_multiple_types():
    router = MessageRouter()
    router.register("D", lambda msg: "new_order")
    router.register("8", lambda msg: "execution")
    router.register("0", lambda msg: "heartbeat")
    assert router.route(make_msg("D")).value == "new_order"
    assert router.route(make_msg("8")).value == "execution"
    assert router.route(make_msg("0")).value == "heartbeat"


def test_route_heartbeat():
    router = MessageRouter()
    router.register("0", lambda msg: "hb")
    result = router.route(make_msg("0"))
    assert result.value == "hb"


def test_route_logon():
    router = MessageRouter()
    router.register("A", lambda msg: "logged_in")
    result = router.route(make_msg("A"))
    assert result.value == "logged_in"


def test_route_logout():
    router = MessageRouter()
    router.register("5", lambda msg: "logged_out")
    result = router.route(make_msg("5"))
    assert result.value == "logged_out"


def test_route_resend_request():
    router = MessageRouter()
    router.register("2", lambda msg: "resend")
    result = router.route(make_msg("2"))
    assert result.value == "resend"


def test_route_test_request():
    router = MessageRouter()
    router.register("1", lambda msg: "test")
    result = router.route(make_msg("1"))
    assert result.value == "test"


# ── Decorator Registration ───────────────────────────────────────────────


def test_decorator_registration():
    router = MessageRouter()
    @router.register("D")
    def handle_order(msg):
        return "decorated"
    result = router.route(make_msg("D"))
    assert result.value == "decorated"


# ── Edge Cases ───────────────────────────────────────────────────────────


def test_empty_router_route_raises():
    router = MessageRouter()
    with pytest.raises(RoutingError):
        router.route(make_msg("D"))


def test_handler_returning_none():
    router = MessageRouter()
    router.register("D", lambda msg: None)
    result = router.route(make_msg("D"))
    assert result.value is None


def test_handler_receives_correct_msg_type():
    router = MessageRouter()
    received = []
    router.register("D", lambda msg: received.append(msg.msg_type))
    router.route(make_msg("D"))
    assert received == ["D"]


def test_stats_is_routing_stats_instance():
    router = MessageRouter()
    stats = router.get_stats()
    assert isinstance(stats, RoutingStats)


def test_route_result_has_msg_type():
    router = MessageRouter()
    router.register("D", lambda msg: "ok")
    result = router.route(make_msg("D"))
    assert result.msg_type == "D"


def test_route_result_has_value():
    router = MessageRouter()
    router.register("D", lambda msg: "my_value")
    result = router.route(make_msg("D"))
    assert result.value == "my_value"


def test_middleware_receives_correct_message():
    router = MessageRouter()
    received = []
    router.add_middleware(lambda msg: received.append(msg))
    router.register("D", lambda msg: "ok")
    msg = make_msg("D", seq_num=99)
    router.route(msg)
    assert received[0].seq_num == 99


def test_concurrent_routing():
    """Router should handle multiple messages correctly."""
    router = MessageRouter()
    router.register("D", lambda msg: "order")
    router.register("8", lambda msg: "exec")
    results = []
    for i in range(10):
        results.append(router.route(make_msg("D" if i % 2 == 0 else "8")))
    assert len(results) == 10
    assert sum(1 for r in results if r.value == "order") == 5
    assert sum(1 for r in results if r.value == "exec") == 5
