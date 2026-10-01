"""Tests for Pre-Trade Risk Engine."""
import time
import pytest
from src.risk.pre_trade import PreTradeRiskEngine, RiskCheckResult, RiskRules, OrderSide


def test_engine_initializes_with_default_rules():
    engine = PreTradeRiskEngine()
    assert engine is not None
    assert engine.rules is not None


def test_valid_order_passes_all_checks():
    engine = PreTradeRiskEngine()
    result = engine.check_order("AAPL", OrderSide.BUY, 100, 150.0)
    assert result.passed is True
    assert result.violations == []


def test_order_value_exceeds_max():
    rules = RiskRules(max_order_value=10_000.0)
    engine = PreTradeRiskEngine(rules)
    result = engine.check_order("AAPL", OrderSide.BUY, 1000, 100.0)
    assert result.passed is False
    assert any("ORDER_VALUE_EXCEEDS_MAX" in v for v in result.violations)


def test_quantity_exceeds_max():
    rules = RiskRules(max_order_quantity=500.0)
    engine = PreTradeRiskEngine(rules)
    result = engine.check_order("AAPL", OrderSide.BUY, 600, 10.0)
    assert result.passed is False
    assert any("QUANTITY_EXCEEDS_MAX" in v for v in result.violations)


def test_position_size_exceeds_max():
    rules = RiskRules(max_position_size=1000.0)
    engine = PreTradeRiskEngine(rules)
    engine.update_position("AAPL", 900.0)
    result = engine.check_order("AAPL", OrderSide.BUY, 200, 10.0)
    assert result.passed is False
    assert any("POSITION_EXCEEDS_MAX" in v for v in result.violations)


def test_price_deviation_exceeds_max():
    rules = RiskRules(max_price_deviation_pct=2.0)
    engine = PreTradeRiskEngine(rules)
    result = engine.check_order("AAPL", OrderSide.BUY, 10, 110.0, reference_price=100.0)
    assert result.passed is False
    assert any("PRICE_DEVIATION_EXCEEDS_MAX" in v for v in result.violations)


def test_price_deviation_within_limit_passes():
    rules = RiskRules(max_price_deviation_pct=5.0)
    engine = PreTradeRiskEngine(rules)
    result = engine.check_order("AAPL", OrderSide.BUY, 10, 103.0, reference_price=100.0)
    assert result.passed is True


def test_symbol_not_allowed():
    rules = RiskRules(allowed_symbols={"AAPL", "MSFT"})
    engine = PreTradeRiskEngine(rules)
    result = engine.check_order("GOOG", OrderSide.BUY, 10, 100.0)
    assert result.passed is False
    assert any("SYMBOL_NOT_ALLOWED" in v for v in result.violations)


def test_allowed_symbol_passes():
    rules = RiskRules(allowed_symbols={"AAPL", "MSFT"})
    engine = PreTradeRiskEngine(rules)
    result = engine.check_order("AAPL", OrderSide.BUY, 10, 100.0)
    assert result.passed is True


def test_kill_switch_blocks_all_orders():
    engine = PreTradeRiskEngine()
    engine.trigger_kill_switch()
    result = engine.check_order("AAPL", OrderSide.BUY, 1, 1.0)
    assert result.passed is False
    assert any("KILL_SWITCH_ACTIVE" in v for v in result.violations)


def test_kill_switch_can_be_cleared():
    engine = PreTradeRiskEngine()
    engine.trigger_kill_switch()
    engine.clear_kill_switch()
    result = engine.check_order("AAPL", OrderSide.BUY, 1, 1.0)
    assert result.passed is True


def test_invalid_quantity_rejected():
    engine = PreTradeRiskEngine()
    result = engine.check_order("AAPL", OrderSide.BUY, 0, 100.0)
    assert result.passed is False
    assert any("INVALID_QUANTITY" in v for v in result.violations)


def test_invalid_price_rejected():
    engine = PreTradeRiskEngine()
    result = engine.check_order("AAPL", OrderSide.BUY, 10, -5.0)
    assert result.passed is False
    assert any("INVALID_PRICE" in v for v in result.violations)


def test_daily_loss_exceeds_max():
    rules = RiskRules(max_daily_loss=1000.0)
    engine = PreTradeRiskEngine(rules)
    engine.update_daily_pnl(-1500.0)
    result = engine.check_order("AAPL", OrderSide.BUY, 1, 100.0)
    assert result.passed is False
    assert any("DAILY_LOSS_EXCEEDS_MAX" in v for v in result.violations)


