"""Unit tests for Bloomberg B-PIPE adapter."""
import pytest
from unittest.mock import MagicMock, patch, call
from datetime import datetime, timezone

from src.venues.bloomberg_bpipe import (
    BloombergBpipeAdapter,
    BpipeSession,
    BpipeOrder,
    BpipeMarketDataSubscription,
    BpipeConnectionError,
    BpipeAuthenticationError,
    BpipeOrderError,
    BpipeMarketDataError,
    OrderSide,
    OrderType,
    OrderStatus,
    SessionState,
)


# ── Session Management ──────────────────────────────────────────────────


class TestBpipeSession:
    """Tests for B-PIPE session lifecycle."""

    def test_session_initializes_disconnected(self):
        session = BpipeSession(host="localhost", port=8194)
        assert session.state == SessionState.DISCONNECTED
        assert session.host == "localhost"
        assert session.port == 8194

    def test_session_connect_success(self):
        session = BpipeSession(host="bpipe.example.com", port=8194)
        with patch.object(session, "_open_connection") as mock_open:
            mock_open.return_value = MagicMock()
            session.connect()
            assert session.state == SessionState.CONNECTED
            mock_open.assert_called_once()

    def test_session_connect_failure_raises(self):
        session = BpipeSession(host="bpipe.example.com", port=8194)
        with patch.object(session, "_open_connection") as mock_open:
            mock_open.side_effect = ConnectionRefusedError("refused")
            with pytest.raises(BpipeConnectionError):
                session.connect()
            assert session.state == SessionState.DISCONNECTED

    def test_session_authenticate_success(self):
        session = BpipeSession(host="bpipe.example.com", port=8194)
        session.state = SessionState.CONNECTED
        with patch.object(session, "_send_auth") as mock_auth:
            mock_auth.return_value = {"status": "SUCCESS"}
            session.authenticate("user", "pass")
            assert session.state == SessionState.AUTHENTICATED

    def test_session_authenticate_failure_raises(self):
        session = BpipeSession(host="bpipe.example.com", port=8194)
        session.state = SessionState.CONNECTED
        with patch.object(session, "_send_auth") as mock_auth:
            mock_auth.return_value = {"status": "FAILURE", "reason": "bad creds"}
            with pytest.raises(BpipeAuthenticationError):
                session.authenticate("user", "wrong")
            assert session.state == SessionState.CONNECTED

    def test_session_disconnect(self):
        session = BpipeSession(host="bpipe.example.com", port=8194)
        session.state = SessionState.AUTHENTICATED
        with patch.object(session, "_close_connection") as mock_close:
            session.disconnect()
            assert session.state == SessionState.DISCONNECTED
            mock_close.assert_called_once()

    def test_session_heartbeat(self):
        session = BpipeSession(host="bpipe.example.com", port=8194)
        session.state = SessionState.AUTHENTICATED
        with patch.object(session, "_send_heartbeat") as mock_hb:
            mock_hb.return_value = True
            assert session.send_heartbeat() is True
            mock_hb.assert_called_once()

    def test_session_heartbeat_not_authenticated(self):
        session = BpipeSession(host="bpipe.example.com", port=8194)
        session.state = SessionState.CONNECTED
        with pytest.raises(BpipeConnectionError):
            session.send_heartbeat()

    def test_session_is_authenticated(self):
        session = BpipeSession(host="bpipe.example.com", port=8194)
        assert not session.is_authenticated()
        session.state = SessionState.AUTHENTICATED
        assert session.is_authenticated()

    def test_session_context_manager(self):
        session = BpipeSession(host="bpipe.example.com", port=8194)
        with patch.object(session, "connect") as mock_connect, \
             patch.object(session, "disconnect") as mock_disconnect:
            with session as s:
                assert s is session
                mock_connect.assert_called_once()
            mock_disconnect.assert_called_once()


# ── Order Routing ───────────────────────────────────────────────────────


