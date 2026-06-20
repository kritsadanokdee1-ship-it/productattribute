"""
Plan B: Mean Reversion Strategy using Bollinger Bands + RSI.
Buys at lower band when oversold, sells at upper band when overbought.
TP: Mid band (mean), SL: 1.0x ATR beyond band.
"""
from __future__ import annotations
from typing import List

from .base import BaseStrategy, StrategyConfig
from ..core.order import Order, OrderSide, TPSLConfig, TPSLType
from ..core.market_data import MarketState


class MeanReversionStrategy(BaseStrategy):
    """
    Signal: Price touches Bollinger Band extremes + RSI extreme.
    TP: Return to midband (FIXED price), SL: ATR-based.
    """

    def __init__(
        self,
        config: StrategyConfig,
        bb_period: int = 20,
        bb_std: float = 2.0,
        rsi_period: int = 14,
        rsi_ob: float = 70.0,
        rsi_os: float = 30.0,
        sl_atr_mult: float = 1.0,
    ):
        super().__init__(config)
        self.bb_period = bb_period
        self.bb_std = bb_std
        self.rsi_period = rsi_period
        self.rsi_ob = rsi_ob
        self.rsi_os = rsi_os
        self.sl_atr_mult = sl_atr_mult

    @property
    def name(self) -> str:
        return "MeanReversionBB"

    def generate_signals(
        self,
        symbol: str,
        market: MarketState,
        portfolio_value: float,
        current_position: float,
    ) -> List[Order]:
        bars = market.get_bars(symbol, self.bb_period + 5)
        if len(bars) < self.config.min_bars:
            return []

        upper, mid, lower = market.bollinger(symbol, self.bb_period, self.bb_std)
        rsi = market.rsi(symbol, self.rsi_period)
        atr = market.atr(symbol, 14)
        price = market.last_price(symbol)

        if None in (upper, mid, lower, rsi, price) or atr == 0:
            return []

        orders = []

        # Long entry: price at/below lower band AND RSI oversold
        if price <= lower and rsi < self.rsi_os and current_position <= 0:
            tpsl = TPSLConfig(
                tp_type=TPSLType.FIXED,
                sl_type=TPSLType.ATR,
                tp_price=mid,
                sl_atr_mult=self.sl_atr_mult,
            )
            sl_dist = atr * self.sl_atr_mult
            qty = self.size_position(portfolio_value, price, 0.008, sl_dist)
            if qty > 0:
                orders.append(
                    self._make_order(symbol, OrderSide.BUY, qty, tpsl, tags={"signal": "lower_bb_bounce"})
                )

        # Short entry: price at/above upper band AND RSI overbought
        elif price >= upper and rsi > self.rsi_ob and current_position >= 0:
            tpsl = TPSLConfig(
                tp_type=TPSLType.FIXED,
                sl_type=TPSLType.ATR,
                tp_price=mid,
                sl_atr_mult=self.sl_atr_mult,
            )
            sl_dist = atr * self.sl_atr_mult
            qty = self.size_position(portfolio_value, price, 0.008, sl_dist)
            if qty > 0:
                orders.append(
                    self._make_order(symbol, OrderSide.SELL, qty, tpsl, tags={"signal": "upper_bb_fade"})
                )

        return orders
