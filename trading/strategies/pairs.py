"""
Plan E: Statistical Arbitrage / Pairs Trading.
Trade the spread between two correlated instruments.
Enter when z-score of spread exceeds threshold; exit on reversion.
Each leg has its own TP/SL.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Optional, Tuple
import numpy as np

from .base import BaseStrategy, StrategyConfig
from ..core.order import Order, OrderSide, TPSLConfig, TPSLType
from ..core.market_data import MarketState


@dataclass
class PairConfig:
    symbol_a: str
    symbol_b: str
    hedge_ratio: float = 1.0          # qty of B per unit of A
    entry_z: float = 2.0              # z-score to enter
    exit_z: float = 0.5               # z-score to exit (mean reversion)
    stop_z: float = 3.5               # z-score to stop out
    lookback: int = 60


class PairsStrategy(BaseStrategy):
    """Pairs / statistical arbitrage strategy."""

    def __init__(
        self,
        config: StrategyConfig,
        pairs: Optional[List[PairConfig]] = None,
        tp_pct: float = 0.015,
        sl_pct: float = 0.008,
    ):
        super().__init__(config)
        self.pairs = pairs or []
        self.tp_pct = tp_pct
        self.sl_pct = sl_pct
        self._pair_state: dict = {}

    @property
    def name(self) -> str:
        return "PairsStatArb"

    def _compute_spread_zscore(
        self, market: MarketState, pair: PairConfig
    ) -> Tuple[Optional[float], Optional[float]]:
        bars_a = market.get_bars(pair.symbol_a, pair.lookback)
        bars_b = market.get_bars(pair.symbol_b, pair.lookback)
        n = min(len(bars_a), len(bars_b))
        if n < pair.lookback // 2:
            return None, None
        closes_a = np.array([b.close for b in bars_a[-n:]])
        closes_b = np.array([b.close for b in bars_b[-n:]])
        spread = closes_a - pair.hedge_ratio * closes_b
        z = (spread[-1] - spread.mean()) / (spread.std() + 1e-9)
        return float(z), float(spread[-1])

    def generate_signals(
        self,
        symbol: str,
        market: MarketState,
        portfolio_value: float,
        current_position: float,
    ) -> List[Order]:
        orders = []
        for pair in self.pairs:
            if symbol not in (pair.symbol_a, pair.symbol_b):
                continue
            pair_key = f"{pair.symbol_a}_{pair.symbol_b}"
            z, spread = self._compute_spread_zscore(market, pair)
            if z is None:
                continue

            price_a = market.last_price(pair.symbol_a)
            price_b = market.last_price(pair.symbol_b)
            if price_a is None or price_b is None:
                continue

            state = self._pair_state.get(pair_key, "FLAT")

            if state == "FLAT":
                if z > pair.entry_z:
                    # Spread too high: sell A, buy B
                    qty_a = self.size_position(portfolio_value, price_a, 0.005, price_a * self.sl_pct)
                    qty_b = qty_a * pair.hedge_ratio
                    tpsl_a = TPSLConfig(tp_type=TPSLType.PERCENT, sl_type=TPSLType.PERCENT,
                                        tp_pct=self.tp_pct, sl_pct=self.sl_pct)
                    tpsl_b = TPSLConfig(tp_type=TPSLType.PERCENT, sl_type=TPSLType.PERCENT,
                                        tp_pct=self.tp_pct, sl_pct=self.sl_pct)
                    orders.append(self._make_order(pair.symbol_a, OrderSide.SELL, qty_a, tpsl_a,
                                                   tags={"pair": pair_key, "leg": "A", "z": z}))
                    orders.append(self._make_order(pair.symbol_b, OrderSide.BUY, qty_b, tpsl_b,
                                                   tags={"pair": pair_key, "leg": "B", "z": z}))
                    self._pair_state[pair_key] = "SHORT_SPREAD"

                elif z < -pair.entry_z:
                    # Spread too low: buy A, sell B
                    qty_a = self.size_position(portfolio_value, price_a, 0.005, price_a * self.sl_pct)
                    qty_b = qty_a * pair.hedge_ratio
                    tpsl_a = TPSLConfig(tp_type=TPSLType.PERCENT, sl_type=TPSLType.PERCENT,
                                        tp_pct=self.tp_pct, sl_pct=self.sl_pct)
                    tpsl_b = TPSLConfig(tp_type=TPSLType.PERCENT, sl_type=TPSLType.PERCENT,
                                        tp_pct=self.tp_pct, sl_pct=self.sl_pct)
                    orders.append(self._make_order(pair.symbol_a, OrderSide.BUY, qty_a, tpsl_a,
                                                   tags={"pair": pair_key, "leg": "A", "z": z}))
                    orders.append(self._make_order(pair.symbol_b, OrderSide.SELL, qty_b, tpsl_b,
                                                   tags={"pair": pair_key, "leg": "B", "z": z}))
                    self._pair_state[pair_key] = "LONG_SPREAD"

        return orders