class TestBpipeOrder:
    """Tests for B-PIPE order model."""

    def test_order_creation(self):
        order = BpipeOrder(
            symbol="AAPL US Equity",
            side=OrderSide.BUY,
            quantity=100,
            order_type=OrderType.MARKET,
        )
        assert order.symbol == "AAPL US Equity"
        assert order.side == OrderSide.BUY
        assert order.quantity == 100
        assert order.order_type == OrderType.MARKET
        assert order.status == OrderStatus.PENDING

    def test_order_with_limit_price(self):
        order = BpipeOrder(
            symbol="MSFT US Equity",
            side=OrderSide.SELL,
            quantity=50,
            order_type=OrderType.LIMIT,
            limit_price=250.0,
        )
        assert order.limit_price == 250.0

    def test_order_with_stop_price(self):
        order = BpipeOrder(
            symbol="GOOG US Equity",
            side=OrderSide.SELL,
            quantity=10,
            order_type=OrderType.STOP,
            stop_price=140.0,
        )
        assert order.stop_price == 140.0

    def test_order_with_tif(self):
        order = BpipeOrder(
            symbol="TSLA US Equity",
            side=OrderSide.BUY,
            quantity=5,
            order_type=OrderType.MARKET,
            time_in_force="DAY",
        )
        assert order.time_in_force == "DAY"

    def test_order_with_account(self):
        order = BpipeOrder(
            symbol="AMZN US Equity",
            side=OrderSide.BUY,
            quantity=1,
            order_type=OrderType.MARKET,
            account="ACCT001",
        )
        assert order.account == "ACCT001"

    def test_order_with_order_id(self):
        order = BpipeOrder(
            symbol="NVDA US Equity",
            side=OrderSide.BUY,
            quantity=10,
            order_type=OrderType.MARKET,
            order_id="ORD-12345",
        )
        assert order.order_id == "ORD-12345"

    def test_order_status_transitions(self):
        order = BpipeOrder(
            symbol="META US Equity",
            side=OrderSide.BUY,
            quantity=20,
            order_type=OrderType.MARKET,
        )
        assert order.status == OrderStatus.PENDING
        order.status = OrderStatus.SUBMITTED
        assert order.status == OrderStatus.SUBMITTED
        order.status = OrderStatus.FILLED
        assert order.status == OrderStatus.FILLED

    def test_order_to_dict(self):
        order = BpipeOrder(
            symbol="AAPL US Equity",
            side=OrderSide.BUY,
            quantity=100,
            order_type=OrderType.LIMIT,
            limit_price=150.0,
            account="ACCT001",
            order_id="ORD-001",
        )
        d = order.to_dict()
        assert d["symbol"] == "AAPL US Equity"
        assert d["side"] == "BUY"
        assert d["quantity"] == 100
        assert d["order_type"] == "LIMIT"
        assert d["limit_price"] == 150.0
        assert d["account"] == "ACCT001"
        assert d["order_id"] == "ORD-001"


