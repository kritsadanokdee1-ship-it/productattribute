"""
TradingView Webhook Alert Parser.

TradingView sends POST requests with JSON bodies when Pine Script alerts fire.
This module parses those payloads into our Order objects.

Example Pine Script alert message JSON:
{
  "symbol": "AAPL",
  "action": "buy",
  "qty": 100,
  "tp_pct": 0.02,
  "sl_pct": 0.01,
  "strategy": "MomentumEMA",
  "plan": "PLAN_A",
  "price": {{close}},
  "atr": {{atr(14)}},
  "secret": "YOUR_WEBHOOK_SECRET"
}
"""
from __future__ import annotations
import hmac
import hashlib
import json
from typing import Optional, Any
from dataclasses import dataclass

from ...core.order import Order, OrderSide, OrderType, TPSLConfig, TPSLType


@dataclass
class TVAlertPayload:
    """Parsed TradingView alert."""
    symbol: str
    action: str           # "buy" | "sell" | "close" | "close_buy" | "close_sell"
    qty: float
    price: Optional[float] = None
    atr: Optional[float] = None
    tp_pct: Optional[float] = None
    sl_pct: Optional[float] = None
    tp_price: Optional[float] = None
    sl_price: Optional[float] = None
    tp_atr_mult: Optional[float] = None
    sl_atr_mult: Optional[float] = None
    strategy: str = "TradingView"
    plan: str = "TV_ALERT"
    comment: str = ""
    raw: dict = None

    @property
    def side(self) -> Optional[OrderSide]:
        a = self.action.lower()
        if a in ("buy", "long", "entry_long"):
            return OrderSide.BUY
        if a in ("sell", "short", "entry_short"):
            return OrderSide.SELL
        return None

    @property
    def is_close(self) -> bool:
        return self.action.lower().startswith("close")

    def to_order(self, portfolio_value: float = 0) -> Optional[Order]:
        """Convert alert to an Order. Returns None for close/unsupported actions."""
        side = self.side
        if side is None:
            return None

        # Determine TP/SL config
        if self.tp_price and self.sl_price:
            tpsl = TPSLConfig(
                tp_type=TPSLType.FIXED, sl_type=TPSLType.FIXED,
                tp_price=self.tp_price, sl_price=self.sl_price,
            )
        elif self.atr and self.tp_atr_mult and self.sl_atr_mult:
            tpsl = TPSLConfig(
                tp_type=TPSLType.ATR, sl_type=TPSLType.TRAILING,
                tp_atr_mult=self.tp_atr_mult, sl_atr_mult=self.sl_atr_mult,
                trail_amount=self.atr * self.sl_atr_mult,
            )
        elif self.tp_pct and self.sl_pct:
            tpsl = TPSLConfig(
                tp_type=TPSLType.PERCENT, sl_type=TPSLType.PERCENT,
                tp_pct=self.tp_pct, sl_pct=self.sl_pct,
            )
        else:
            # Default: 2% TP, 1% SL
            tpsl = TPSLConfig(
                tp_type=TPSLType.PERCENT, sl_type=TPSLType.PERCENT,
                tp_pct=0.02, sl_pct=0.01,
            )

        return Order(
            symbol=self.symbol.upper(),
            side=side,
            quantity=self.qty,
            order_type=OrderType.MARKET,
            tpsl=tpsl,
            strategy_id=self.strategy,
            plan_id=self.plan,
            tags={"source": "tradingview", "comment": self.comment},
        )


class TVAlertParser:
    """Parses and authenticates TradingView webhook payloads."""

    REQUIRED_FIELDS = ("symbol", "action", "qty")

    def __init__(self, secret: str = ""):
        self.secret = secret

    def verify_signature(self, body: bytes, signature: str) -> bool:
        """HMAC-SHA256 signature check (optional but recommended)."""
        if not self.secret:
            return True
        expected = hmac.new(
            self.secret.encode(), body, hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(expected, signature)

    def parse(self, payload: dict | str) -> TVAlertPayload:
        """Parse raw alert dict or JSON string into TVAlertPayload."""
        if isinstance(payload, str):
            payload = json.loads(payload)

        for field in self.REQUIRED_FIELDS:
            if field not in payload:
                raise ValueError(f"Missing required field: {field}")

        return TVAlertPayload(
            symbol=str(payload["symbol"]).upper().replace("/", ""),
            action=str(payload["action"]).lower(),
            qty=float(payload["qty"]),
            price=float(payload["price"]) if "price" in payload else None,
            atr=float(payload["atr"]) if "atr" in payload else None,
            tp_pct=float(payload["tp_pct"]) if "tp_pct" in payload else None,
            sl_pct=float(payload["sl_pct"]) if "sl_pct" in payload else None,
            tp_price=float(payload["tp_price"]) if "tp_price" in payload else None,
            sl_price=float(payload["sl_price"]) if "sl_price" in payload else None,
            tp_atr_mult=float(payload["tp_atr_mult"]) if "tp_atr_mult" in payload else None,
            sl_atr_mult=float(payload["sl_atr_mult"]) if "sl_atr_mult" in payload else None,
            strategy=str(payload.get("strategy", "TradingView")),
            plan=str(payload.get("plan", "TV_ALERT")),
            comment=str(payload.get("comment", "")),
            raw=payload,
        )
