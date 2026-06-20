"""
Position tracking per symbol.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Optional
from datetime import datetime

from .order import Order, OrderSide, OrderStatus


@dataclass
class Position:
    """Aggregated position for a symbol."""
    symbol: str
    quantity: float = 0.0
    avg_entry_price: float = 0.0
    realized_pnl: float = 0.0
    orders: List[Order] = field(default_factory=list)
    opened_at: Optional[datetime] = None
    last_updated: Optional[datetime] = None

    @property
    def side(self) -> Optional[str]:
        if self.quantity > 0:
            return "LONG"
        elif self.quantity < 0:
            return "SHORT"
        return None

    @property
    def is_flat(self) -> bool:
        return abs(self.quantity) < 1e-9

    def unrealized_pnl(self, current_price: float) -> float:
        if self.is_flat:
            return 0.0
        return (current_price - self.avg_entry_price) * self.quantity

    def total_pnl(self, current_price: float) -> float:
        return self.realized_pnl + self.unrealized_pnl(current_price)

    def market_value(self, current_price: float) -> float:
        return self.quantity * current_price

    def apply_fill(self, order: Order, fill_price: float, fill_qty: float) -> float:
        """Apply fill to position. Returns realized PnL from this fill."""
        realized = 0.0
        signed_qty = fill_qty if order.side == OrderSide.BUY else -fill_qty

        if self.is_flat:
            self.quantity = signed_qty
            self.avg_entry_price = fill_price
            self.opened_at = datetime.utcnow()
        elif (self.quantity > 0 and signed_qty > 0) or (self.quantity < 0 and signed_qty < 0):
            # Adding to position: update VWAP entry
            total_qty = self.quantity + signed_qty
            self.avg_entry_price = (
                self.avg_entry_price * abs(self.quantity) + fill_price * abs(signed_qty)
            ) / abs(total_qty)
            self.quantity = total_qty
        else:
            # Reducing or flipping position
            close_qty = min(abs(signed_qty), abs(self.quantity))
            direction = 1 if self.quantity > 0 else -1
            realized = (fill_price - self.avg_entry_price) * direction * close_qty
            self.realized_pnl += realized
            remaining = self.quantity + signed_qty
            if abs(remaining) < 1e-9:
                self.quantity = 0.0
                self.avg_entry_price = 0.0
            else:
                # Flipped
                self.quantity = remaining
                self.avg_entry_price = fill_price

        self.orders.append(order)
        self.last_updated = datetime.utcnow()
        return realized

    def __repr__(self) -> str:
        return (
            f"Position({self.symbol} qty={self.quantity:.4f} "
            f"avg={self.avg_entry_price:.4f} realized_pnl={self.realized_pnl:.2f})"
        )
