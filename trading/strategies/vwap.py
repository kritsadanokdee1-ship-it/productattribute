"""
Plan C: VWAP Strategy.
Institutional intraday strategy — trade reversions to VWAP.
Long when price is below VWAP with increasing volume.
Short when price is above VWAP with decreasing volume.
TP: VWAP level (FIXED), SL: PERCENT-based.
"""
from __future__ import annotations
from typing import List

from .base import BaseStrategy, StrategyConfig
from ..core.order import Order, OrderSide, TPSLConfig, TPSLType
from ..core.market_data import MarketState


class VWAPStrategy(BaseStrategy):
    """VWAP mean-reversion intraday strategy."""

    def __init__(
        self,
        config: StrategyConfig,
        vwap_period: int = 20,
        deviation_pct: float = 0.005,   # enter when price deviates 0.5% from VWAP
        tp_pct: float = 0.004,
        sl_pct: float = 0.003,
        volume_confirm_bars: int = 3,
    ):
        super().__init__(config)
        self.vwap_period = vwap_period
        self.deviation_pct = deviation_pct
        self.tp_pct = tp_pct
        self.sl_pct = sl_pct
        self.volume_confirm_bars = volume_confirm_bars

    @property
    def name(self) -> str:
        return "VWAPReversion"

    def _avg_volume(self, bars, n: int) -> float:
        if len(bars) < n:
            return 0.0
        return sum(b.volume for b in bars[-n:]) / n

    def generate_signals(
        self,
        symbol: str,
        market: MarketState,
        portfolio_value: float,
        current_position: float,
    ) -> List[Order]:
        if market.bar_count(symbol) < self.config.min_bars:
            return []

        bars = market.get_bars(symbol, self.vwap_period + self.volume_confirm_bars)
        vwap = market.vwap(symbol, self.vwap_period)
        price = market.last_price(symbol)
        if vwap is None or price is None:
            return []

        deviation = (price - vwap) / vwap
        avg_vol = self._avg_volume(bars, self.volume_confirm_bars)
        last_vol = bars[-1].volume if bars else 0

        orders = []

        # Long: price significantly below VWAP with volume spike (institutional buying)
        if deviation < -self.deviation_pct and last_vol > avg_vol * 1.2 and current_position <= 0:
            tpsl = TPSLConfig(
                tp_type=TPSLType.FIXED,
                sl_type=TPSLType.PERCENT,
                tp_price=vwap,
                sl_pct=self.sl_pct,
            )
            sl_dist = price * self.sl_pct
            qty = self.size_position(portfolio_value, price, 0.005, sl_dist)
            if qty > 0:
                orders.append(
                    self._make_order(symbol, OrderSide.BUY, qty, tpsl,
                                     tags={"signal": "below_vwap", "deviation": deviation})
                )

        # Short: price significantly above VWAP with volume dry-up
        elif deviation > self.deviation_pct and last_vol < avg_vol * 0.8 and current_position >= 0:
            tpsl = TPSLConfig(
                tp_type=TPSLType.FIXED,
                sl_type=TPSLType.PERCENT,
                tp_price=vwap,
                sl_pct=self.sl_pct,
            )
            sl_dist = price * self.sl_pct
            qty = self.size_position(portfolio_value, price, 0.005, sl_dist)
            if qty > 0:
                orders.append(
                    self._make_order(symbol, OrderSide.SELL, qty, tpsl,
                                     tags={"signal": "above_vwap", "deviation": deviation})
                )

        return orders
