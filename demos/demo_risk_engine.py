#!/usr/bin/env python3
"""
demo_risk_engine.py — Apex_Omega Risk Engine Demo

Demonstrates pre-trade risk checks including:
- Position limits
- Notional exposure limits
- Order value limits
- Daily loss limits
- Concentration limits

Usage:
    python demo_risk_engine.py
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class RiskCheckResult(Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    WARNING = "WARNING"


@dataclass
class RiskCheck:
    name: str
    result: RiskCheckResult
    message: str
    current_value: float
    limit_value: float


@dataclass
class Position:
    symbol: str
    quantity: int  # positive = long, negative = short
    avg_price: float
    market_price: float

    @property
    def market_value(self) -> float:
        return self.quantity * self.market_price

    @property
    def unrealized_pnl(self) -> float:
        return self.quantity * (self.market_price - self.avg_price)


@dataclass
class Account:
    account_id: str
    cash: float
    positions: dict[str, Position] = field(default_factory=dict)
    daily_pnl: float = 0.0
    total_traded_today: float = 0.0


@dataclass
class RiskLimits:
    max_position_value: float = 1_000_000.0
    max_total_exposure: float = 5_000_000.0
    max_order_value: float = 500_000.0
    max_daily_loss: float = 100_000.0
    max_concentration_pct: float = 0.25  # 25% of total exposure in one symbol
    max_order_quantity: int = 10_000


class RiskEngine:
    """Pre-trade risk engine for Apex_Omega."""

    def __init__(self, limits: RiskLimits):
        self.limits = limits

    def check_order(
        self,
        account: Account,
        symbol: str,
        side: str,  # "BUY" or "SELL"
        quantity: int,
        price: float,
    ) -> list[RiskCheck]:
        """Run all risk checks for a proposed order."""
        checks = []

        # 1. Order value check
        order_value = quantity * price
        checks.append(
            RiskCheck(
                name="Order Value Limit",
                result=RiskCheckResult.PASS if order_value <= self.limits.max_order_value else RiskCheckResult.FAIL,
                message=f"Order value ${order_value:,.2f} {'within' if order_value <= self.limits.max_order_value else 'exceeds'} limit ${self.limits.max_order_value:,.2f}",
                current_value=order_value,
                limit_value=self.limits.max_order_value,
            )
        )

        # 2. Order quantity check
        checks.append(
            RiskCheck(
                name="Order Quantity Limit",
                result=RiskCheckResult.PASS if quantity <= self.limits.max_order_quantity else RiskCheckResult.FAIL,
                message=f"Quantity {quantity:,} {'within' if quantity <= self.limits.max_order_quantity else 'exceeds'} limit {self.limits.max_order_quantity:,}",
                current_value=float(quantity),
                limit_value=float(self.limits.max_order_quantity),
            )
        )

        # 3. Position limit check
        current_pos = account.positions.get(symbol)
        current_qty = current_pos.quantity if current_pos else 0
        new_qty = current_qty + quantity if side == "BUY" else current_qty - quantity
        new_position_value = abs(new_qty * price)
        checks.append(
            RiskCheck(
                name="Position Value Limit",
                result=RiskCheckResult.PASS if new_position_value <= self.limits.max_position_value else RiskCheckResult.FAIL,
                message=f"New position value ${new_position_value:,.2f} {'within' if new_position_value <= self.limits.max_position_value else 'exceeds'} limit ${self.limits.max_position_value:,.2f}",
                current_value=new_position_value,
                limit_value=self.limits.max_position_value,
            )
        )

        # 4. Total exposure check
        total_exposure = sum(abs(p.market_value) for p in account.positions.values())
        # Adjust for the new order
        if current_pos:
            total_exposure -= abs(current_pos.market_value)
        total_exposure += abs(new_qty * price)
        checks.append(
            RiskCheck(
                name="Total Exposure Limit",
                result=RiskCheckResult.PASS if total_exposure <= self.limits.max_total_exposure else RiskCheckResult.FAIL,
                message=f"Total exposure ${total_exposure:,.2f} {'within' if total_exposure <= self.limits.max_total_exposure else 'exceeds'} limit ${self.limits.max_total_exposure:,.2f}",
                current_value=total_exposure,
                limit_value=self.limits.max_total_exposure,
            )
        )

        # 5. Concentration check
        if total_exposure > 0:
            concentration = abs(new_qty * price) / total_exposure
            checks.append(
                RiskCheck(
                    name="Concentration Limit",
                    result=RiskCheckResult.PASS if concentration <= self.limits.max_concentration_pct else RiskCheckResult.FAIL,
                    message=f"Concentration {concentration:.1%} {'within' if concentration <= self.limits.max_concentration_pct else 'exceeds'} limit {self.limits.max_concentration_pct:.1%}",
                    current_value=concentration,
                    limit_value=self.limits.max_concentration_pct,
                )
            )

        # 6. Daily loss check
        checks.append(
            RiskCheck(
                name="Daily Loss Limit",
                result=RiskCheckResult.PASS if account.daily_pnl >= -self.limits.max_daily_loss else RiskCheckResult.FAIL,
                message=f"Daily P&L ${account.daily_pnl:,.2f} {'within' if account.daily_pnl >= -self.limits.max_daily_loss else 'breaches'} loss limit ${self.limits.max_daily_loss:,.2f}",
                current_value=account.daily_pnl,
                limit_value=self.limits.max_daily_loss,
            )
        )

        return checks

    def can_trade(self, checks: list[RiskCheck]) -> bool:
        """Return True if all checks pass."""
        return all(c.result != RiskCheckResult.FAIL for c in checks)


def display_checks(checks: list[RiskCheck]) -> None:
    """Display risk check results."""
    print(f"\n  {'Check':<25} {'Result':<10} {'Current':>15} {'Limit':>15} {'Message'}")
    print(f"  {'-'*25} {'-'*10} {'-'*15} {'-'*15} {'-'*30}")
    for check in checks:
        status_icon = "✓" if check.result == RiskCheckResult.PASS else "✗"
        print(f"  {check.name:<25} {status_icon} {check.result.value:<8} {check.current_value:>15,.2f} {check.limit_value:>15,.2f} {check.message}")


def run_demo() -> None:
    """Run the risk engine demonstration."""
    print("=" * 80)
    print("  Apex_Omega — Risk Engine Demo")
    print("=" * 80)

    # Setup
    limits = RiskLimits(
        max_position_value=1_000_000.0,
        max_total_exposure=5_000_000.0,
        max_order_value=500_000.0,
        max_daily_loss=100_000.0,
        max_concentration_pct=0.25,
        max_order_quantity=10_000,
    )

    account = Account(
        account_id="ACC-001",
        cash=10_000_000.0,
        positions={
            "AAPL": Position("AAPL", 5000, 145.00, 150.00),
            "GOOGL": Position("GOOGL", 3000, 2800.00, 2850.00),
            "MSFT": Position("MSFT", -2000, 310.00, 305.00),
        },
        daily_pnl=-45_000.0,
    )

    engine = RiskEngine(limits)

    # Display account state
    print(f"\n  Account: {account.account_id}")
    print(f"  Cash: ${account.cash:,.2f}")
    print(f"  Daily P&L: ${account.daily_pnl:,.2f}")
    print(f"\n  Positions:")
    print(f"  {'Symbol':<10} {'Qty':>10} {'Avg Price':>12} {'Market':>12} {'Value':>15} {'uPnL':>15}")
    print(f"  {'-'*10} {'-'*10} {'-'*12} {'-'*12} {'-'*15} {'-'*15}")
    for pos in account.positions.values():
        print(f"  {pos.symbol:<10} {pos.quantity:>10,} {pos.avg_price:>12.2f} {pos.market_price:>12.2f} ${pos.market_value:>14,.2f} ${pos.unrealized_pnl:>14,.2f}")

    total_exposure = sum(abs(p.market_value) for p in account.positions.values())
    print(f"\n  Total Exposure: ${total_exposure:,.2f}")

    # Test scenarios
    scenarios = [
        ("Small BUY order (should pass)", "AAPL", "BUY", 100, 150.00),
        ("Large BUY order (position limit)", "AAPL", "BUY", 5000, 150.00),
        ("Large SELL order (exposure limit)", "TSLA", "SELL", 2000, 250.00),
        ("Order exceeding quantity limit", "AAPL", "BUY", 15000, 150.00),
        ("Order exceeding order value limit", "GOOGL", "BUY", 200, 2850.00),
    ]

    for desc, symbol, side, qty, price in scenarios:
        print(f"\n{'='*80}")
        print(f"  Scenario: {desc}")
        print(f"  Order: {side} {qty:,} {symbol} @ ${price:.2f}")
        print(f"{'='*80}")

        checks = engine.check_order(account, symbol, side, qty, price)
        display_checks(checks)

        if engine.can_trade(checks):
            print(f"\n  ✅ ORDER APPROVED")
        else:
            print(f"\n  ❌ ORDER REJECTED")

    # Summary
    print(f"\n{'='*80}")
    print("  Risk Engine Configuration:")
    print(f"{'='*80}")
    print(f"  Max Position Value:    ${limits.max_position_value:>15,.2f}")
    print(f"  Max Total Exposure:    ${limits.max_total_exposure:>15,.2f}")
    print(f"  Max Order Value:       ${limits.max_order_value:>15,.2f}")
    print(f"  Max Daily Loss:        ${limits.max_daily_loss:>15,.2f}")
    print(f"  Max Concentration:     {limits.max_concentration_pct:>15.1%}")
    print(f"  Max Order Quantity:    {limits.max_order_quantity:>15,}")


if __name__ == "__main__":
    run_demo()
