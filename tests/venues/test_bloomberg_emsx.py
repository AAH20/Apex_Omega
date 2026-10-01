"""Unit tests for Bloomberg EMSX adapter: order entry, execution reports, position management."""
from __future__ import annotations

import pytest

from venues.bloomberg_emsx import (
    EMSXConnectionError,
    EMSXOrderRejectedError,
    EMSXPosition,
    EMSXSession,
    EMSXSide,
    EMSXOrder,
    EMSXOrderStatus,
    EMSXOrderType,
    EMSXTimeInForce,
    BloombergEMSXAdapter,
)


def _make_session() -> EMSXSession:
    return EMSXSession(
        host="emsx.bloomberg.com",
        port=8094,
        account="TESTACCT",
        user="testuser",
        uuid="test-uuid-1234",
    )


def _make_adapter() -> BloombergEMSXAdapter:
    return BloombergEMSXAdapter(_make_session())


class TestEMSXSession:
    def test_session_creation(self) -> None:
        session = _make_session()
        assert session.host == "emsx.bloomberg.com"
        assert session.port == 8094
        assert session.account == "TESTACCT"
        assert session.user == "testuser"
        assert session.uuid == "test-uuid-1234"

    def test_session_default_port(self) -> None:
        session = EMSXSession(
            host="localhost",
            account="ACC",
            user="user",
            uuid="uuid",
        )
        assert session.port == 8094

    def test_session_is_not_connected_initially(self) -> None:
        session = _make_session()
        assert not session.is_connected

    def test_session_connect_sets_connected(self) -> None:
        session = _make_session()
        session.connect()
        assert session.is_connected

    def test_session_disconnect_clears_connected(self) -> None:
        session = _make_session()
        session.connect()
        session.disconnect()
        assert not session.is_connected

    def test_session_double_connect_is_noop(self) -> None:
        session = _make_session()
        session.connect()
        session.connect()
        assert session.is_connected

    def test_session_disconnect_when_not_connected_is_noop(self) -> None:
        session = _make_session()
        session.disconnect()
        assert not session.is_connected

    def test_session_context_manager(self) -> None:
        session = _make_session()
        with session as s:
            assert s.is_connected
        assert not session.is_connected


class TestEMSXOrder:
    def test_order_creation(self) -> None:
        order = EMSXOrder(
            symbol="EURUSD",
            side=EMSXSide.BUY,
            quantity=1_000_000,
            order_type=EMSXOrderType.LIMIT,
            price=1.0850,
            time_in_force=EMSXTimeInForce.DAY,
        )
        assert order.symbol == "EURUSD"
        assert order.side == EMSXSide.BUY
        assert order.quantity == 1_000_000
        assert order.order_type == EMSXOrderType.LIMIT
        assert order.price == 1.0850
        assert order.time_in_force == EMSXTimeInForce.DAY
        assert order.status == EMSXOrderStatus.PENDING_NEW
        assert order.filled_quantity == 0
        assert order.avg_fill_price == 0.0
        assert order.order_id is not None
        assert len(order.order_id) > 0

    def test_order_unique_ids(self) -> None:
        order1 = EMSXOrder(
            symbol="EURUSD",
            side=EMSXSide.BUY,
            quantity=100,
            order_type=EMSXOrderType.MARKET,
        )
        order2 = EMSXOrder(
            symbol="EURUSD",
            side=EMSXSide.BUY,
            quantity=100,
            order_type=EMSXOrderType.MARKET,
        )
        assert order1.order_id != order2.order_id

    def test_order_with_custom_id(self) -> None:
        order = EMSXOrder(
            symbol="EURUSD",
            side=EMSXSide.BUY,
            quantity=100,
            order_type=EMSXOrderType.MARKET,
            order_id="MY-ID-001",
        )
        assert order.order_id == "MY-ID-001"

    def test_order_market_has_no_price(self) -> None:
        order = EMSXOrder(
            symbol="EURUSD",
            side=EMSXSide.BUY,
            quantity=100,
            order_type=EMSXOrderType.MARKET,
        )
        assert order.price == 0.0

    def test_order_limit_requires_price(self) -> None:
        order = EMSXOrder(
            symbol="EURUSD",
            side=EMSXSide.BUY,
            quantity=100,
            order_type=EMSXOrderType.LIMIT,
            price=1.0850,
        )
        assert order.price == 1.0850