class TestBpipeOrderRouting:
    """Tests for order routing through the adapter."""

    @pytest.fixture
    def adapter(self):
        return BloombergBpipeAdapter(
            host="bpipe.example.com",
            port=8194,
            username="testuser",
            password="testpass",
        )

    @pytest.fixture
    def authenticated_adapter(self, adapter):
        adapter.session.state = SessionState.AUTHENTICATED
        return adapter

    def test_submit_order_success(self, authenticated_adapter):
        order = BpipeOrder(
            symbol="AAPL US Equity",
            side=OrderSide.BUY,
            quantity=100,
            order_type=OrderType.MARKET,
        )
        with patch.object(authenticated_adapter, "_route_order") as mock_route:
            mock_route.return_value = {"order_id": "BPIPE-001", "status": "ACCEPTED"}
            result = authenticated_adapter.submit_order(order)
            assert result["order_id"] == "BPIPE-001"
            assert result["status"] == "ACCEPTED"
            mock_route.assert_called_once_with(order)

    def test_submit_order_not_authenticated(self, adapter):
        order = BpipeOrder(
            symbol="AAPL US Equity",
            side=OrderSide.BUY,
            quantity=100,
            order_type=OrderType.MARKET,
        )
        with pytest.raises(BpipeConnectionError):
            adapter.submit_order(order)

    def test_cancel_order_success(self, authenticated_adapter):
        with patch.object(authenticated_adapter, "_cancel_order") as mock_cancel:
            mock_cancel.return_value = {"status": "CANCELLED"}
            result = authenticated_adapter.cancel_order("BPIPE-001")
            assert result["status"] == "CANCELLED"
            mock_cancel.assert_called_once_with("BPIPE-001")

    def test_cancel_order_not_authenticated(self, adapter):
        with pytest.raises(BpipeConnectionError):
            adapter.cancel_order("BPIPE-001")

    def test_amend_order_success(self, authenticated_adapter):
        with patch.object(authenticated_adapter, "_amend_order") as mock_amend:
            mock_amend.return_value = {"status": "AMENDED"}
            result = authenticated_adapter.amend_order("BPIPE-001", quantity=200)
            assert result["status"] == "AMENDED"
            mock_amend.assert_called_once_with("BPIPE-001", quantity=200)

    def test_amend_order_not_authenticated(self, adapter):
        with pytest.raises(BpipeConnectionError):
            adapter.amend_order("BPIPE-001", quantity=200)

    def test_get_order_status_success(self, authenticated_adapter):
        with patch.object(authenticated_adapter, "_get_order_status") as mock_status:
            mock_status.return_value = {"status": "FILLED", "filled_qty": 100}
            result = authenticated_adapter.get_order_status("BPIPE-001")
            assert result["status"] == "FILLED"
            assert result["filled_qty"] == 100

    def test_get_order_status_not_authenticated(self, adapter):
        with pytest.raises(BpipeConnectionError):
            adapter.get_order_status("BPIPE-001")

    def test_submit_order_invalid_quantity(self, authenticated_adapter):
        order = BpipeOrder(
            symbol="AAPL US Equity",
            side=OrderSide.BUY,
            quantity=-100,
            order_type=OrderType.MARKET,
        )
        with pytest.raises(BpipeOrderError):
            authenticated_adapter.submit_order(order)

    def test_submit_order_invalid_symbol(self, authenticated_adapter):
        order = BpipeOrder(
            symbol="",
            side=OrderSide.BUY,
            quantity=100,
            order_type=OrderType.MARKET,
        )
        with pytest.raises(BpipeOrderError):
            authenticated_adapter.submit_order(order)


# ── Market Data Subscription ────────────────────────────────────────────


class TestBpipeMarketDataSubscription:
    """Tests for market data subscription model."""

    def test_subscription_creation(self):
        sub = BpipeMarketDataSubscription(
            symbol="AAPL US Equity",
            fields=["BID", "ASK", "LAST_PRICE"],
        )
        assert sub.symbol == "AAPL US Equity"
        assert sub.fields == ["BID", "ASK", "LAST_PRICE"]
        assert sub.active is False

    def test_subscription_with_options(self):
        sub = BpipeMarketDataSubscription(
            symbol="MSFT US Equity",
            fields=["BID", "ASK"],
            interval=1000,
        )
        assert sub.interval == 1000

    def test_subscription_to_dict(self):
        sub = BpipeMarketDataSubscription(
            symbol="GOOG US Equity",
            fields=["LAST_PRICE", "VOLUME"],
        )
        d = sub.to_dict()
        assert d["symbol"] == "GOOG US Equity"
        assert d["fields"] == ["LAST_PRICE", "VOLUME"]


