"""
Portfolio tracking: cash, positions, PnL, drawdown.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

from .position import Position
from .order import Order, OrderSide


@dataclass
class EquitySnapshot:
    timestamp: datetime
    cash: float
    unrealized_pnl: float
    realized_pnl: float
    equity: float
    drawdown: float


class Portfolio:
    """Tracks cash, positions, and performance metrics."""

    def __init__(self, initial_capital: float = 1_000_000.0):
        self.initial_capital = initial_capital
        self.cash = initial_capital
        self.positions: Dict[str, Position] = {}
        self.closed_trades: List[Order] = []
        self.equity_curve: List[EquitySnapshot] = []
        self.peak_equity = initial_capital
        self._total_commission = 0.0

    def get_position(self, symbol: str) -> Position:
        if symbol not in self.positions:
            self.positions[symbol] = Position(symbol=symbol)
        return self.positions[symbol]

    def apply_fill(
        self,
        order: Order,
        fill_price: float,
        fill_qty: float,
        commission: float = 0.0,
    ) -> float:
        pos = self.get_position(order.symbol)
        realized = pos.apply_fill(order, fill_price, fill_qty)

        order.fill_price = fill_price
        order.fill_qty = fill_qty
        order.commission = commission
        order.realized_pnl = realized
        order.filled_at = datetime.utcnow()

        # Cash tracks real money: deduct cost on buy, receive proceeds on sell.
        # realized PnL is NOT added here — it's captured by the two cash flows
        # (entry cost already deducted, exit proceeds received separately).
        signed_cost = fill_price * fill_qty * (
            -1 if order.side == OrderSide.BUY else 1
        )
        self.cash += signed_cost - commission
        self._total_commission += commission

        return realized

    def unrealized_pnl(self, prices: Dict[str, float]) -> float:
        total = 0.0
        for sym, pos in self.positions.items():
            if not pos.is_flat and sym in prices:
                total += pos.unrealized_pnl(prices[sym])
        return total

    def realized_pnl(self) -> float:
        return sum(p.realized_pnl for p in self.positions.values())

    def market_value(self, prices: Dict[str, float]) -> float:
        """Mark-to-market value of all open positions."""
        return sum(
            pos.quantity * prices[sym]
            for sym, pos in self.positions.items()
            if not pos.is_flat and sym in prices
        )

    def equity(self, prices: Dict[str, float]) -> float:
        # equity = cash (net of all buy/sell flows) + current market value of open positions
        return self.cash + self.market_value(prices)

    def snapshot(self, prices: Dict[str, float], ts: Optional[datetime] = None) -> EquitySnapshot:
        ts = ts or datetime.utcnow()
        unreal = self.unrealized_pnl(prices)
        real = self.realized_pnl()
        eq = self.equity(prices)
        self.peak_equity = max(self.peak_equity, eq)
        dd = (self.peak_equity - eq) / self.peak_equity if self.peak_equity > 0 else 0.0
        snap = EquitySnapshot(
            timestamp=ts,
            cash=self.cash,
            unrealized_pnl=unreal,
            realized_pnl=real,
            equity=eq,
            drawdown=dd,
        )
        self.equity_curve.append(snap)
        return snap

    def max_drawdown(self) -> float:
        if not self.equity_curve:
            return 0.0
        return max(s.drawdown for s in self.equity_curve)

    def sharpe_ratio(self, risk_free_rate: float = 0.0) -> float:
        if len(self.equity_curve) < 2:
            return 0.0
        import numpy as np
        equities = [s.equity for s in self.equity_curve]
        returns = np.diff(equities) / np.array(equities[:-1])
        if returns.std() == 0:
            return 0.0
        return float((returns.mean() - risk_free_rate) / returns.std() * (252 ** 0.5))

    def win_rate(self) -> float:
        winners = [o for o in self.closed_trades if o.realized_pnl > 0]
        if not self.closed_trades:
            return 0.0
        return len(winners) / len(self.closed_trades)

    def profit_factor(self) -> float:
        gains = sum(o.realized_pnl for o in self.closed_trades if o.realized_pnl > 0)
        losses = abs(sum(o.realized_pnl for o in self.closed_trades if o.realized_pnl < 0))
        return gains / losses if losses > 0 else float("inf")

    def total_return(self, prices: Dict[str, float]) -> float:
        return (self.equity(prices) - self.initial_capital) / self.initial_capital

    def summary(self, prices: Dict[str, float]) -> dict:
        return {
            "initial_capital": self.initial_capital,
            "cash": round(self.cash, 2),
            "equity": round(self.equity(prices), 2),
            "realized_pnl": round(self.realized_pnl(), 2),
            "unrealized_pnl": round(self.unrealized_pnl(prices), 2),
            "total_return_pct": round(self.total_return(prices) * 100, 2),
            "max_drawdown_pct": round(self.max_drawdown() * 100, 2),
            "sharpe_ratio": round(self.sharpe_ratio(), 4),
            "win_rate_pct": round(self.win_rate() * 100, 2),
            "profit_factor": round(self.profit_factor(), 4),
            "total_trades": len(self.closed_trades),
            "total_commission": round(self._total_commission, 2),
            "open_positions": {
                sym: str(pos) for sym, pos in self.positions.items() if not pos.is_flat
            },
        }