class TestEMSXPosition:
    def test_position_creation(self) -> None:
        position = EMSXPosition(
            symbol="EURUSD",
            quantity=1_000_000,
            avg_price=1.0850,
        )
        assert position.symbol == "EURUSD"
        assert position.quantity == 1_000_000
        assert position.avg_price == 1.0850
        assert position.unrealized_pnl == 0.0

    def test_position_unrealized_pnl(self) -> None:
        position = EMSXPosition(
            symbol="EURUSD",
            quantity=1_000_000,
            avg_price=1.0850,
            unrealized_pnl=500.0,
        )
        assert position.unrealized_pnl == 500.0

    def test_position_short_quantity(self) -> None:
        position = EMSXPosition(
            symbol="EURUSD",
            quantity=-500_000,
            avg_price=1.0900,
        )
        assert position.quantity == -500_000

    def test_position_zero_quantity(self) -> None:
        position = EMSXPosition(
            symbol="EURUSD",
            quantity=0,
            avg_price=0.0,
        )
        assert position.quantity == 0


class TestBloombergEMSXAdapterConnection:
    def test_initial_state(self) -> None:
        adapter = _make_adapter()
        assert not adapter.is_connected
        assert adapter.session is not None

    def test_connect(self) -> None:
        adapter = _make_adapter()
        adapter.connect()
        assert adapter.is_connected

    def test_disconnect(self) -> None:
        adapter = _make_adapter()
        adapter.connect()
        adapter.disconnect()
        assert not adapter.is_connected

    def test_double_connect_is_noop(self) -> None:
        adapter = _make_adapter()
        adapter.connect()
        adapter.connect()
        assert adapter.is_connected

    def test_disconnect_when_not_connected_is_noop(self) -> None:
        adapter = _make_adapter()
        adapter.disconnect()
        assert not adapter.is_connected

    def test_context_manager(self) -> None:
        adapter = _make_adapter()
        with adapter as a:
            assert a.is_connected
        assert not adapter.is_connected

    def test_connect_raises_on_invalid_host(self) -> None:
        session = EMSXSession(
            host="",
            port=8094,
            account="ACC",
            user="user",
            uuid="uuid",
        )
        adapter = BloombergEMSXAdapter(session)
        with pytest.raises(EMSXConnectionError):
            adapter.connect()


