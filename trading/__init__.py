"""
JP Morgan-style Multi-Strategy Trading System
"""
__version__ = "1.0.0"

from .core import Order, OrderSide, OrderType, OrderStatus, TPSLConfig, TPSLType
from .core import Position, Portfolio, Bar, Tick, MarketState
from .execution import TradingEngine, OrderManager, RiskManager, RiskLimits
from .backtest import Backtester, BacktestConfig
from .data import MarketDataGenerator
from .config import TradingConfig, build_default_strategies
