"""
MT5 Order Bridge.

Converts our internal Order objects into MT5 trade requests and executes them.
Handles:
- Market orders with TP/SL (set directly on the MT5 ticket)
- Limit/Stop orders
- Position close
- Order modification (update TP/SL)
"""
from __future__ import annotations
import logging
from typing import Optional
from datetime import datetime

from .connector import MT5Connector
from ...core.order import Order, OrderSide, OrderType, OrderStatus

logger = logging.getLogger(__name__)

try:
    import MetaTrader5 as mt5
    MT5_AVAILABLE = True
except ImportError:
    MT5_AVAILABLE = False
    mt5 = None


class MT5OrderBridge:
    """
    Translates our Order objects into MT5 trade requests.
    Each filled order gets an MT5 ticket stored in order.tags["mt5_ticket"].
    """

    def __init__(self, connector: MT5Connector, magic: int = 20240101):
        if not MT5_AVAILABLE:
            raise ImportError("pip install MetaTrader5")
        self.connector = connector
        self.magic = magic  # EA magic number to identify our orders

    def send_order(self, order: Order) -> tuple[bool, str, Optional[int]]:
        """
        Send order to MT5. Returns (success, message, mt5_ticket).
        """
        if not self.connector.ensure_connected():
            return False, "MT5 not connected", None

        mt5_sym = self.connector.normalize_symbol(order.symbol)
        sym_info = self.connector.get_symbol_info(order.symbol)
        if sym_info is None:
            return False, f"Symbol not found: {mt5_sym}", None

        # Ensure symbol is selected
        mt5.symbol_select(mt5_sym, True)

        # Determine order type
        if order.order_type == OrderType.MARKET:
            if order.side == OrderSide.BUY:
                action = mt5.TRADE_ACTION_DEAL
                order_type = mt5.ORDER_TYPE_BUY
                price = sym_info["ask"]
            else:
                action = mt5.TRADE_ACTION_DEAL
                order_type = mt5.ORDER_TYPE_SELL
                price = sym_info["bid"]
        elif order.order_type == OrderType.LIMIT:
            action = mt5.TRADE_ACTION_PENDING
            if order.side == OrderSide.BUY:
                order_type = mt5.ORDER_TYPE_BUY_LIMIT
            else:
                order_type = mt5.ORDER_TYPE_SELL_LIMIT
            price = order.limit_price
        elif order.order_type == OrderType.STOP:
            action = mt5.TRADE_ACTION_PENDING
            if order.side == OrderSide.BUY:
                order_type = mt5.ORDER_TYPE_BUY_STOP
            else:
                order_type = mt5.ORDER_TYPE_SELL_STOP
            price = order.stop_price
        else:
            return False, f"Unsupported order type: {order.order_type}", None

        # Compute TP/SL from our config
        tp_price, sl_price = order.tpsl.compute_levels(
            price, order.side,
            atr=order.tags.get("atr", 0),
        )

        # Normalize volume to MT5 constraints
        vol_min = sym_info["volume_min"]
        vol_step = sym_info["volume_step"]
        vol_max = sym_info["volume_max"]
        volume = round(max(vol_min, min(vol_max, order.quantity)), 2)

        request = {
            "action": action,
            "symbol": mt5_sym,
            "volume": volume,
            "type": order_type,
            "price": float(price),
            "tp": float(tp_price) if tp_price else 0.0,
            "sl": float(sl_price) if sl_price else 0.0,
            "deviation": 20,           # slippage tolerance in points
            "magic": self.magic,
            "comment": f"{order.strategy_id}|{order.order_id[:6]}",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }

        result = mt5.order_send(request)

        if result is None:
            err = mt5.last_error()
            return False, f"order_send returned None: {err}", None

        if result.retcode != mt5.TRADE_RETCODE_DONE:
            msg = f"MT5 retcode {result.retcode}: {result.comment}"
            logger.error(f"Order failed for {order.order_id}: {msg}")
            return False, msg, None

        ticket = result.order
        order.tags["mt5_ticket"] = ticket
        order.tags["mt5_deal"] = result.deal
        order.fill_price = result.price
        order.fill_qty = result.volume
        order.status = OrderStatus.FILLED
        order.filled_at = datetime.utcnow()

        logger.info(
            f"MT5 order executed: ticket={ticket} {order.side.value} "
            f"{volume} {mt5_sym} @ {result.price:.4f} "
            f"TP={tp_price} SL={sl_price}"
        )
        return True, "OK", ticket

    def modify_tpsl(self, ticket: int, tp: float, sl: float) -> bool:
        """Modify TP/SL on an existing MT5 position by ticket."""
        if not self.connector.ensure_connected():
            return False

        positions = mt5.positions_get(ticket=ticket)
        if not positions:
            logger.warning(f"Position not found: ticket={ticket}")
            return False

        pos = positions[0]
        request = {
            "action": mt5.TRADE_ACTION_SLTP,
            "symbol": pos.symbol,
            "position": ticket,
            "tp": float(tp),
            "sl": float(sl),
            "magic": self.magic,
        }
        result = mt5.order_send(request)
        if result and result.retcode == mt5.TRADE_RETCODE_DONE:
            logger.info(f"Modified ticket {ticket}: TP={tp} SL={sl}")
            return True
        err = mt5.last_error()
        logger.error(f"Modify failed for ticket {ticket}: {err}")
        return False

    def close_position(self, ticket: int, symbol: str, volume: float) -> bool:
        """Close (or partially close) an open MT5 position."""
        if not self.connector.ensure_connected():
            return False

        positions = mt5.positions_get(ticket=ticket)
        if not positions:
            logger.warning(f"Close: position {ticket} not found")
            return False

        pos = positions[0]
        mt5_sym = pos.symbol

        close_type = (
            mt5.ORDER_TYPE_SELL if pos.type == mt5.POSITION_TYPE_BUY
            else mt5.ORDER_TYPE_BUY
        )
        tick = mt5.symbol_info_tick(mt5_sym)
        price = tick.bid if close_type == mt5.ORDER_TYPE_SELL else tick.ask

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": mt5_sym,
            "volume": float(volume),
            "type": close_type,
            "position": ticket,
            "price": float(price),
            "deviation": 20,
            "magic": self.magic,
            "comment": "system_close",
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        result = mt5.order_send(request)
        if result and result.retcode == mt5.TRADE_RETCODE_DONE:
            logger.info(f"Closed ticket {ticket} @ {result.price}")
            return True
        err = mt5.last_error()
        logger.error(f"Close failed for {ticket}: {err}")
        return False

    def close_all(self, symbol: Optional[str] = None) -> int:
        """Close all open positions, optionally filtered by symbol."""
        if not self.connector.ensure_connected():
            return 0

        positions = mt5.positions_get(symbol=symbol) if symbol else mt5.positions_get()
        if not positions:
            return 0

        closed = 0
        for pos in positions:
            if self.close_position(pos.ticket, pos.symbol, pos.volume):
                closed += 1
        return closed