class TestBloombergEMSXAdapterOrderEntry:
    def test_submit_market_order(self) -> None:
        adapter = _make_adapter()
        adapter.connect()
        order = adapter.submit_order(
            symbol="EURUSD",
            side=EMSXSide.BUY,
            quantity=1_000_000,
            order_type=EMSXOrderType.MARKET,
        )
        assert order.symbol == "EURUSD"
        assert order.side == EMSXSide.BUY
        assert order.quantity == 1_000_000
        assert order.order_type == EMSXOrderType.MARKET
        assert order.status == EMSXOrderStatus.PENDING_NEW

    def test_submit_limit_order(self) -> None:
        adapter = _make_adapter()
        adapter.connect()
        order = adapter.submit_order(
            symbol="GBPUSD",
            side=EMSXSide.SELL,
            quantity=500_000,
            order_type=EMSXOrderType.LIMIT,
            price=1.2650,
        )
        assert order.symbol == "GBPUSD"
        assert order.side == EMSXSide.SELL
        assert order.price == 1.2650
        assert order.status == EMSXOrderStatus.PENDING_NEW

    def test_submit_order_not_connected_raises(self) -> None:
        adapter = _make_adapter()
        with pytest.raises(EMSXConnectionError):
            adapter.submit_order(
                symbol="EURUSD",
                side=EMSXSide.BUY,
                quantity=100,
                order_type=EMSXOrderType.MARKET,
            )

    def test_submit_order_with_custom_id(self) -> None:
        adapter = _make_adapter()
        adapter.connect()
        order = adapter.submit_order(
            symbol="EURUSD",
            side=EMSXSide.BUY,
            quantity=100,
            order_type=EMSXOrderType.MARKET,
            order_id="CUSTOM-001",
        )
        assert order.order_id == "CUSTOM-001"

    def test_cancel_order(self) -> None:
        adapter = _make_adapter()
        adapter.connect()
        order = adapter.submit_order(
            symbol="EURUSD",
            side=EMSXSide.BUY,
            quantity=100,
            order_type=EMSXOrderType.LIMIT,
            price=1.0850,
        )
        result = adapter.cancel_order(order.order_id)
        assert result is True
        assert order.status == EMSXOrderStatus.PENDING_CANCEL

    def test_cancel_nonexistent_order_returns_false(self) -> None:
        adapter = _make_adapter()
        adapter.connect()
        result = adapter.cancel_order("nonexistent-id")
        assert result is False

    def test_cancel_order_not_connected_raises(self) -> None:
        adapter = _make_adapter()
        with pytest.raises(EMSXConnectionError):
            adapter.cancel_order("some-id")

    def test_replace_order(self) -> None:
        adapter = _make_adapter()
        adapter.connect()
        order = adapter.submit_order(
            symbol="EURUSD",
            side=EMSXSide.BUY,
            quantity=100,
            order_type=EMSXOrderType.LIMIT,
            price=1.0850,
        )
        new_order = adapter.replace_order(
            order.order_id,
            new_quantity=200,
            new_price=1.0900,
        )
        assert new_order.order_id != order.order_id
        assert new_order.quantity == 200
        assert new_order.price == 1.0900

    def test_replace_nonexistent_order_raises(self) -> None:
        adapter = _make_adapter()
        adapter.connect()
        with pytest.raises(EMSXOrderRejectedError):
            adapter.replace_order("nonexistent", new_quantity=100)


