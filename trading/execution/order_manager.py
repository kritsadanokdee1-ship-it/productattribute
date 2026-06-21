"""
Order Manager: tracks all open orders, processes fills, checks TP/SL every bar.
"""
from __future__ import annotations
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from ..core.order import Order, OrderStatus, OrderSide, OrderType
from ..core.market_data import Bar, MarketState
from ..core.portfolio import Portfolio


class OrderManager:
    """
    Manages the full lifecycle of orders:
    - Submit -> validate -> fill
    - Monitor active orders for TP/SL hits every bar
    - Track order history
    """

    def __init__(self, commission_pct: float = 0.0005):
        self.commission_pct = commission_pct
        self.open_orders: Dict[str, Order] = {}      # order_id -> Order
        self.filled_orders: List[Order] = []
        self.cancelled_orders: List[Order] = []
        self._fill_log: List[dict] = []

    @property
    def open_count_by_symbol(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for o in self.open_orders.values():
            counts[o.symbol] = counts.get(o.symbol, 0) + 1
        return counts

    def submit(self, order: Order) -> None:
        """Accept a new order into pending queue."""
        order.status = OrderStatus.PENDING
        self.open_orders[order.order_id] = order

    def process_bar(
        self,
        bar: Bar,
        market: MarketState,
        portfolio: Portfolio,
    ) -> List[Tuple[Order, float, str]]:
        """
        Process a new bar for all open orders on this symbol.
        Returns list of (order, fill_price, event_type) events.
        event_type: 'FILL' | 'TP' | 'SL'
        """
        events = []
        orders_to_process = [
            o for o in self.open_orders.values()
            if o.symbol == bar.symbol
        ]

        for order in orders_to_process:
            if order.status == OrderStatus.PENDING:
                # Try to fill
                fill_price = self._try_fill(order, bar)
                if fill_price is not None:
                    self._fill_order(order, fill_price, order.quantity, portfolio, market)
                    events.append((order, fill_price, "FILL"))

            elif order.is_active:
                # Update trailing stops
                order.update_trailing_sl(bar.close)
                # Check TP/SL
                hit = order.check_tpsl_hit(bar.high, bar.low)
                if hit == "TP":
                    self._close_order(order, order.tp_level, portfolio, bar.timestamp, "TP_HIT")
                    events.append((order, order.tp_level, "TP"))
                elif hit == "SL":
                    self._close_order(order, order.sl_level, portfolio, bar.timestamp, "SL_HIT")
                    events.append((order, order.sl_level, "SL"))

        return events

    def _try_fill(self, order: Order, bar: Bar) -> Optional[float]:
        """Determine fill price. Returns None if not filled this bar."""
        if order.order_type == OrderType.MARKET:
            return bar.open  # Fill at bar open (realistic)
        elif order.order_type == OrderType.LIMIT:
            if order.side == OrderSide.BUY and bar.low <= order.limit_price:
                return order.limit_price
            elif order.side == OrderSide.SELL and bar.high >= order.limit_price:
                return order.limit_price
        elif order.order_type == OrderType.STOP:
            if order.side == OrderSide.BUY and bar.high >= order.stop_price:
                return order.stop_price
            elif order.side == OrderSide.SELL and bar.low <= order.stop_price:
                return order.stop_price
        return None

    def _fill_order(
        self,
        order: Order,
        fill_price: float,
        fill_qty: float,
        portfolio: Portfolio,
        market: MarketState,
    ) -> None:
        atr = market.atr(order.symbol, 14)
        commission = fill_price * fill_qty * self.commission_pct
        portfolio.apply_fill(order, fill_price, fill_qty, commission)
        order.set_tpsl_from_fill(fill_price, atr)
        order.status = OrderStatus.FILLED
        self.open_orders.pop(order.order_id, None)
        self.open_orders[order.order_id] = order  # re-register as active (watching TP/SL)
        order.status = OrderStatus.OPEN

        self._fill_log.append({
            "ts": datetime.utcnow().isoformat(),
            "order_id": order.order_id,
            "symbol": order.symbol,
            "side": order.side.value,
            "qty": fill_qty,
            "fill": fill_price,
            "tp": order.tp_level,
            "sl": order.sl_level,
            "rrr": round(order.risk_reward_ratio, 2),
            "strategy": order.strategy_id,
        })

    def _close_order(
        self,
        order: Order,
        close_price: float,
        portfolio: Portfolio,
        ts: datetime,
        reason: str,
    ) -> None:
        direction = 1 if order.side == OrderSide.BUY else -1
        commission = close_price * order.fill_qty * self.commission_pct

        # Closing a LONG means selling → receive close_price * qty.
        # Closing a SHORT means buying → pay close_price * qty.
        # Cash was deducted/credited by full value at entry, so credit full close proceeds here.
        proceeds = direction * close_price * order.fill_qty
        portfolio.cash += proceeds - commission
        portfolio._total_commission += commission

        pnl = direction * (close_price - order.fill_price) * order.fill_qty - commission
        order.realized_pnl += pnl
        portfolio.get_position(order.symbol).realized_pnl += pnl
        portfolio.get_position(order.symbol).quantity = 0.0
        order.closed_at = ts
        order.status = (
            OrderStatus.TP_HIT if reason == "TP_HIT" else OrderStatus.SL_HIT
        )
        self.open_orders.pop(order.order_id, None)
        self.filled_orders.append(order)
        portfolio.closed_trades.append(order)

        self._fill_log.append({
            "ts": ts.isoformat(),
            "order_id": order.order_id,
            "symbol": order.symbol,
            "event": reason,
            "close_price": close_price,
            "pnl": round(pnl, 2),
        })

    def cancel_all(self, symbol: Optional[str] = None) -> int:
        to_cancel = [
            o for o in self.open_orders.values()
            if (symbol is None or o.symbol == symbol) and o.status == OrderStatus.PENDING
        ]
        for o in to_cancel:
            o.status = OrderStatus.CANCELLED
            self.cancelled_orders.append(o)
            del self.open_orders[o.order_id]
        return len(to_cancel)

    def fill_log(self) -> List[dict]:
        return self._fill_log
