"""
Order model with per-order TP/SL management.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime
from typing import Optional
import uuid


class OrderSide(Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP = "STOP"
    STOP_LIMIT = "STOP_LIMIT"


class OrderStatus(Enum):
    PENDING = "PENDING"
    OPEN = "OPEN"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    TP_HIT = "TP_HIT"
    SL_HIT = "SL_HIT"


class TPSLType(Enum):
    FIXED = "FIXED"          # Fixed price level
    ATR = "ATR"              # Multiple of ATR
    PERCENT = "PERCENT"      # Percentage from entry
    R_MULTIPLE = "R_MULTIPLE"  # Risk multiple (e.g., 2R target)
    TRAILING = "TRAILING"    # Trailing stop


@dataclass
class TPSLConfig:
    """Per-order Take Profit / Stop Loss configuration."""
    tp_type: TPSLType = TPSLType.PERCENT
    sl_type: TPSLType = TPSLType.PERCENT

    # For FIXED type: absolute price
    tp_price: Optional[float] = None
    sl_price: Optional[float] = None

    # For PERCENT type: percentage from entry (e.g., 0.02 = 2%)
    tp_pct: float = 0.02
    sl_pct: float = 0.01

    # For ATR type: ATR multiplier
    tp_atr_mult: float = 2.0
    sl_atr_mult: float = 1.0

    # For R_MULTIPLE: risk amount per unit, then tp = entry + R * mult
    risk_per_unit: Optional[float] = None
    tp_r_mult: float = 2.0

    # For TRAILING: trail amount in price units
    trail_amount: Optional[float] = None
    trail_pct: float = 0.01

    def compute_levels(
        self,
        entry_price: float,
        side: OrderSide,
        atr: float = 0.0,
    ) -> tuple[Optional[float], Optional[float]]:
        """Return (tp_price, sl_price) computed from entry."""
        direction = 1 if side == OrderSide.BUY else -1

        tp = self._compute(
            self.tp_type, entry_price, direction,
            fixed=self.tp_price, pct=self.tp_pct,
            atr=atr, atr_mult=self.tp_atr_mult,
            r_mult=self.tp_r_mult, risk=self.risk_per_unit,
            is_tp=True,
        )
        sl = self._compute(
            self.sl_type, entry_price, direction,
            fixed=self.sl_price, pct=self.sl_pct,
            atr=atr, atr_mult=self.sl_atr_mult,
            r_mult=1.0, risk=self.risk_per_unit,
            is_tp=False,
        )
        return tp, sl

    def _compute(
        self,
        tp_sl_type: TPSLType,
        entry: float,
        direction: int,
        fixed: Optional[float],
        pct: float,
        atr: float,
        atr_mult: float,
        r_mult: float,
        risk: Optional[float],
        is_tp: bool,
    ) -> Optional[float]:
        sign = direction if is_tp else -direction

        if tp_sl_type == TPSLType.FIXED:
            return fixed
        elif tp_sl_type == TPSLType.PERCENT:
            return entry * (1 + sign * pct)
        elif tp_sl_type == TPSLType.ATR:
            return entry + sign * atr * atr_mult
        elif tp_sl_type == TPSLType.R_MULTIPLE:
            if risk is None:
                return None
            return entry + sign * risk * r_mult
        elif tp_sl_type == TPSLType.TRAILING:
            # Initial placement same as PERCENT for TRAILING
            return entry * (1 + sign * (self.trail_pct if not self.trail_amount else 0))
        return None


@dataclass
class Order:
    """Represents a single trading order with TP/SL."""
    symbol: str
    side: OrderSide
    quantity: float
    order_type: OrderType = OrderType.MARKET
    limit_price: Optional[float] = None
    stop_price: Optional[float] = None
    tpsl: TPSLConfig = field(default_factory=TPSLConfig)
    strategy_id: str = ""
    plan_id: str = ""
    tags: dict = field(default_factory=dict)

    # Filled by execution engine
    order_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    status: OrderStatus = OrderStatus.PENDING
    fill_price: Optional[float] = None
    fill_qty: float = 0.0
    tp_level: Optional[float] = None
    sl_level: Optional[float] = None
    trailing_sl: Optional[float] = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    filled_at: Optional[datetime] = None
    closed_at: Optional[datetime] = None
    realized_pnl: float = 0.0
    commission: float = 0.0

    def set_tpsl_from_fill(self, fill_price: float, atr: float = 0.0) -> None:
        self.tp_level, self.sl_level = self.tpsl.compute_levels(fill_price, self.side, atr)
        if self.tpsl.sl_type == TPSLType.TRAILING and self.tpsl.trail_amount:
            direction = 1 if self.side == OrderSide.BUY else -1
            self.trailing_sl = fill_price - direction * self.tpsl.trail_amount

    def update_trailing_sl(self, current_price: float) -> None:
        """Ratchet trailing stop in profit direction."""
        if self.tpsl.sl_type != TPSLType.TRAILING:
            return
        if self.side == OrderSide.BUY and self.trailing_sl is not None:
            trail = (
                self.tpsl.trail_amount
                if self.tpsl.trail_amount
                else current_price * self.tpsl.trail_pct
            )
            new_sl = current_price - trail
            if new_sl > (self.trailing_sl or 0):
                self.trailing_sl = new_sl
                self.sl_level = self.trailing_sl
        elif self.side == OrderSide.SELL and self.trailing_sl is not None:
            trail = (
                self.tpsl.trail_amount
                if self.tpsl.trail_amount
                else current_price * self.tpsl.trail_pct
            )
            new_sl = current_price + trail
            if new_sl < (self.trailing_sl or float("inf")):
                self.trailing_sl = new_sl
                self.sl_level = self.trailing_sl

    def check_tpsl_hit(self, high: float, low: float) -> Optional[str]:
        """Return 'TP', 'SL', or None based on bar high/low."""
        if self.side == OrderSide.BUY:
            if self.tp_level and high >= self.tp_level:
                return "TP"
            if self.sl_level and low <= self.sl_level:
                return "SL"
        else:
            if self.tp_level and low <= self.tp_level:
                return "TP"
            if self.sl_level and high >= self.sl_level:
                return "SL"
        return None

    @property
    def is_active(self) -> bool:
        return self.status in (OrderStatus.OPEN, OrderStatus.PARTIALLY_FILLED)

    @property
    def risk_amount(self) -> float:
        if self.fill_price and self.sl_level:
            return abs(self.fill_price - self.sl_level) * self.fill_qty
        return 0.0

    @property
    def potential_reward(self) -> float:
        if self.fill_price and self.tp_level:
            return abs(self.fill_price - self.tp_level) * self.fill_qty
        return 0.0

    @property
    def risk_reward_ratio(self) -> float:
        risk = self.risk_amount
        return self.potential_reward / risk if risk > 0 else 0.0

    def __repr__(self) -> str:
        return (
            f"Order({self.order_id} {self.side.value} {self.quantity} {self.symbol} "
            f"@ {self.fill_price} TP={self.tp_level} SL={self.sl_level} "
            f"PnL={self.realized_pnl:.2f})"
        )