class TestBloombergEMSXAdapterExecutionReports:
    def test_on_execution_report_new(self) -> None:
        adapter = _make_adapter()
        adapter.connect()
        order = adapter.submit_order(
            symbol="EURUSD",
            side=EMSXSide.BUY,
            quantity=1_000_000,
            order_type=EMSXOrderType.MARKET,
        )
        adapter._on_execution_report(
            order_id=order.order_id,
            exec_type="NEW",
            status=EMSXOrderStatus.NEW,
            filled_quantity=0,
            avg_fill_price=0.0,
        )
        assert order.status == EMSXOrderStatus.NEW

    def test_on_execution_report_partial_fill(self) -> None:
        adapter = _make_adapter()
        adapter.connect()
        order = adapter.submit_order(
            symbol="EURUSD",
            side=EMSXSide.BUY,
            quantity=1_000_000,
            order_type=EMSXOrderType.LIMIT,
            price=1.0850,
        )
        adapter._on_execution_report(
            order_id=order.order_id,
            exec_type="PARTIAL_FILL",
            status=EMSXOrderStatus.PARTIALLY_FILLED,
            filled_quantity=400_000,
            avg_fill_price=1.0848,
        )
        assert order.status == EMSXOrderStatus.PARTIALLY_FILLED
        assert order.filled_quantity == 400_000
        assert order.avg_fill_price == 1.0848

    def test_on_execution_report_fill(self) -> None:
        adapter = _make_adapter()
        adapter.connect()
        order = adapter.submit_order(
            symbol="EURUSD",
            side=EMSXSide.BUY,
            quantity=1_000_000,
            order_type=EMSXOrderType.LIMIT,
            price=1.0850,
        )
        adapter._on_execution_report(
            order_id=order.order_id,
            exec_type="FILL",
            status=EMSXOrderStatus.FILLED,
            filled_quantity=1_000_000,
            avg_fill_price=1.0849,
        )
        assert order.status == EMSXOrderStatus.FILLED
        assert order.filled_quantity == 1_000_000
        assert order.avg_fill_price == 1.0849

    def test_on_execution_report_cancelled(self) -> None:
        adapter = _make_adapter()
        adapter.connect()
        order = adapter.submit_order(
            symbol="EURUSD",
            side=EMSXSide.BUY,
            quantity=100,
            order_type=EMSXOrderType.LIMIT,
            price=1.0850,
        )
        adapter._on_execution_report(
            order_id=order.order_id,
            exec_type="CANCELLED",
            status=EMSXOrderStatus.CANCELLED,
            filled_quantity=0,
            avg_fill_price=0.0,
        )
        assert order.status == EMSXOrderStatus.CANCELLED

    def test_on_execution_report_rejected(self) -> None:
        adapter = _make_adapter()
        adapter.connect()
        order = adapter.submit_order(
            symbol="EURUSD",
            side=EMSXSide.BUY,
            quantity=100,
            order_type=EMSXOrderType.LIMIT,
            price=1.0850,
        )
        adapter._on_execution_report(
            order_id=order.order_id,
            exec_type="REJECTED",
            status=EMSXOrderStatus.REJECTED,
            filled_quantity=0,
            avg_fill_price=0.0,
        )
        assert order.status == EMSXOrderStatus.REJECTED

    def test_on_execution_report_unknown_order_is_noop(self) -> None:
        adapter = _make_adapter()
        adapter.connect()
        # Should not raise
        adapter._on_execution_report(
            order_id="unknown-id",
            exec_type="FILL",
            status=EMSXOrderStatus.FILLED,
            filled_quantity=100,
            avg_fill_price=1.0,
        )

    def test_multiple_partial_fills_accumulate(self) -> None:
        adapter = _make_adapter()
        adapter.connect()
        order = adapter.submit_order(
            symbol="EURUSD",
            side=EMSXSide.BUY,
            quantity=1_000_000,
            order_type=EMSXOrderType.LIMIT,
            price=1.0850,
        )
        adapter._on_execution_report(
            order_id=order.order_id,
            exec_type="PARTIAL_FILL",
            status=EMSXOrderStatus.PARTIALLY_FILLED,
            filled_quantity=300_000,
            avg_fill_price=1.0848,
        )
        adapter._on_execution_report(
            order_id=order.order_id,
            exec_type="PARTIAL_FILL",
            status=EMSXOrderStatus.PARTIALLY_FILLED,
            filled_quantity=600_000,
            avg_fill_price=1.0850,
        )
        assert order.filled_quantity == 600_000
        # Weighted average: (300k*1.0848 + 300k*1.0850) / 600k
        expected_avg = (300_000 * 1.0848 + 300_000 * 1.0850) / 600_000
        assert abs(order.avg_fill_price - expected_avg) < 1e-10


