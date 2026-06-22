"""
MT5 Position Synchronizer.

Keeps our internal Portfolio in sync with MT5's actual positions.
Reconciles on startup and can run periodic drift checks.
"""
from __future__ import annotations
import logging
from datetime import datetime
from typing import List, Dict, Optional

from .connector import MT5Connector, AccountInfo
from ...core.portfolio import Portfolio
from ...core.position import Position
from ...core.order import Order, OrderSide, OrderStatus

logger = logging.getLogger(__name__)

try:
    import MetaTrader5 as mt5
    MT5_AVAILABLE = True
except ImportError:
    MT5_AVAILABLE = False
    mt5 = None


class MT5PositionSync:
    """
    Syncs MT5 open positions with our internal Portfolio.
    - On startup: imports existing MT5 positions
    - Periodic: checks for orphaned positions (closed by SL/TP on MT5 side)
    - Provides real account equity from MT5
    """

    def __init__(self, connector: MT5Connector, portfolio: Portfolio):
        if not MT5_AVAILABLE:
            raise ImportError("pip install MetaTrader5")
        self.connector = connector
        self.portfolio = portfolio

    def get_mt5_positions(self) -> List[dict]:
        """Return all currently open MT5 positions."""
        if not self.connector.ensure_connected():
            return []
        positions = mt5.positions_get()
        if positions is None:
            return []
        result = []
        for pos in positions:
            result.append({
                "ticket": pos.ticket,
                "symbol": pos.symbol,
                "type": "BUY" if pos.type == mt5.POSITION_TYPE_BUY else "SELL",
                "volume": pos.volume,
                "open_price": pos.price_open,
                "current_price": pos.price_current,
                "sl": pos.sl,
                "tp": pos.tp,
                "profit": pos.profit,
                "swap": pos.swap,
                "open_time": datetime.fromtimestamp(pos.time),
                "comment": pos.comment,
                "magic": pos.magic,
            })
        return result

    def get_mt5_history(self, from_dt: datetime, to_dt: Optional[datetime] = None) -> List[dict]:
        """Fetch closed deal history."""
        if not self.connector.ensure_connected():
            return []
        to_dt = to_dt or datetime.utcnow()
        deals = mt5.history_deals_get(from_dt, to_dt)
        if deals is None:
            return []
        return [
            {
                "ticket": d.ticket,
                "order": d.order,
                "symbol": d.symbol,
                "type": d.type,
                "volume": d.volume,
                "price": d.price,
                "profit": d.profit,
                "commission": d.commission,
                "swap": d.swap,
                "time": datetime.fromtimestamp(d.time),
                "comment": d.comment,
            }
            for d in deals
        ]

    def import_existing_positions(self, symbol_map: Optional[Dict[str, str]] = None) -> int:
        """
        On startup: import MT5 open positions into our portfolio.
        symbol_map: {mt5_symbol → internal_symbol}
        """
        positions = self.get_mt5_positions()
        imported = 0

        for pos in positions:
            sym = pos["symbol"]
            # Reverse-map MT5 symbol to internal name
            if symbol_map:
                sym = {v: k for k, v in symbol_map.items()}.get(sym, sym)

            side = OrderSide.BUY if pos["type"] == "BUY" else OrderSide.SELL
            internal_pos = self.portfolio.get_position(sym)

            if internal_pos.is_flat:
                # Reconstruct position
                internal_pos.quantity = pos["volume"] * (1 if side == OrderSide.BUY else -1)
                internal_pos.avg_entry_price = pos["open_price"]
                internal_pos.opened_at = pos["open_time"]

                # Create a synthetic filled order to represent this
                order = Order(
                    symbol=sym,
                    side=side,
                    quantity=pos["volume"],
                    strategy_id="MT5_IMPORT",
                    plan_id="IMPORTED",
                )
                order.status = OrderStatus.OPEN
                order.fill_price = pos["open_price"]
                order.fill_qty = pos["volume"]
                order.tp_level = pos["tp"] if pos["tp"] != 0 else None
                order.sl_level = pos["sl"] if pos["sl"] != 0 else None
                order.tags["mt5_ticket"] = pos["ticket"]
                internal_pos.orders.append(order)

                # Adjust portfolio cash to account for the position
                cost = pos["open_price"] * pos["volume"] * (
                    -1 if side == OrderSide.BUY else 1
                )
                self.portfolio.cash += cost
                imported += 1
                logger.info(
                    f"Imported MT5 position: {sym} {pos['type']} "
                    f"{pos['volume']} @ {pos['open_price']} "
                    f"TP={pos['tp']} SL={pos['sl']}"
                )

        return imported

    def reconcile(self) -> Dict[str, list]:
        """
        Check for positions that exist in MT5 but not in our portfolio
        (e.g. manual trades, EA trades) and vice versa.
        Returns {"missing_internal": [...], "missing_mt5": [...]}.
        """
        mt5_positions = {p["ticket"]: p for p in self.get_mt5_positions()}
        internal_tickets = set()

        for pos in self.portfolio.positions.values():
            for order in pos.orders:
                t = order.tags.get("mt5_ticket")
                if t:
                    internal_tickets.add(t)

        missing_internal = [
            p for ticket, p in mt5_positions.items()
            if ticket not in internal_tickets
        ]
        missing_mt5 = [
            {"symbol": sym, "position": str(pos)}
            for sym, pos in self.portfolio.positions.items()
            if not pos.is_flat and not any(
                o.tags.get("mt5_ticket") in mt5_positions
                for o in pos.orders
            )
        ]

        if missing_internal:
            logger.warning(f"Positions in MT5 but not in system: {[p['symbol'] for p in missing_internal]}")
        if missing_mt5:
            logger.warning(f"Positions in system but not in MT5: {[p['symbol'] for p in missing_mt5]}")

        return {"missing_internal": missing_internal, "missing_mt5": missing_mt5}

    def sync_account_equity(self) -> Optional[float]:
        """Update portfolio initial capital/cash from real MT5 account balance."""
        info: Optional[AccountInfo] = self.connector.account_info()
        if info is None:
            return None
        logger.info(
            f"MT5 Account: balance={info.balance:,.2f} equity={info.equity:,.2f} "
            f"free_margin={info.free_margin:,.2f} profit={info.profit:,.2f}"
        )
        return info.equity
