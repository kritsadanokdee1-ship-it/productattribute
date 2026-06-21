"""
Market data models and OHLCV bar structures.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional
import numpy as np


@dataclass
class Bar:
    """OHLCV bar."""
    symbol: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float

    @property
    def mid(self) -> float:
        return (self.high + self.low) / 2

    @property
    def range(self) -> float:
        return self.high - self.low

    @property
    def body(self) -> float:
        return abs(self.close - self.open)

    @property
    def is_bullish(self) -> bool:
        return self.close > self.open


@dataclass
class Tick:
    """Real-time tick data."""
    symbol: str
    timestamp: datetime
    bid: float
    ask: float
    last: float
    volume: float

    @property
    def spread(self) -> float:
        return self.ask - self.bid

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2


class MarketState:
    """Tracks current market state per symbol."""

    def __init__(self):
        self.bars: Dict[str, List[Bar]] = {}
        self.ticks: Dict[str, Tick] = {}
        self._atr_cache: Dict[str, float] = {}

    def update_bar(self, bar: Bar) -> None:
        if bar.symbol not in self.bars:
            self.bars[bar.symbol] = []
        self.bars[bar.symbol].append(bar)
        # Invalidate ATR cache
        self._atr_cache.pop(bar.symbol, None)

    def update_tick(self, tick: Tick) -> None:
        self.ticks[tick.symbol] = tick

    def last_price(self, symbol: str) -> Optional[float]:
        if symbol in self.ticks:
            return self.ticks[symbol].last
        bars = self.bars.get(symbol)
        if bars:
            return bars[-1].close
        return None

    def bar_count(self, symbol: str) -> int:
        return len(self.bars.get(symbol, []))

    def get_bars(self, symbol: str, n: int = 100) -> List[Bar]:
        return self.bars.get(symbol, [])[-n:]

    def atr(self, symbol: str, period: int = 14) -> float:
        if symbol in self._atr_cache:
            return self._atr_cache[symbol]
        bars = self.get_bars(symbol, period + 1)
        if len(bars) < 2:
            return 0.0
        trs = []
        for i in range(1, len(bars)):
            tr = max(
                bars[i].high - bars[i].low,
                abs(bars[i].high - bars[i - 1].close),
                abs(bars[i].low - bars[i - 1].close),
            )
            trs.append(tr)
        atr_val = float(np.mean(trs[-period:]))
        self._atr_cache[symbol] = atr_val
        return atr_val

    def sma(self, symbol: str, period: int) -> Optional[float]:
        bars = self.get_bars(symbol, period)
        if len(bars) < period:
            return None
        return float(np.mean([b.close for b in bars]))

    def ema(self, symbol: str, period: int) -> Optional[float]:
        bars = self.get_bars(symbol, period * 3)
        if len(bars) < period:
            return None
        closes = np.array([b.close for b in bars])
        k = 2 / (period + 1)
        ema = closes[0]
        for c in closes[1:]:
            ema = c * k + ema * (1 - k)
        return float(ema)

    def rsi(self, symbol: str, period: int = 14) -> Optional[float]:
        bars = self.get_bars(symbol, period + 1)
        if len(bars) < period + 1:
            return None
        closes = [b.close for b in bars]
        gains, losses = [], []
        for i in range(1, len(closes)):
            diff = closes[i] - closes[i - 1]
            gains.append(max(diff, 0))
            losses.append(max(-diff, 0))
        avg_gain = np.mean(gains[-period:])
        avg_loss = np.mean(losses[-period:])
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return float(100 - 100 / (1 + rs))

    def vwap(self, symbol: str, period: int = 20) -> Optional[float]:
        bars = self.get_bars(symbol, period)
        if not bars:
            return None
        total_vol = sum(b.volume for b in bars)
        if total_vol == 0:
            return None
        return sum(b.mid * b.volume for b in bars) / total_vol

    def bollinger(
        self, symbol: str, period: int = 20, std_mult: float = 2.0
    ) -> tuple[Optional[float], Optional[float], Optional[float]]:
        """Return (upper, mid, lower) Bollinger Bands."""
        bars = self.get_bars(symbol, period)
        if len(bars) < period:
            return None, None, None
        closes = np.array([b.close for b in bars])
        mid = float(np.mean(closes))
        std = float(np.std(closes))
        return mid + std_mult * std, mid, mid - std_mult * std

    def momentum(self, symbol: str, period: int = 10) -> Optional[float]:
        bars = self.get_bars(symbol, period + 1)
        if len(bars) < period + 1:
            return None
        return (bars[-1].close - bars[-period - 1].close) / bars[-period - 1].close