class TestBpipeMarketData:
    """Tests for market data subscription through the adapter."""

    @pytest.fixture
    def adapter(self):
        return BloombergBpipeAdapter(
            host="bpipe.example.com",
            port=8194,
            username="testuser",
            password="testpass",
        )

    @pytest.fixture
    def authenticated_adapter(self, adapter):
        adapter.session.state = SessionState.AUTHENTICATED
        return adapter

    def test_subscribe_market_data_success(self, authenticated_adapter):
        with patch.object(authenticated_adapter, "_subscribe") as mock_sub:
            mock_sub.return_value = {"subscription_id": "SUB-001", "status": "ACTIVE"}
            result = authenticated_adapter.subscribe_market_data(
                "AAPL US Equity", ["BID", "ASK", "LAST_PRICE"]
            )
            assert result["subscription_id"] == "SUB-001"
            assert result["status"] == "ACTIVE"

    def test_subscribe_market_data_not_authenticated(self, adapter):
        with pytest.raises(BpipeConnectionError):
            adapter.subscribe_market_data("AAPL US Equity", ["BID", "ASK"])

    def test_unsubscribe_market_data_success(self, authenticated_adapter):
        with patch.object(authenticated_adapter, "_unsubscribe") as mock_unsub:
            mock_unsub.return_value = {"status": "INACTIVE"}
            result = authenticated_adapter.unsubscribe_market_data("SUB-001")
            assert result["status"] == "INACTIVE"
            mock_unsub.assert_called_once_with("SUB-001")

    def test_unsubscribe_market_data_not_authenticated(self, adapter):
        with pytest.raises(BpipeConnectionError):
            adapter.unsubscribe_market_data("SUB-001")

    def test_get_market_data_success(self, authenticated_adapter):
        with patch.object(authenticated_adapter, "_get_market_data") as mock_get:
            mock_get.return_value = {
                "symbol": "AAPL US Equity",
                "BID": 150.0,
                "ASK": 150.05,
                "LAST_PRICE": 150.02,
            }
            result = authenticated_adapter.get_market_data("AAPL US Equity")
            assert result["symbol"] == "AAPL US Equity"
            assert result["BID"] == 150.0
            assert result["ASK"] == 150.05

    def test_get_market_data_not_authenticated(self, adapter):
        with pytest.raises(BpipeConnectionError):
            adapter.get_market_data("AAPL US Equity")

    def test_subscribe_invalid_symbol(self, authenticated_adapter):
        with pytest.raises(BpipeMarketDataError):
            authenticated_adapter.subscribe_market_data("", ["BID"])

    def test_subscribe_invalid_fields(self, authenticated_adapter):
        with pytest.raises(BpipeMarketDataError):
            authenticated_adapter.subscribe_market_data("AAPL US Equity", [])

    def test_market_data_callback_registration(self, authenticated_adapter):
        callback = MagicMock()
        authenticated_adapter.register_market_data_callback("AAPL US Equity", callback)
        assert "AAPL US Equity" in authenticated_adapter._market_data_callbacks
        assert callback in authenticated_adapter._market_data_callbacks["AAPL US Equity"]

    def test_market_data_callback_invocation(self, authenticated_adapter):
        callback = MagicMock()
        authenticated_adapter.register_market_data_callback("AAPL US Equity", callback)
        data = {"BID": 150.0, "ASK": 150.05, "LAST_PRICE": 150.02}
        authenticated_adapter._notify_market_data("AAPL US Equity", data)
        callback.assert_called_once_with("AAPL US Equity", data)

    def test_market_data_callback_unregister(self, authenticated_adapter):
        callback = MagicMock()
        authenticated_adapter.register_market_data_callback("AAPL US Equity", callback)
        authenticated_adapter.unregister_market_data_callback("AAPL US Equity", callback)
        assert callback not in authenticated_adapter._market_data_callbacks.get("AAPL US Equity", [])


# ── Adapter Integration ─────────────────────────────────────────────────


