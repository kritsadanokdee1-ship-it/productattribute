"""
Synthetic market data generator using Geometric Brownian Motion + regime switching.
Produces realistic OHLCV bars for backtesting.
"""
from __future__ import annotations
from datetime import datetime, timedelta
from typing import List, Optional
import numpy as np

from ..core.market_data import Bar


class MarketDataGenerator:
    """
    Generates synthetic OHLCV bars via GBM with:
    - Regime switching (bull / bear / sideways)
    - Mean-reverting spreads for pairs
    - Fat tails (Student-t noise)
    - Volume correlated with price moves
    """

    def __init__(self, seed: Optional[int] = 42):
        self.rng = np.random.default_rng(seed)

    def generate_gbm_bars(
        self,
        symbol: str,
        start_price: float = 100.0,
        n_bars: int = 500,
        mu: float = 0.0002,        # drift per bar
        sigma: float = 0.012,      # vol per bar
        start_time: Optional[datetime] = None,
        bar_minutes: int = 60,
        regime_shift: bool = True,
        fat_tails: bool = True,
    ) -> List[Bar]:
        start_time = start_time or datetime(2024, 1, 1, 9, 30)
        bars: List[Bar] = []
        price = start_price
        regime = "BULL"
        regime_bars = 0
        regime_len = int(self.rng.integers(50, 150))

        for i in range(n_bars):
            # Regime switching
            if regime_shift:
                regime_bars += 1
                if regime_bars >= regime_len:
                    regime = self.rng.choice(["BULL", "BEAR", "SIDEWAYS"])
                    regime_len = int(self.rng.integers(50, 150))
                    regime_bars = 0
                regime_mu = {"BULL": mu + 0.0003, "BEAR": mu - 0.0003, "SIDEWAYS": 0.0}[regime]
                regime_sigma = {"BULL": sigma * 0.8, "BEAR": sigma * 1.3, "SIDEWAYS": sigma * 0.5}[regime]
            else:
                regime_mu = mu
                regime_sigma = sigma

            # Fat-tailed returns
            if fat_tails:
                ret = self.rng.standard_t(df=5) * regime_sigma + regime_mu
            else:
                ret = self.rng.normal(regime_mu, regime_sigma)

            close = price * (1 + ret)
            intrabar_vol = abs(ret) * self.rng.uniform(0.3, 0.8)
            high = max(price, close) * (1 + intrabar_vol)
            low = min(price, close) * (1 - intrabar_vol)
            open_price = price * (1 + self.rng.normal(0, sigma * 0.1))

            # Volume: higher on bigger moves
            base_vol = 1_000_000
            vol_mult = 1 + abs(ret) / sigma * 2
            volume = base_vol * vol_mult * self.rng.lognormal(0, 0.3)

            ts = start_time + timedelta(minutes=bar_minutes * i)
            bars.append(Bar(
                symbol=symbol,
                timestamp=ts,
                open=round(open_price, 4),
                high=round(high, 4),
                low=round(low, 4),
                close=round(close, 4),
                volume=round(volume, 0),
            ))
            price = close

        return bars

    def generate_correlated_pair(
        self,
        symbol_a: str,
        symbol_b: str,
        start_price_a: float = 100.0,
        start_price_b: float = 98.0,
        n_bars: int = 500,
        correlation: float = 0.85,
        mean_reversion_speed: float = 0.1,
        **kwargs,
    ) -> tuple[List[Bar], List[Bar]]:
        """Generate two correlated instruments with mean-reverting spread."""
        sigma = kwargs.get("sigma", 0.012)
        mu = kwargs.get("mu", 0.0002)
        start_time = kwargs.get("start_time", datetime(2024, 1, 1, 9, 30))
        bar_minutes = kwargs.get("bar_minutes", 60)

        bars_a: List[Bar] = []
        bars_b: List[Bar] = []
        price_a = start_price_a
        price_b = start_price_b
        spread_mean = price_a - price_b
        spread = spread_mean

        cov = [[sigma**2, correlation * sigma**2],
               [correlation * sigma**2, sigma**2]]

        for i in range(n_bars):
            returns = self.rng.multivariate_normal([mu, mu], cov)
            # Add mean-reverting component to spread
            spread_deviation = spread - spread_mean
            mr_adj = -mean_reversion_speed * spread_deviation / (price_a + 1e-9)
            ret_a = returns[0] + mr_adj
            ret_b = returns[1] - mr_adj

            def make_bar(sym, p, ret, t):
                close = p * (1 + ret)
                iv = abs(ret) * self.rng.uniform(0.3, 0.8)
                return Bar(
                    symbol=sym,
                    timestamp=t,
                    open=round(p * (1 + self.rng.normal(0, sigma * 0.1)), 4),
                    high=round(max(p, close) * (1 + iv), 4),
                    low=round(min(p, close) * (1 - iv), 4),
                    close=round(close, 4),
                    volume=round(1_000_000 * self.rng.lognormal(0, 0.3), 0),
                )

            ts = start_time + timedelta(minutes=bar_minutes * i)
            bars_a.append(make_bar(symbol_a, price_a, ret_a, ts))
            bars_b.append(make_bar(symbol_b, price_b, ret_b, ts))
            price_a = bars_a[-1].close
            price_b = bars_b[-1].close
            spread = price_a - price_b

        return bars_a, bars_b