class TestBloombergEMSXAdapterPositionManagement:
    def test_update_position_on_fill(self) -> None:
        adapter = _make_adapter()
        adapter.connect()
        order = adapter.submit_order(
            symbol="EURUSD",
            side=EMSXSide.BUY,
            quantity=1_000_000,
            order_type=EMSXOrderType.MARKET,
        )
        adapter._on_execution_report(
            order_id=order.order_id,
            exec_type="FILL",
            status=EMSXOrderStatus.FILLED,
            filled_quantity=1_000_000,
            avg_fill_price=1.0850,
        )
        positions = adapter.get_positions()
        assert len(positions) == 1
        assert positions[0].symbol == "EURUSD"
        assert positions[0].quantity == 1_000_000
        assert positions[0].avg_price == 1.0850

    def test_update_position_on_sell(self) -> None:
        adapter = _make_adapter()
        adapter.connect()
        # Buy first
        buy_order = adapter.submit_order(
            symbol="EURUSD",
            side=EMSXSide.BUY,
            quantity=1_000_000,
            order_type=EMSXOrderType.MARKET,
        )
        adapter._on_execution_report(
            order_id=buy_order.order_id,
            exec_type="FILL",
            status=EMSXOrderStatus.FILLED,
            filled_quantity=1_000_000,
            avg_fill_price=1.0850,
        )
        # Sell
        sell_order = adapter.submit_order(
            symbol="EURUSD",
            side=EMSXSide.SELL,
            quantity=500_000,
            order_type=EMSXOrderType.MARKET,
        )
        adapter._on_execution_report(
            order_id=sell_order.order_id,
            exec_type="FILL",
            status=EMSXOrderStatus.FILLED,
            filled_quantity=500_000,
            avg_fill_price=1.0860,
        )
        positions = adapter.get_positions()
        assert len(positions) == 1
        assert positions[0].quantity == 500_000

    def test_position_flips_on_oversell(self) -> None:
        adapter = _make_adapter()
        adapter.connect()
        # Buy 1M
        buy_order = adapter.submit_order(
            symbol="EURUSD",
            side=EMSXSide.BUY,
            quantity=1_000_000,
            order_type=EMSXOrderType.MARKET,
        )
        adapter._on_execution_report(
            order_id=buy_order.order_id,
            exec_type="FILL",
            status=EMSXOrderStatus.FILLED,
            filled_quantity=1_000_000,
            avg_fill_price=1.0850,
        )
        # Sell 1.5M — flips to short
        sell_order = adapter.submit_order(
            symbol="EURUSD",
            side=EMSXSide.SELL,
            quantity=1_500_000,
            order_type=EMSXOrderType.MARKET,
        )
        adapter._on_execution_report(
            order_id=sell_order.order_id,
            exec_type="FILL",
            status=EMSXOrderStatus.FILLED,
            filled_quantity=1_500_000,
            avg_fill_price=1.0860,
        )
        positions = adapter.get_positions()
        assert len(positions) == 1
        assert positions[0].quantity == -500_000

    def test_get_position_for_symbol(self) -> None:
        adapter = _make_adapter()
        adapter.connect()
        order = adapter.submit_order(
            symbol="EURUSD",
            side=EMSXSide.BUY,
            quantity=1_000_000,
            order_type=EMSXOrderType.MARKET,
        )
        adapter._on_execution_report(
            order_id=order.order_id,
            exec_type="FILL",
            status=EMSXOrderStatus.FILLED,
            filled_quantity=1_000_000,
            avg_fill_price=1.0850,
        )
        position = adapter.get_position("EURUSD")
        assert position is not None
        assert position.symbol == "EURUSD"
        assert position.quantity == 1_000_000

    def test_get_position_for_unknown_symbol_returns_none(self) -> None:
        adapter = _make_adapter()
        adapter.connect()
        position = adapter.get_position("UNKNOWN")
        assert position is None

    def test_get_positions_empty_initially(self) -> None:
        adapter = _make_adapter()
        adapter.connect()
        positions = adapter.get_positions()
        assert positions == []

    def test_multiple_symbol_positions(self) -> None:
        adapter = _make_adapter()
        adapter.connect()
        # Buy EURUSD
        order1 = adapter.submit_order(
            symbol="EURUSD",
            side=EMSXSide.BUY,
            quantity=1_000_000,
            order_type=EMSXOrderType.MARKET,
        )
        adapter._on_execution_report(
            order_id=order1.order_id,
            exec_type="FILL",
            status=EMSXOrderStatus.FILLED,
            filled_quantity=1_000_000,
            avg_fill_price=1.0850,
        )
        # Buy GBPUSD
        order2 = adapter.submit_order(
            symbol="GBPUSD",
            side=EMSXSide.BUY,
            quantity=500_000,
            order_type=EMSXOrderType.MARKET,
        )
        adapter._on_execution_report(
            order_id=order2.order_id,
            exec_type="FILL",
            status=EMSXOrderStatus.FILLED,
            filled_quantity=500_000,
            avg_fill_price=1.2650,
        )
        positions = adapter.get_positions()
        assert len(positions) == 2
        symbols = {p.symbol for p in positions}
        assert symbols == {"EURUSD", "GBPUSD"}

    def test_partial_fill_updates_position(self) -> None:
        adapter = _make_adapter()
        adapter.connect()
        order = adapter.submit_order(
            symbol="EURUSD",
            side=EMSXSide.BUY,
            quantity=1_000_000,
            order_type=EMSXOrderType.LIMIT,
            price=1.0850,
        )
        adapter._on_execution_report(
            order_id=order.order_id,
            exec_type="PARTIAL_FILL",
            status=EMSXOrderStatus.PARTIALLY_FILLED,
            filled_quantity=400_000,
            avg_fill_price=1.0848,
        )
        position = adapter.get_position("EURUSD")
        assert position is not None
        assert position.quantity == 400_000
        assert position.avg_price == 1.0848

    def test_position_avg_price_weighted(self) -> None:
        adapter = _make_adapter()
        adapter.connect()
        # First buy 500k @ 1.0850
        order1 = adapter.submit_order(
            symbol="EURUSD",
            side=EMSXSide.BUY,
            quantity=500_000,
            order_type=EMSXOrderType.MARKET,
        )
        adapter._on_execution_report(
            order_id=order1.order_id,
            exec_type="FILL",
            status=EMSXOrderStatus.FILLED,
            filled_quantity=500_000,
            avg_fill_price=1.0850,
        )
        # Second buy 500k @ 1.0860
        order2 = adapter.submit_order(
            symbol="EURUSD",
            side=EMSXSide.BUY,
            quantity=500_000,
            order_type=EMSXOrderType.MARKET,
        )
        adapter._on_execution_report(
            order_id=order2.order_id,
            exec_type="FILL",
            status=EMSXOrderStatus.FILLED,
            filled_quantity=500_000,
            avg_fill_price=1.0860,
        )
        position = adapter.get_position("EURUSD")
        assert position is not None
        assert position.quantity == 1_000_000
        expected_avg = (500_000 * 1.0850 + 500_000 * 1.0860) / 1_000_000
        assert abs(position.avg_price - expected_avg) < 1e-10


