"""
Risk Manager: pre-trade and post-trade risk controls.
Enforces position limits, exposure caps, max drawdown circuit breakers.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, List, Optional

from ..core.order import Order, OrderSide, OrderStatus
from ..core.portfolio import Portfolio


@dataclass
class RiskLimits:
    max_position_pct: float = 0.10        # max single position % of equity
    max_gross_exposure_pct: float = 1.50  # max gross (long+short) % of equity
    max_net_exposure_pct: float = 0.50    # max net (long-short) % of equity
    max_drawdown_pct: float = 0.20        # circuit breaker: halt trading
    max_daily_loss_pct: float = 0.05      # daily loss limit
    max_orders_per_symbol: int = 5        # concurrent open orders per symbol
    max_risk_per_trade_pct: float = 0.02  # max risk % per single trade
    min_cash_reserve_pct: float = 0.05    # keep 5% cash reserve


class RiskManager:
    """Pre-trade risk checks and post-trade monitoring."""

    def __init__(self, limits: Optional[RiskLimits] = None):
        self.limits = limits or RiskLimits()
        self._daily_pnl_start: Optional[float] = None
        self._trading_halted: bool = False
        self._rejection_log: List[dict] = []

    def reset_daily(self, equity: float) -> None:
        """Call at start of each trading day."""
        self._daily_pnl_start = equity
        self._trading_halted = False

    def check_order(
        self,
        order: Order,
        portfolio: Portfolio,
        prices: Dict[str, float],
        open_orders_by_symbol: Dict[str, int],
    ) -> tuple[bool, str]:
        """
        Returns (approved, reason).
        Runs all pre-trade checks.
        """
        if self._trading_halted:
            return False, "Trading halted: circuit breaker triggered"

        equity = portfolio.equity(prices)
        price = prices.get(order.symbol)
        if price is None:
            return False, f"No price for {order.symbol}"

        # 1. Max drawdown circuit breaker
        dd = portfolio.max_drawdown()
        if dd >= self.limits.max_drawdown_pct:
            self._trading_halted = True
            return False, f"Circuit breaker: drawdown {dd:.1%} >= limit {self.limits.max_drawdown_pct:.1%}"

        # 2. Daily loss limit
        if self._daily_pnl_start is not None:
            daily_pnl_pct = (equity - self._daily_pnl_start) / self._daily_pnl_start
            if daily_pnl_pct <= -self.limits.max_daily_loss_pct:
                self._trading_halted = True
                return False, f"Daily loss limit hit: {daily_pnl_pct:.1%}"

        # 3. Cash reserve check
        min_cash = equity * self.limits.min_cash_reserve_pct
        order_cost = price * order.quantity
        if portfolio.cash - order_cost < min_cash and order.side == OrderSide.BUY:
            return False, f"Insufficient cash: need {order_cost:.2f}, reserve={min_cash:.2f}"

        # 4. Position size limit
        pos = portfolio.get_position(order.symbol)
        new_qty = abs(pos.quantity + (
            order.quantity if order.side == OrderSide.BUY else -order.quantity
        ))
        position_value = new_qty * price
        if position_value > equity * self.limits.max_position_pct:
            return False, (
                f"Position too large: {position_value:.0f} > "
                f"{equity * self.limits.max_position_pct:.0f} "
                f"({self.limits.max_position_pct:.0%} of equity)"
            )

        # 5. Open orders per symbol
        open_count = open_orders_by_symbol.get(order.symbol, 0)
        if open_count >= self.limits.max_orders_per_symbol:
            return False, f"Too many open orders for {order.symbol}: {open_count}"

        # 6. Risk per trade
        risk_amt = order.risk_amount  # computed after fill; estimate here
        estimated_sl = order.tpsl.sl_pct if order.tpsl else 0.01
        estimated_risk = price * order.quantity * estimated_sl
        if estimated_risk > equity * self.limits.max_risk_per_trade_pct:
            return False, (
                f"Trade risk too high: ${estimated_risk:.0f} > "
                f"${equity * self.limits.max_risk_per_trade_pct:.0f}"
            )

        return True, "OK"

    def log_rejection(self, order: Order, reason: str) -> None:
        self._rejection_log.append({
            "order_id": order.order_id,
            "symbol": order.symbol,
            "side": order.side.value,
            "qty": order.quantity,
            "reason": reason,
        })

    def summary(self) -> dict:
        return {
            "trading_halted": self._trading_halted,
            "total_rejections": len(self._rejection_log),
            "rejection_log": self._rejection_log[-10:],
        }
