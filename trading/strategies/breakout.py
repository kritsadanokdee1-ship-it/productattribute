"""
Plan D: Donchian Channel Breakout Strategy.
Classic breakout: enter long when price breaks n-period high, short on n-period low.
Used by trend-followers (Turtle Traders / Dunn Capital style).
TP: 2x entry channel width, SL: Trailing ATR.
"""
from __future__ import annotations
from typing import List, Optional

from .base import BaseStrategy, StrategyConfig
from ..core.order import Order, OrderSide, TPSLConfig, TPSLType
from ..core.market_data import MarketState


class BreakoutStrategy(BaseStrategy):
    """Donchian channel breakout with ATR-scaled TP/SL."""

    def __init__(
        self,
        config: StrategyConfig,
        entry_period: int = 20,
        exit_period: int = 10,
        tp_channel_mult: float = 2.0,
        sl_atr_mult: float = 2.0,
        atr_period: int = 14,
    ):
        super().__init__(config)
        self.entry_period = entry_period
        self.exit_period = exit_period
        self.tp_channel_mult = tp_channel_mult
        self.sl_atr_mult = sl_atr_mult
        self.atr_period = atr_period
        self._last_signal: dict = {}

    @property
    def name(self) -> str:
        return "DonchianBreakout"

    def _channel(self, market: MarketState, symbol: str, period: int) -> tuple[Optional[float], Optional[float]]:
        # Exclude the current (most recent) bar so price can break out of the channel
        bars = market.get_bars(symbol, period + 1)[:-1]
        if len(bars) < period:
            return None, None
        return max(b.high for b in bars), min(b.low for b in bars)

    def generate_signals(
        self,
        symbol: str,
        market: MarketState,
        portfolio_value: float,
        current_position: float,
    ) -> List[Order]:
        if market.bar_count(symbol) < self.config.min_bars:
            return []

        entry_high, entry_low = self._channel(market, symbol, self.entry_period)
        atr = market.atr(symbol, self.atr_period)
        price = market.last_price(symbol)

        if None in (entry_high, entry_low, price) or atr == 0:
            return []

        channel_width = entry_high - entry_low
        prev = self._last_signal.get(symbol)
        orders = []

        # Upside breakout
        if price > entry_high and prev != "LONG" and current_position <= 0:
            tpsl = TPSLConfig(
                tp_type=TPSLType.FIXED,
                sl_type=TPSLType.TRAILING,
                tp_price=price + channel_width * self.tp_channel_mult,
                trail_amount=atr * self.sl_atr_mult,
            )
            qty = self.size_position(portfolio_value, price, 0.01, atr * self.sl_atr_mult)
            if qty > 0:
                orders.append(
                    self._make_order(symbol, OrderSide.BUY, qty, tpsl,
                                     tags={"signal": "breakout_up", "channel_high": entry_high})
                )
                self._last_signal[symbol] = "LONG"

        # Downside breakout
        elif price < entry_low and prev != "SHORT" and current_position >= 0:
            tpsl = TPSLConfig(
                tp_type=TPSLType.FIXED,
                sl_type=TPSLType.TRAILING,
                tp_price=price - channel_width * self.tp_channel_mult,
                trail_amount=atr * self.sl_atr_mult,
            )
            qty = self.size_position(portfolio_value, price, 0.01, atr * self.sl_atr_mult)
            if qty > 0:
                orders.append(
                    self._make_order(symbol, OrderSide.SELL, qty, tpsl,
                                     tags={"signal": "breakout_down", "channel_low": entry_low})
                )
                self._last_signal[symbol] = "SHORT"

        return orders
