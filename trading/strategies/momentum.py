"""
Plan A: Momentum / Trend-Following Strategy.
Enters in the direction of strong price momentum confirmed by EMA crossover.
TP: 3x ATR, SL: 1.5x ATR (trailing after 1x ATR profit).
"""
from __future__ import annotations
from typing import List

from .base import BaseStrategy, StrategyConfig
from ..core.order import Order, OrderSide, TPSLConfig, TPSLType
from ..core.market_data import MarketState


class MomentumStrategy(BaseStrategy):
    """
    Signal: Fast EMA crosses above/below Slow EMA + RSI confirmation.
    TP/SL: ATR-based per trade.
    """

    def __init__(
        self,
        config: StrategyConfig,
        fast_ema: int = 9,
        slow_ema: int = 21,
        rsi_period: int = 14,
        rsi_ob: float = 65.0,
        rsi_os: float = 35.0,
        tp_atr: float = 3.0,
        sl_atr: float = 1.5,
    ):
        super().__init__(config)
        self.fast_ema = fast_ema
        self.slow_ema = slow_ema
        self.rsi_period = rsi_period
        self.rsi_ob = rsi_ob
        self.rsi_os = rsi_os
        self.tp_atr = tp_atr
        self.sl_atr = sl_atr
        self._prev_cross: dict = {}

    @property
    def name(self) -> str:
        return "MomentumEMACross"

    def generate_signals(
        self,
        symbol: str,
        market: MarketState,
        portfolio_value: float,
        current_position: float,
    ) -> List[Order]:
        bars = market.get_bars(symbol, self.slow_ema + 10)
        if len(bars) < self.config.min_bars:
            return []

        fast = market.ema(symbol, self.fast_ema)
        slow = market.ema(symbol, self.slow_ema)
        rsi = market.rsi(symbol, self.rsi_period)
        atr = market.atr(symbol, 14)
        price = market.last_price(symbol)

        if None in (fast, slow, rsi, price) or atr == 0:
            return []

        prev = self._prev_cross.get(symbol, {"fast": fast, "slow": slow})
        bullish_cross = prev["fast"] <= prev["slow"] and fast > slow
        bearish_cross = prev["fast"] >= prev["slow"] and fast < slow
        self._prev_cross[symbol] = {"fast": fast, "slow": slow}

        orders = []

        if bullish_cross and rsi < self.rsi_ob and current_position <= 0:
            tpsl = TPSLConfig(
                tp_type=TPSLType.ATR,
                sl_type=TPSLType.TRAILING,
                tp_atr_mult=self.tp_atr,
                sl_atr_mult=self.sl_atr,
                trail_amount=atr * self.sl_atr,
            )
            qty = self.size_position(portfolio_value, price, 0.01, atr * self.sl_atr)
            if qty > 0:
                orders.append(self._make_order(symbol, OrderSide.BUY, qty, tpsl, tags={"signal": "bullish_cross"}))

        elif bearish_cross and rsi > self.rsi_os and current_position >= 0:
            tpsl = TPSLConfig(
                tp_type=TPSLType.ATR,
                sl_type=TPSLType.TRAILING,
                tp_atr_mult=self.tp_atr,
                sl_atr_mult=self.sl_atr,
                trail_amount=atr * self.sl_atr,
            )
            qty = self.size_position(portfolio_value, price, 0.01, atr * self.sl_atr)
            if qty > 0:
                orders.append(self._make_order(symbol, OrderSide.SELL, qty, tpsl, tags={"signal": "bearish_cross"}))

        return orders
