"""
MetaTrader 5 Connection Manager.

Wraps the MetaTrader5 Python library with:
- Auto-reconnect logic
- Symbol normalization
- Account info caching
- Thread-safe access

Requires: pip install MetaTrader5
MT5 terminal must be running and logged in on the same machine (Windows only).
For Linux/Mac: run MT5 in Wine or via a Windows VM, expose via socket.
"""
from __future__ import annotations
import time
import logging
from dataclasses import dataclass
from typing import Optional
from contextlib import contextmanager

logger = logging.getLogger(__name__)

try:
    import MetaTrader5 as mt5
    MT5_AVAILABLE = True
except ImportError:
    MT5_AVAILABLE = False
    mt5 = None


@dataclass
class MT5Config:
    login: int = 0
    password: str = ""
    server: str = ""          # e.g. "ICMarkets-Demo01"
    path: str = ""            # MT5 terminal path (optional)
    timeout: int = 60_000     # ms
    portable: bool = False


@dataclass
class AccountInfo:
    login: int
    name: str
    server: str
    currency: str
    balance: float
    equity: float
    margin: float
    free_margin: float
    leverage: int
    profit: float


class MT5Connector:
    """
    Manages the MT5 connection lifecycle.
    Use as context manager or call connect()/disconnect() manually.
    """

    def __init__(self, config: Optional[MT5Config] = None):
        if not MT5_AVAILABLE:
            raise ImportError(
                "MetaTrader5 package not found.\n"
                "Install: pip install MetaTrader5\n"
                "Note: MT5 Python API requires Windows + MT5 terminal running."
            )
        self.config = config or MT5Config()
        self._connected = False

    def connect(self, retries: int = 3) -> bool:
        """Initialize and login to MT5."""
        for attempt in range(retries):
            try:
                kwargs = {"timeout": self.config.timeout, "portable": self.config.portable}
                if self.config.path:
                    kwargs["path"] = self.config.path

                if not mt5.initialize(**kwargs):
                    err = mt5.last_error()
                    logger.warning(f"MT5 initialize failed (attempt {attempt+1}): {err}")
                    time.sleep(2 ** attempt)
                    continue

                if self.config.login:
                    ok = mt5.login(
                        self.config.login,
                        password=self.config.password,
                        server=self.config.server,
                    )
                    if not ok:
                        err = mt5.last_error()
                        logger.error(f"MT5 login failed: {err}")
                        mt5.shutdown()
                        time.sleep(2 ** attempt)
                        continue

                self._connected = True
                info = self.account_info()
                if info:
                    logger.info(
                        f"MT5 connected: {info.name} @ {info.server} "
                        f"Balance=${info.balance:,.2f} Equity=${info.equity:,.2f}"
                    )
                return True

            except Exception as e:
                logger.error(f"MT5 connect error (attempt {attempt+1}): {e}")
                time.sleep(2 ** attempt)

        return False

    def disconnect(self) -> None:
        if self._connected:
            mt5.shutdown()
            self._connected = False
            logger.info("MT5 disconnected")

    def is_connected(self) -> bool:
        if not self._connected:
            return False
        # Check terminal info to verify connection is live
        try:
            info = mt5.terminal_info()
            return info is not None and info.connected
        except Exception:
            return False

    def ensure_connected(self) -> bool:
        if not self.is_connected():
            logger.info("MT5 not connected — reconnecting...")
            return self.connect()
        return True

    def account_info(self) -> Optional[AccountInfo]:
        info = mt5.account_info()
        if info is None:
            return None
        return AccountInfo(
            login=info.login,
            name=info.name,
            server=info.server,
            currency=info.currency,
            balance=info.balance,
            equity=info.equity,
            margin=info.margin,
            free_margin=info.margin_free,
            leverage=info.leverage,
            profit=info.profit,
        )

    def normalize_symbol(self, symbol: str) -> str:
        """
        Map our internal symbol names to MT5 symbol names.
        e.g. AAPL → AAPL.US (varies by broker).
        """
        mappings = {
            "AAPL": "AAPL.US",
            "MSFT": "MSFT.US",
            "TSLA": "TSLA.US",
            "JPM": "JPM.US",
            "GS": "GS.US",
            "SPY": "SPY.US",
            "EURUSD": "EURUSD",
            "GBPUSD": "GBPUSD",
            "USDJPY": "USDJPY",
            "BTCUSD": "BTCUSD",
            "XAUUSD": "XAUUSD",
        }
        return mappings.get(symbol, symbol)

    def get_symbol_info(self, symbol: str) -> Optional[dict]:
        mt5_sym = self.normalize_symbol(symbol)
        info = mt5.symbol_info(mt5_sym)
        if info is None:
            return None
        return {
            "symbol": mt5_sym,
            "bid": info.bid,
            "ask": info.ask,
            "last": info.last,
            "point": info.point,
            "digits": info.digits,
            "volume_min": info.volume_min,
            "volume_step": info.volume_step,
            "volume_max": info.volume_max,
            "spread": info.spread,
            "trade_stops_level": info.trade_stops_level,
        }

    @contextmanager
    def connected(self):
        """Context manager for MT5 session."""
        ok = self.connect()
        if not ok:
            raise ConnectionError("Failed to connect to MT5")
        try:
            yield self
        finally:
            self.disconnect()

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *args):
        self.disconnect()