def test_daily_loss_within_limit_passes():
    rules = RiskRules(max_daily_loss=1000.0)
    engine = PreTradeRiskEngine(rules)
    engine.update_daily_pnl(-500.0)
    result = engine.check_order("AAPL", OrderSide.BUY, 1, 100.0)
    assert result.passed is True


def test_orders_per_second_limit():
    rules = RiskRules(max_orders_per_second=3)
    engine = PreTradeRiskEngine(rules)
    for _ in range(3):
        engine.check_order("AAPL", OrderSide.BUY, 1, 100.0)
    result = engine.check_order("AAPL", OrderSide.BUY, 1, 100.0)
    assert result.passed is False
    assert any("ORDERS_PER_SECOND_EXCEEDS_MAX" in v for v in result.violations)


def test_orders_per_minute_limit():
    rules = RiskRules(max_orders_per_minute=5, max_orders_per_second=100)
    engine = PreTradeRiskEngine(rules)
    for _ in range(5):
        engine.check_order("AAPL", OrderSide.BUY, 1, 100.0)
    result = engine.check_order("AAPL", OrderSide.BUY, 1, 100.0)
    assert result.passed is False
    assert any("ORDERS_PER_MINUTE_EXCEEDS_MAX" in v for v in result.violations)


def test_sell_order_reduces_position():
    rules = RiskRules(max_position_size=1000.0)
    engine = PreTradeRiskEngine(rules)
    engine.update_position("AAPL", 500.0)
    result = engine.check_order("AAPL", OrderSide.SELL, 200, 100.0)
    assert result.passed is True


def test_multiple_violations_reported():
    rules = RiskRules(max_order_value=100.0, max_order_quantity=5.0)
    engine = PreTradeRiskEngine(rules)
    result = engine.check_order("AAPL", OrderSide.BUY, 100, 50.0)
    assert result.passed is False
    assert len(result.violations) >= 2


def test_latency_under_2ms():
    engine = PreTradeRiskEngine()
    result = engine.check_order("AAPL", OrderSide.BUY, 100, 150.0)
    assert result.latency_us < 2000.0


def test_update_position_accumulates():
    engine = PreTradeRiskEngine()
    engine.update_position("AAPL", 100.0)
    engine.update_position("AAPL", 200.0)
    assert engine._positions["AAPL"] == 300.0


def test_reset_daily_clears_state():
    engine = PreTradeRiskEngine()
    engine.update_daily_pnl(-500.0)
    engine.check_order("AAPL", OrderSide.BUY, 1, 100.0)
    engine.reset_daily()
    assert engine._daily_pnl == 0.0
    assert len(engine._order_timestamps) == 0


def test_custom_rules_override_defaults():
    rules = RiskRules(max_order_value=500.0, max_order_quantity=50.0)
    engine = PreTradeRiskEngine(rules)
    assert engine.rules.max_order_value == 500.0
    assert engine.rules.max_order_quantity == 50.0


def test_no_reference_price_skips_deviation_check():
    engine = PreTradeRiskEngine()
    result = engine.check_order("AAPL", OrderSide.BUY, 10, 9999.0)
    assert result.passed is True


def test_risk_check_result_dataclass():
    result = RiskCheckResult(passed=True, violations=[], latency_us=0.5)
    assert result.passed is True
    assert result.violations == []
    assert result.latency_us == 0.5


def test_order_side_enum():
    assert OrderSide.BUY.value == "buy"
    assert OrderSide.SELL.value == "sell"


def test_engine_with_custom_rules_object():
    rules = RiskRules(
        max_order_value=5000.0,
        max_position_size=500.0,
        max_daily_loss=100.0,
        max_order_quantity=50.0,
        max_price_deviation_pct=1.0,
        allowed_symbols={"TSLA"},
        max_orders_per_second=10,
        max_orders_per_minute=100,
    )
    engine = PreTradeRiskEngine(rules)
    assert engine.rules.max_order_value == 5000.0
    assert engine.rules.allowed_symbols == {"TSLA"}


def test_buy_and_sell_sides_work():
    engine = PreTradeRiskEngine()
    buy_result = engine.check_order("AAPL", OrderSide.BUY, 10, 100.0)
    sell_result = engine.check_order("AAPL", OrderSide.SELL, 5, 100.0)
    assert buy_result.passed is True
    assert sell_result.passed is True


def test_position_check_for_sell_side():
    rules = RiskRules(max_position_size=100.0)
    engine = PreTradeRiskEngine(rules)
    engine.update_position("AAPL", -50.0)
    result = engine.check_order("AAPL", OrderSide.SELL, 60, 100.0)
    assert result.passed is False
    assert any("POSITION_EXCEEDS_MAX" in v for v in result.violations)