class TestBloombergEMSXAdapterOrderTracking:
    def test_get_order(self) -> None:
        adapter = _make_adapter()
        adapter.connect()
        order = adapter.submit_order(
            symbol="EURUSD",
            side=EMSXSide.BUY,
            quantity=100,
            order_type=EMSXOrderType.MARKET,
        )
        retrieved = adapter.get_order(order.order_id)
        assert retrieved is not None
        assert retrieved.order_id == order.order_id

    def test_get_order_unknown_returns_none(self) -> None:
        adapter = _make_adapter()
        adapter.connect()
        result = adapter.get_order("unknown-id")
        assert result is None

    def test_get_all_orders(self) -> None:
        adapter = _make_adapter()
        adapter.connect()
        order1 = adapter.submit_order(
            symbol="EURUSD",
            side=EMSXSide.BUY,
            quantity=100,
            order_type=EMSXOrderType.MARKET,
        )
        order2 = adapter.submit_order(
            symbol="GBPUSD",
            side=EMSXSide.SELL,
            quantity=200,
            order_type=EMSXOrderType.LIMIT,
            price=1.2650,
        )
        orders = adapter.get_all_orders()
        assert len(orders) == 2
        order_ids = {o.order_id for o in orders}
        assert order1.order_id in order_ids
        assert order2.order_id in order_ids

    def test_get_orders_by_status(self) -> None:
        adapter = _make_adapter()
        adapter.connect()
        order1 = adapter.submit_order(
            symbol="EURUSD",
            side=EMSXSide.BUY,
            quantity=100,
            order_type=EMSXOrderType.MARKET,
        )
        order2 = adapter.submit_order(
            symbol="GBPUSD",
            side=EMSXSide.SELL,
            quantity=200,
            order_type=EMSXOrderType.LIMIT,
            price=1.2650,
        )
        # Fill order1
        adapter._on_execution_report(
            order_id=order1.order_id,
            exec_type="FILL",
            status=EMSXOrderStatus.FILLED,
            filled_quantity=100,
            avg_fill_price=1.0850,
        )
        filled_orders = adapter.get_orders_by_status(EMSXOrderStatus.FILLED)
        assert len(filled_orders) == 1
        assert filled_orders[0].order_id == order1.order_id

        pending_orders = adapter.get_orders_by_status(EMSXOrderStatus.PENDING_NEW)
        assert len(pending_orders) == 1
        assert pending_orders[0].order_id == order2.order_id


