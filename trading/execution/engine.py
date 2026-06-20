"""
Trading Engine: orchestrates strategies, risk checks, order management.
"""
from __future__ import annotations
from datetime import datetime
from typing import Dict, List, Optional

from ..core.market_data import Bar, MarketState
from ..core.portfolio import Portfolio
from ..strategies.base import BaseStrategy
from .order_manager import OrderManager
from .risk_manager import RiskManager, RiskLimits


class TradingEngine:
    """
    Central orchestrator. Per bar:
    1. Update market state
    2. Run all strategies -> collect candidate orders
    3. Risk-check each order
    4. Submit approved orders to OrderManager
    5. Process fills and TP/SL events
    6. Snapshot portfolio
    """

    def __init__(
        self,
        portfolio: Portfolio,
        strategies: List[BaseStrategy],
        risk_limits: Optional[RiskLimits] = None,
        commission_pct: float = 0.0005,
    ):
        self.portfolio = portfolio
        self.strategies = strategies
        self.market = MarketState()
        self.order_manager = OrderManager(commission_pct=commission_pct)
        self.risk_manager = RiskManager(risk_limits)
        self._bar_count = 0
        self._event_log: List[dict] = []

    def on_bar(self, bar: Bar) -> List[dict]:
        """Process a new OHLCV bar. Returns events generated this bar."""
        self.market.update_bar(bar)
        self._bar_count += 1
        events = []

        prices = {sym: self.market.last_price(sym) for sym in self.market.bars}
        prices = {k: v for k, v in prices.items() if v is not None}

        # 1. Process existing orders (fills + TP/SL checks)
        bar_events = self.order_manager.process_bar(bar, self.market, self.portfolio)
        for order, price, etype in bar_events:
            events.append({
                "ts": bar.timestamp.isoformat(),
                "symbol": bar.symbol,
                "event": etype,
                "order_id": order.order_id,
                "price": price,
                "pnl": round(order.realized_pnl, 2),
                "strategy": order.strategy_id,
                "plan": order.plan_id,
            })

        # 2. Run strategies every bar
        for strategy in self.strategies:
            if not strategy.config.enabled:
                continue
            if bar.symbol not in strategy.config.symbols:
                continue

            pos = self.portfolio.get_position(bar.symbol)
            equity = self.portfolio.equity(prices)
            candidate_orders = strategy.generate_signals(
                bar.symbol, self.market, equity, pos.quantity
            )

            for order in candidate_orders:
                approved, reason = self.risk_manager.check_order(
                    order, self.portfolio, prices,
                    self.order_manager.open_count_by_symbol,
                )
                if approved:
                    self.order_manager.submit(order)
                    events.append({
                        "ts": bar.timestamp.isoformat(),
                        "symbol": bar.symbol,
                        "event": "ORDER_SUBMITTED",
                        "order_id": order.order_id,
                        "side": order.side.value,
                        "qty": order.quantity,
                        "strategy": order.strategy_id,
                        "plan": order.plan_id,
                    })
                else:
                    self.risk_manager.log_rejection(order, reason)
                    events.append({
                        "ts": bar.timestamp.isoformat(),
                        "symbol": bar.symbol,
                        "event": "ORDER_REJECTED",
                        "order_id": order.order_id,
                        "reason": reason,
                        "strategy": order.strategy_id,
                    })

        # 3. Snapshot portfolio
        snap = self.portfolio.snapshot(prices, bar.timestamp)

        self._event_log.extend(events)
        return events

    def run(self, bars: List[Bar]) -> dict:
        """Run engine over a list of bars. Returns final report."""
        for bar in bars:
            self.on_bar(bar)

        prices = {}
        for sym in self.market.bars:
            p = self.market.last_price(sym)
            if p:
                prices[sym] = p

        return {
            "portfolio": self.portfolio.summary(prices),
            "risk": self.risk_manager.summary(),
            "fills": self.order_manager.fill_log(),
            "total_events": len(self._event_log),
            "bars_processed": self._bar_count,
        }

    def status(self) -> dict:
        prices = {}
        for sym in self.market.bars:
            p = self.market.last_price(sym)
            if p:
                prices[sym] = p
        return {
            "bars_processed": self._bar_count,
            "open_orders": len(self.order_manager.open_orders),
            "filled_orders": len(self.order_manager.filled_orders),
            "portfolio": self.portfolio.summary(prices),
        }