class TestBloombergBpipeAdapter:
    """Tests for the main adapter class."""

    def test_adapter_initialization(self):
        adapter = BloombergBpipeAdapter(
            host="bpipe.example.com",
            port=8194,
            username="user",
            password="pass",
        )
        assert adapter.host == "bpipe.example.com"
        assert adapter.port == 8194
        assert adapter.username == "user"
        assert adapter.session is not None
        assert adapter.session.state == SessionState.DISCONNECTED

    def test_adapter_connect(self):
        adapter = BloombergBpipeAdapter(
            host="bpipe.example.com",
            port=8194,
            username="user",
            password="pass",
        )
        with patch.object(adapter.session, "connect") as mock_connect, \
             patch.object(adapter.session, "authenticate") as mock_auth:
            adapter.connect()
            mock_connect.assert_called_once()
            mock_auth.assert_called_once_with("user", "pass")

    def test_adapter_disconnect(self):
        adapter = BloombergBpipeAdapter(
            host="bpipe.example.com",
            port=8194,
            username="user",
            password="pass",
        )
        adapter.session.state = SessionState.AUTHENTICATED
        with patch.object(adapter.session, "disconnect") as mock_disconnect:
            adapter.disconnect()
            mock_disconnect.assert_called_once()

    def test_adapter_is_connected(self):
        adapter = BloombergBpipeAdapter(
            host="bpipe.example.com",
            port=8194,
            username="user",
            password="pass",
        )
        assert not adapter.is_connected()
        adapter.session.state = SessionState.AUTHENTICATED
        assert adapter.is_connected()

    def test_adapter_context_manager(self):
        adapter = BloombergBpipeAdapter(
            host="bpipe.example.com",
            port=8194,
            username="user",
            password="pass",
        )
        with patch.object(adapter, "connect") as mock_connect, \
             patch.object(adapter, "disconnect") as mock_disconnect:
            with adapter as a:
                assert a is adapter
                mock_connect.assert_called_once()
            mock_disconnect.assert_called_once()

    def test_adapter_session_property(self):
        adapter = BloombergBpipeAdapter(
            host="bpipe.example.com",
            port=8194,
            username="user",
            password="pass",
        )
        assert isinstance(adapter.session, BpipeSession)

    def test_adapter_market_data_callbacks_init(self):
        adapter = BloombergBpipeAdapter(
            host="bpipe.example.com",
            port=8194,
            username="user",
            password="pass",
        )
        assert adapter._market_data_callbacks == {}

    def test_adapter_order_history(self):
        adapter = BloombergBpipeAdapter(
            host="bpipe.example.com",
            port=8194,
            username="user",
            password="pass",
        )
        assert adapter.order_history == []
        order = BpipeOrder(
            symbol="AAPL US Equity",
            side=OrderSide.BUY,
            quantity=100,
            order_type=OrderType.MARKET,
        )
        adapter.order_history.append(order)
        assert len(adapter.order_history) == 1
        assert adapter.order_history[0].symbol == "AAPL US Equity"

    def test_adapter_active_subscriptions(self):
        adapter = BloombergBpipeAdapter(
            host="bpipe.example.com",
            port=8194,
            username="user",
            password="pass",
        )
        assert adapter.active_subscriptions == {}
        sub = BpipeMarketDataSubscription(
            symbol="AAPL US Equity",
            fields=["BID", "ASK"],
        )
        adapter.active_subscriptions["SUB-001"] = sub
        assert len(adapter.active_subscriptions) == 1
        assert adapter.active_subscriptions["SUB-001"].symbol == "AAPL US Equity"


# ── Error Handling ──────────────────────────────────────────────────────


class TestBpipeErrors:
    """Tests for B-PIPE error types."""

    def test_connection_error(self):
        err = BpipeConnectionError("connection failed")
        assert str(err) == "connection failed"

    def test_authentication_error(self):
        err = BpipeAuthenticationError("auth failed")
        assert str(err) == "auth failed"

    def test_order_error(self):
        err = BpipeOrderError("order failed")
        assert str(err) == "order failed"

    def test_market_data_error(self):
        err = BpipeMarketDataError("market data failed")
        assert str(err) == "market data failed"

    def test_connection_error_is_exception(self):
        assert issubclass(BpipeConnectionError, Exception)

    def test_authentication_error_is_exception(self):
        assert issubclass(BpipeAuthenticationError, Exception)

    def test_order_error_is_exception(self):
        assert issubclass(BpipeOrderError, Exception)

    def test_market_data_error_is_exception(self):
        assert issubclass(BpipeMarketDataError, Exception)


# ── Enums ───────────────────────────────────────────────────────────────


class TestEnums:
    """Tests for B-PIPE enum types."""

    def test_order_side_values(self):
        assert OrderSide.BUY.value == "BUY"
        assert OrderSide.SELL.value == "SELL"

    def test_order_type_values(self):
        assert OrderType.MARKET.value == "MARKET"
        assert OrderType.LIMIT.value == "LIMIT"
        assert OrderType.STOP.value == "STOP"
        assert OrderType.STOP_LIMIT.value == "STOP_LIMIT"

    def test_order_status_values(self):
        assert OrderStatus.PENDING.value == "PENDING"
        assert OrderStatus.SUBMITTED.value == "SUBMITTED"
        assert OrderStatus.FILLED.value == "FILLED"
        assert OrderStatus.CANCELLED.value == "CANCELLED"
        assert OrderStatus.REJECTED.value == "REJECTED"

    def test_session_state_values(self):
        assert SessionState.DISCONNECTED.value == "DISCONNECTED"
        assert SessionState.CONNECTED.value == "CONNECTED"
        assert SessionState.AUTHENTICATED.value == "AUTHENTICATED"
