"""Pre-Trade Risk Engine — sub-2ms risk checks with configurable rules."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class OrderSide(Enum):
    BUY = "buy"
    SELL = "sell"


@dataclass
class RiskCheckResult:
    passed: bool
    violations: list[str] = field(default_factory=list)
    latency_us: float = 0.0


@dataclass
class RiskRules:
    max_order_value: float = 1_000_000.0
    max_position_size: float = 100_000.0
    max_daily_loss: float = 50_000.0
    max_order_quantity: float = 10_000.0
    max_price_deviation_pct: float = 5.0
    allowed_symbols: set[str] | None = None
    max_orders_per_second: int = 100
    max_orders_per_minute: int = 1000
    kill_switch: bool = False


class PreTradeRiskEngine:
    """Pre-trade risk engine performing sub-2ms checks."""

    def __init__(self, rules: RiskRules | None = None):
        self.rules = rules or RiskRules()
        self._order_timestamps: list[float] = []
        self._daily_pnl: float = 0.0
        self._positions: dict[str, float] = {}

    def check_order(
        self,
        symbol: str,
        side: OrderSide,
        quantity: float,
        price: float,
        reference_price: float | None = None,
    ) -> RiskCheckResult:
        start = time.perf_counter_ns()
        violations: list[str] = []

        if self.rules.kill_switch:
            violations.append("KILL_SWITCH_ACTIVE")

        if self.rules.allowed_symbols is not None and symbol not in self.rules.allowed_symbols:
            violations.append(f"SYMBOL_NOT_ALLOWED:{symbol}")

        if quantity <= 0:
            violations.append("INVALID_QUANTITY")

        if price <= 0:
            violations.append("INVALID_PRICE")

        order_value = quantity * price
        if order_value > self.rules.max_order_value:
            violations.append(f"ORDER_VALUE_EXCEEDS_MAX:{order_value:.2f}>{self.rules.max_order_value:.2f}")

        if quantity > self.rules.max_order_quantity:
            violations.append(f"QUANTITY_EXCEEDS_MAX:{quantity}>{self.rules.max_order_quantity}")

        current_position = self._positions.get(symbol, 0.0)
        new_position = current_position + quantity if side == OrderSide.BUY else current_position - quantity
        if abs(new_position) > self.rules.max_position_size:
            violations.append(f"POSITION_EXCEEDS_MAX:{abs(new_position):.2f}>{self.rules.max_position_size:.2f}")

        if reference_price is not None and reference_price > 0:
            deviation_pct = abs(price - reference_price) / reference_price * 100
            if deviation_pct > self.rules.max_price_deviation_pct:
                violations.append(f"PRICE_DEVIATION_EXCEEDS_MAX:{deviation_pct:.2f}%>{self.rules.max_price_deviation_pct}%")

        if self._daily_pnl < -self.rules.max_daily_loss:
            violations.append(f"DAILY_LOSS_EXCEEDS_MAX:{self._daily_pnl:.2f}>{-self.rules.max_daily_loss:.2f}")

        now = time.perf_counter()
        self._order_timestamps = [t for t in self._order_timestamps if now - t < 60.0]
        self._order_timestamps.append(now)

        orders_last_second = sum(1 for t in self._order_timestamps if now - t < 1.0)
        if orders_last_second > self.rules.max_orders_per_second:
            violations.append(f"ORDERS_PER_SECOND_EXCEEDS_MAX:{orders_last_second}>{self.rules.max_orders_per_second}")

        if len(self._order_timestamps) > self.rules.max_orders_per_minute:
            violations.append(f"ORDERS_PER_MINUTE_EXCEEDS_MAX:{len(self._order_timestamps)}>{self.rules.max_orders_per_minute}")

        elapsed_us = (time.perf_counter_ns() - start) / 1000.0
        return RiskCheckResult(passed=len(violations) == 0, violations=violations, latency_us=elapsed_us)

    def update_position(self, symbol: str, quantity: float) -> None:
        self._positions[symbol] = self._positions.get(symbol, 0.0) + quantity

    def update_daily_pnl(self, pnl: float) -> None:
        self._daily_pnl += pnl

    def reset_daily(self) -> None:
        self._daily_pnl = 0.0
        self._order_timestamps.clear()

    def trigger_kill_switch(self) -> None:
        self.rules.kill_switch = True

    def clear_kill_switch(self) -> None:
        self.rules.kill_switch = False
