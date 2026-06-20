"""
Plan F: Market Making Strategy.
Posts limit orders on both sides of the book to capture bid-ask spread.
Manages inventory risk via skewed quotes when position builds.
TP: Captured spread, SL: hard stop on adverse inventory.
"""
from __future__ import annotations
from typing import List

from .base import BaseStrategy, StrategyConfig
from ..core.order import Order, OrderSide, OrderType, TPSLConfig, TPSLType
from ..core.market_data import MarketState


class MarketMakingStrategy(BaseStrategy):
    """
    Posts two-sided limit orders around mid-price.
    Adjusts quote skew based on current inventory.
    """

    def __init__(
        self,
        config: StrategyConfig,
        spread_pct: float = 0.001,      # half-spread
        order_size_pct: float = 0.01,   # fraction of portfolio per quote
        max_inventory_pct: float = 0.05, # max net position before skewing
        skew_factor: float = 0.3,       # how much to skew quotes toward flat
        sl_pct: float = 0.008,          # hard stop loss on inventory
        tp_pct: float = 0.004,          # take profit on inventory position
    ):
        super().__init__(config)
        self.spread_pct = spread_pct
        self.order_size_pct = order_size_pct
        self.max_inventory_pct = max_inventory_pct
        self.skew_factor = skew_factor
        self.sl_pct = sl_pct
        self.tp_pct = tp_pct

    @property
    def name(self) -> str:
        return "MarketMaker"

    def generate_signals(
        self,
        symbol: str,
        market: MarketState,
        portfolio_value: float,
        current_position: float,
    ) -> List[Order]:
        bars = market.get_bars(symbol, 5)
        if len(bars) < self.config.min_bars:
            return []

        price = market.last_price(symbol)
        atr = market.atr(symbol, 14)
        if price is None or atr == 0:
            return []

        max_inventory = (portfolio_value * self.max_inventory_pct) / price
        inventory_ratio = current_position / max_inventory if max_inventory > 0 else 0
        inventory_ratio = max(-1.0, min(1.0, inventory_ratio))

        # Skew quotes based on inventory
        skew = -inventory_ratio * self.skew_factor * self.spread_pct * price
        half_spread = self.spread_pct * price

        bid_price = price - half_spread + skew
        ask_price = price + half_spread + skew

        qty = round((portfolio_value * self.order_size_pct) / price, 6)
        orders = []

        # Only post buy side if not too long
        if inventory_ratio < 0.8:
            tpsl_buy = TPSLConfig(
                tp_type=TPSLType.PERCENT,
                sl_type=TPSLType.PERCENT,
                tp_pct=self.tp_pct,
                sl_pct=self.sl_pct,
            )
            orders.append(
                self._make_order(
                    symbol, OrderSide.BUY, qty, tpsl_buy,
                    order_type=OrderType.LIMIT, limit_price=round(bid_price, 4),
                    tags={"signal": "mm_bid", "skew": inventory_ratio},
                )
            )

        # Only post sell side if not too short
        if inventory_ratio > -0.8:
            tpsl_sell = TPSLConfig(
                tp_type=TPSLType.PERCENT,
                sl_type=TPSLType.PERCENT,
                tp_pct=self.tp_pct,
                sl_pct=self.sl_pct,
            )
            orders.append(
                self._make_order(
                    symbol, OrderSide.SELL, qty, tpsl_sell,
                    order_type=OrderType.LIMIT, limit_price=round(ask_price, 4),
                    tags={"signal": "mm_ask", "skew": inventory_ratio},
                )
            )

        return orders
