"""
Abstract base strategy. All strategies inherit from this.
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import List, Optional
from dataclasses import dataclass, field

from ..core.order import Order, OrderSide, OrderType, TPSLConfig, TPSLType
from ..core.market_data import MarketState, Bar


@dataclass
class StrategyConfig:
    """Common configuration shared across strategies."""
    plan_id: str = "DEFAULT"
    symbols: List[str] = field(default_factory=list)
    max_position_pct: float = 0.10    # max % of portfolio per position
    commission_pct: float = 0.0005    # 0.05% per side
    min_bars: int = 20                # bars needed before trading
    enabled: bool = True


class BaseStrategy(ABC):
    """Abstract base for all trading strategies."""

    def __init__(self, config: StrategyConfig):
        self.config = config
        self.plan_id = config.plan_id
        self.orders_generated: List[Order] = []

    @property
    @abstractmethod
    def name(self) -> str:
        ...

    @abstractmethod
    def generate_signals(
        self,
        symbol: str,
        market: MarketState,
        portfolio_value: float,
        current_position: float,
    ) -> List[Order]:
        """Return list of orders to submit. Empty list = no action."""
        ...

    def _make_order(
        self,
        symbol: str,
        side: OrderSide,
        qty: float,
        tpsl: TPSLConfig,
        order_type: OrderType = OrderType.MARKET,
        limit_price: Optional[float] = None,
        tags: Optional[dict] = None,
    ) -> Order:
        return Order(
            symbol=symbol,
            side=side,
            quantity=qty,
            order_type=order_type,
            limit_price=limit_price,
            tpsl=tpsl,
            strategy_id=self.name,
            plan_id=self.plan_id,
            tags=tags or {},
        )

    def size_position(
        self,
        portfolio_value: float,
        price: float,
        risk_pct: float = 0.01,
        sl_distance: float = 0.0,
    ) -> float:
        """Kelly-inspired position sizing based on risk % and SL distance."""
        risk_amount = portfolio_value * risk_pct
        if sl_distance > 0:
            qty = risk_amount / sl_distance
        else:
            qty = (portfolio_value * self.config.max_position_pct) / price
        max_qty = (portfolio_value * self.config.max_position_pct) / price
        return round(min(qty, max_qty), 6)