class TestBloombergEMSXAdapterMarketData:
    def test_subscribe_market_data(self) -> None:
        adapter = _make_adapter()
        adapter.connect()
        adapter.subscribe_market_data(["EURUSD", "GBPUSD"])
        assert "EURUSD" in adapter.subscribed_symbols
        assert "GBPUSD" in adapter.subscribed_symbols

    def test_unsubscribe_market_data(self) -> None:
        adapter = _make_adapter()
        adapter.connect()
        adapter.subscribe_market_data(["EURUSD", "GBPUSD"])
        adapter.unsubscribe_market_data(["EURUSD"])
        assert "EURUSD" not in adapter.subscribed_symbols
        assert "GBPUSD" in adapter.subscribed_symbols

    def test_subscribe_not_connected_raises(self) -> None:
        adapter = _make_adapter()
        with pytest.raises(EMSXConnectionError):
            adapter.subscribe_market_data(["EURUSD"])

    def test_on_market_data_tick(self) -> None:
        adapter = _make_adapter()
        adapter.connect()
        adapter.subscribe_market_data(["EURUSD"])
        tick = adapter._on_market_data_tick(
            symbol="EURUSD",
            bid=1.0848,
            ask=1.0852,
            bid_size=1_000_000,
            ask_size=2_000_000,
        )
        assert tick.symbol == "EURUSD"
        assert tick.bid == 1.0848
        assert tick.ask == 1.0852
        assert tick.bid_size == 1_000_000
        assert tick.ask_size == 2_000_000


class TestBloombergEMSXAdapterErrorHandling:
    def test_connection_error_on_send_when_disconnected(self) -> None:
        adapter = _make_adapter()
        with pytest.raises(EMSXConnectionError):
            adapter._send_message({"type": "test"})

    def test_order_rejected_error(self) -> None:
        err = EMSXOrderRejectedError("Order rejected: insufficient margin")
        assert "insufficient margin" in str(err)

    def test_connection_error(self) -> None:
        err = EMSXConnectionError("Connection refused")
        assert "Connection refused" in str(err)


class TestBloombergEMSXAdapterMetrics:
    def test_metrics_initial(self) -> None:
        adapter = _make_adapter()
        metrics = adapter.metrics
        assert metrics.orders_submitted == 0
        assert metrics.orders_filled == 0
        assert metrics.orders_cancelled == 0
        assert metrics.errors == 0

    def test_metrics_orders_submitted(self) -> None:
        adapter = _make_adapter()
        adapter.connect()
        adapter.submit_order(
            symbol="EURUSD",
            side=EMSXSide.BUY,
            quantity=100,
            order_type=EMSXOrderType.MARKET,
        )
        assert adapter.metrics.orders_submitted == 1

    def test_metrics_orders_filled(self) -> None:
        adapter = _make_adapter()
        adapter.connect()
        order = adapter.submit_order(
            symbol="EURUSD",
            side=EMSXSide.BUY,
            quantity=100,
            order_type=EMSXOrderType.MARKET,
        )
        adapter._on_execution_report(
            order_id=order.order_id,
            exec_type="FILL",
            status=EMSXOrderStatus.FILLED,
            filled_quantity=100,
            avg_fill_price=1.0850,
        )
        assert adapter.metrics.orders_filled == 1

    def test_metrics_orders_cancelled(self) -> None:
        adapter = _make_adapter()
        adapter.connect()
        order = adapter.submit_order(
            symbol="EURUSD",
            side=EMSXSide.BUY,
            quantity=100,
            order_type=EMSXOrderType.LIMIT,
            price=1.0850,
        )
        adapter.cancel_order(order.order_id)
        assert adapter.metrics.orders_cancelled == 1


