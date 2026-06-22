"""
MT5 Live Data Feed.

Pulls OHLCV bars and tick data from MT5 and feeds them into our MarketState.
Supports both historical backfill and live streaming via polling.
"""
from __future__ import annotations
import time
import threading
import logging
from datetime import datetime, timezone
from typing import List, Optional, Callable, Dict

from .connector import MT5Connector
from ...core.market_data import Bar, Tick, MarketState

logger = logging.getLogger(__name__)

try:
    import MetaTrader5 as mt5
    import numpy as np
    MT5_AVAILABLE = True
except ImportError:
    MT5_AVAILABLE = False
    mt5 = None


# MT5 timeframe constants mapping
TIMEFRAMES = {
    "M1":  mt5.TIMEFRAME_M1  if MT5_AVAILABLE else 1,
    "M5":  mt5.TIMEFRAME_M5  if MT5_AVAILABLE else 5,
    "M15": mt5.TIMEFRAME_M15 if MT5_AVAILABLE else 15,
    "M30": mt5.TIMEFRAME_M30 if MT5_AVAILABLE else 30,
    "H1":  mt5.TIMEFRAME_H1  if MT5_AVAILABLE else 60,
    "H4":  mt5.TIMEFRAME_H4  if MT5_AVAILABLE else 240,
    "D1":  mt5.TIMEFRAME_D1  if MT5_AVAILABLE else 1440,
}


class MT5DataFeed:
    """
    Fetches OHLCV bars from MT5 and updates MarketState.
    Can run in background thread for live trading.
    """

    def __init__(
        self,
        connector: MT5Connector,
        market_state: MarketState,
        symbols: List[str],
        timeframe: str = "H1",
        lookback_bars: int = 500,
        poll_interval_sec: float = 60.0,
    ):
        if not MT5_AVAILABLE:
            raise ImportError("pip install MetaTrader5")
        self.connector = connector
        self.market = market_state
        self.symbols = symbols
        self.timeframe = timeframe
        self.tf_const = TIMEFRAMES.get(timeframe, mt5.TIMEFRAME_H1)
        self.lookback_bars = lookback_bars
        self.poll_interval = poll_interval_sec
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._on_bar_callbacks: List[Callable[[Bar], None]] = []
        self._last_bar_time: Dict[str, datetime] = {}

    def on_bar(self, callback: Callable[[Bar], None]) -> None:
        """Register callback to be called when a new bar is received."""
        self._on_bar_callbacks.append(callback)

    def fetch_bars(self, symbol: str, n: int = None) -> List[Bar]:
        """Pull latest N bars from MT5 for symbol."""
        if not self.connector.ensure_connected():
            logger.error("MT5 not connected")
            return []

        mt5_sym = self.connector.normalize_symbol(symbol)
        n = n or self.lookback_bars

        rates = mt5.copy_rates_from_pos(mt5_sym, self.tf_const, 0, n)
        if rates is None or len(rates) == 0:
            err = mt5.last_error()
            logger.warning(f"No bars for {mt5_sym}: {err}")
            return []

        bars = []
        for r in rates:
            ts = datetime.fromtimestamp(r["time"], tz=timezone.utc).replace(tzinfo=None)
            bars.append(Bar(
                symbol=symbol,
                timestamp=ts,
                open=float(r["open"]),
                high=float(r["high"]),
                low=float(r["low"]),
                close=float(r["close"]),
                volume=float(r["tick_volume"]),
            ))
        return bars

    def fetch_tick(self, symbol: str) -> Optional[Tick]:
        """Get latest bid/ask/last for symbol."""
        if not self.connector.ensure_connected():
            return None
        mt5_sym = self.connector.normalize_symbol(symbol)
        tick = mt5.symbol_info_tick(mt5_sym)
        if tick is None:
            return None
        return Tick(
            symbol=symbol,
            timestamp=datetime.fromtimestamp(tick.time, tz=timezone.utc).replace(tzinfo=None),
            bid=float(tick.bid),
            ask=float(tick.ask),
            last=float(tick.last) if tick.last else float(tick.bid),
            volume=float(tick.volume),
        )

    def backfill(self) -> int:
        """Load historical bars for all symbols into market state."""
        total = 0
        for sym in self.symbols:
            bars = self.fetch_bars(sym, self.lookback_bars)
            for bar in bars:
                self.market.update_bar(bar)
            total += len(bars)
            logger.info(f"Backfilled {len(bars)} bars for {sym}")
        return total

    def start(self) -> None:
        """Start background polling thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()
        logger.info(f"MT5 data feed started ({self.timeframe}, {len(self.symbols)} symbols)")

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=10)
        logger.info("MT5 data feed stopped")

    def _poll_loop(self) -> None:
        while self._running:
            for sym in self.symbols:
                try:
                    # Get latest 2 bars; if newest bar time changed → new bar
                    bars = self.fetch_bars(sym, 2)
                    if bars:
                        latest = bars[-1]
                        last_time = self._last_bar_time.get(sym)
                        if last_time is None or latest.timestamp > last_time:
                            self._last_bar_time[sym] = latest.timestamp
                            self.market.update_bar(latest)
                            for cb in self._on_bar_callbacks:
                                cb(latest)
                            logger.debug(f"New bar: {sym} @ {latest.close:.4f}")

                    # Also update tick data
                    tick = self.fetch_tick(sym)
                    if tick:
                        self.market.update_tick(tick)

                except Exception as e:
                    logger.error(f"Feed error for {sym}: {e}")

            time.sleep(self.poll_interval)