class TestBloombergEMSXAdapterTimeInForce:
    def test_submit_with_time_in_force(self) -> None:
        adapter = _make_adapter()
        adapter.connect()
        order = adapter.submit_order(
            symbol="EURUSD",
            side=EMSXSide.BUY,
            quantity=100,
            order_type=EMSXOrderType.LIMIT,
            price=1.0850,
            time_in_force=EMSXTimeInForce.IOC,
        )
        assert order.time_in_force == EMSXTimeInForce.IOC

    def test_default_time_in_force_is_day(self) -> None:
        adapter = _make_adapter()
        adapter.connect()
        order = adapter.submit_order(
            symbol="EURUSD",
            side=EMSXSide.BUY,
            quantity=100,
            order_type=EMSXOrderType.LIMIT,
            price=1.0850,
        )
        assert order.time_in_force == EMSXTimeInForce.DAY


class TestBloombergEMSXAdapterIntegration:
    def test_full_lifecycle_buy_fill(self) -> None:
        adapter = _make_adapter()
        adapter.connect()
        # Submit
        order = adapter.submit_order(
            symbol="EURUSD",
            side=EMSXSide.BUY,
            quantity=1_000_000,
            order_type=EMSXOrderType.LIMIT,
            price=1.0850,
        )
        assert order.status == EMSXOrderStatus.PENDING_NEW
        # New
        adapter._on_execution_report(
            order_id=order.order_id,
            exec_type="NEW",
            status=EMSXOrderStatus.NEW,
            filled_quantity=0,
            avg_fill_price=0.0,
        )
        assert order.status == EMSXOrderStatus.NEW
        # Partial fill
        adapter._on_execution_report(
            order_id=order.order_id,
            exec_type="PARTIAL_FILL",
            status=EMSXOrderStatus.PARTIALLY_FILLED,
            filled_quantity=600_000,
            avg_fill_price=1.0849,
        )
        assert order.status == EMSXOrderStatus.PARTIALLY_FILLED
        assert order.filled_quantity == 600_000
        # Full fill
        adapter._on_execution_report(
            order_id=order.order_id,
            exec_type="FILL",
            status=EMSXOrderStatus.FILLED,
            filled_quantity=1_000_000,
            avg_fill_price=1.08495,
        )
        assert order.status == EMSXOrderStatus.FILLED
        assert order.filled_quantity == 1_000_000
        # Position
        position = adapter.get_position("EURUSD")
        assert position is not None
        assert position.quantity == 1_000_000

    def test_full_lifecycle_cancel(self) -> None:
        adapter = _make_adapter()
        adapter.connect()
        order = adapter.submit_order(
            symbol="EURUSD",
            side=EMSXSide.BUY,
            quantity=1_000_000,
            order_type=EMSXOrderType.LIMIT,
            price=1.0850,
        )
        adapter._on_execution_report(
            order_id=order.order_id,
            exec_type="NEW",
            status=EMSXOrderStatus.NEW,
            filled_quantity=0,
            avg_fill_price=0.0,
        )
        adapter.cancel_order(order.order_id)
        assert order.status == EMSXOrderStatus.PENDING_CANCEL
        adapter._on_execution_report(
            order_id=order.order_id,
            exec_type="CANCELLED",
            status=EMSXOrderStatus.CANCELLED,
            filled_quantity=0,
            avg_fill_price=0.0,
        )
        assert order.status == EMSXOrderStatus.CANCELLED
        # No position from cancelled order
        position = adapter.get_position("EURUSD")
        assert position is None

    def test_full_lifecycle_replace(self) -> None:
        adapter = _make_adapter()
        adapter.connect()
        order = adapter.submit_order(
            symbol="EURUSD",
            side=EMSXSide.BUY,
            quantity=1_000_000,
            order_type=EMSXOrderType.LIMIT,
            price=1.0850,
        )
        adapter._on_execution_report(
            order_id=order.order_id,
            exec_type="NEW",
            status=EMSXOrderStatus.NEW,
            filled_quantity=0,
            avg_fill_price=0.0,
        )
        new_order = adapter.replace_order(
            order.order_id,
            new_quantity=2_000_000,
            new_price=1.0900,
        )
        assert new_order.quantity == 2_000_000
        assert new_order.price == 1.0900
        assert new_order.order_id != order.order_id
        # Old order should be cancelled
        assert order.status == EMSXOrderStatus.CANCELLED
