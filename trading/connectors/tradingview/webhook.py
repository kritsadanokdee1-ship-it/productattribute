"""
TradingView Webhook Server (FastAPI).

Listens for incoming alerts from TradingView Pine Script strategies/indicators.
Routes each alert through the risk manager and order manager.

Usage:
    uvicorn trading.connectors.tradingview.webhook:app --host 0.0.0.0 --port 8080

TradingView webhook URL: http://YOUR_SERVER:8080/webhook/tv

Pine Script alert message template (JSON):
{
  "secret": "{{strategy.order.id}}",    <- set to your WEBHOOK_SECRET
  "symbol": "{{ticker}}",
  "action": "{{strategy.order.action}}",
  "qty": {{strategy.order.contracts}},
  "price": {{close}},
  "atr": {{ta.atr(14)}},
  "tp_atr_mult": 2.5,
  "sl_atr_mult": 1.2,
  "strategy": "MyStrategy",
  "plan": "PLAN_A_MOMENTUM"
}
"""
from __future__ import annotations
import os
import logging
from datetime import datetime
from typing import Optional, Any

try:
    from fastapi import FastAPI, Request, HTTPException, Header, BackgroundTasks
    from fastapi.responses import JSONResponse
    import uvicorn
    FASTAPI_AVAILABLE = True
except ImportError:
    FASTAPI_AVAILABLE = False

from .alert_parser import TVAlertParser, TVAlertPayload
from ...execution.engine import TradingEngine
from ...execution.risk_manager import RiskManager
from ...core.market_data import MarketState, Bar, Tick

logger = logging.getLogger(__name__)


class TradingViewWebhookServer:
    """
    Standalone webhook server that bridges TradingView alerts
    to our trading engine.
    """

    def __init__(
        self,
        engine: TradingEngine,
        secret: str = "",
        host: str = "0.0.0.0",
        port: int = 8080,
    ):
        if not FASTAPI_AVAILABLE:
            raise ImportError("Install fastapi and uvicorn: pip install fastapi uvicorn")
        self.engine = engine
        self.parser = TVAlertParser(secret=secret)
        self.host = host
        self.port = port
        self.app = FastAPI(title="JP Morgan Trading System — TradingView Bridge")
        self._alert_log: list = []
        self._register_routes()

    def _register_routes(self) -> None:
        app = self.app

        @app.get("/health")
        async def health():
            return {
                "status": "ok",
                "ts": datetime.utcnow().isoformat(),
                "engine_bars": self.engine._bar_count,
                "open_orders": len(self.engine.order_manager.open_orders),
            }

        @app.post("/webhook/tv")
        async def tradingview_webhook(
            request: Request,
            background_tasks: BackgroundTasks,
            x_tv_signature: Optional[str] = Header(default=None),
        ):
            body = await request.body()

            # Signature check
            if not self.parser.verify_signature(body, x_tv_signature or ""):
                raise HTTPException(status_code=401, detail="Invalid signature")

            try:
                payload_dict = await request.json()
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"Invalid JSON: {e}")

            # Validate secret field if set
            if self.parser.secret and payload_dict.get("secret") != self.parser.secret:
                raise HTTPException(status_code=401, detail="Invalid secret")

            try:
                alert = self.parser.parse(payload_dict)
            except ValueError as e:
                raise HTTPException(status_code=422, detail=str(e))

            # Process in background to return fast to TradingView (5s timeout)
            background_tasks.add_task(self._process_alert, alert)

            return JSONResponse({
                "status": "accepted",
                "symbol": alert.symbol,
                "action": alert.action,
                "ts": datetime.utcnow().isoformat(),
            })

        @app.get("/orders/open")
        async def open_orders():
            return {
                "count": len(self.engine.order_manager.open_orders),
                "orders": [
                    {
                        "id": o.order_id,
                        "symbol": o.symbol,
                        "side": o.side.value,
                        "qty": o.fill_qty or o.quantity,
                        "tp": o.tp_level,
                        "sl": o.sl_level,
                        "strategy": o.strategy_id,
                    }
                    for o in self.engine.order_manager.open_orders.values()
                ],
            }

        @app.get("/portfolio")
        async def portfolio():
            return self.engine.status()

        @app.get("/alerts/log")
        async def alert_log():
            return {"alerts": self._alert_log[-50:]}

        @app.post("/orders/cancel")
        async def cancel_all(symbol: Optional[str] = None):
            n = self.engine.order_manager.cancel_all(symbol)
            return {"cancelled": n}

    async def _process_alert(self, alert: TVAlertPayload) -> None:
        """Process a parsed TV alert — submit order or handle close."""
        self._alert_log.append({
            "ts": datetime.utcnow().isoformat(),
            "symbol": alert.symbol,
            "action": alert.action,
            "qty": alert.qty,
            "strategy": alert.strategy,
        })

        if alert.is_close:
            n = self.engine.order_manager.cancel_all(alert.symbol)
            logger.info(f"[TV] CLOSE signal for {alert.symbol} — cancelled {n} pending orders")
            return

        order = alert.to_order()
        if order is None:
            logger.warning(f"[TV] Could not convert alert to order: {alert}")
            return

        prices = {alert.symbol: alert.price or 0}
        approved, reason = self.engine.risk_manager.check_order(
            order, self.engine.portfolio, prices,
            self.engine.order_manager.open_count_by_symbol,
        )
        if approved:
            self.engine.order_manager.submit(order)
            logger.info(f"[TV] Order submitted: {order}")
        else:
            self.engine.risk_manager.log_rejection(order, reason)
            logger.warning(f"[TV] Order rejected: {reason}")

    def run(self) -> None:
        uvicorn.run(self.app, host=self.host, port=self.port)


# Convenience: create a standalone app if engine is provided via env
def create_app_from_env() -> "FastAPI":
    """
    Factory for creating the FastAPI app with engine from environment.
    For use with: uvicorn trading.connectors.tradingview.webhook:app
    """
    if not FASTAPI_AVAILABLE:
        raise ImportError("pip install fastapi uvicorn")

    from ...config.settings import TradingConfig, build_default_strategies
    from ...core.portfolio import Portfolio
    from ...execution.engine import TradingEngine

    capital = float(os.getenv("INITIAL_CAPITAL", "1000000"))
    secret = os.getenv("TV_WEBHOOK_SECRET", "")
    symbols = os.getenv("SYMBOLS", "AAPL,MSFT,TSLA").split(",")

    portfolio = Portfolio(initial_capital=capital)
    strategies = build_default_strategies(symbols)
    engine = TradingEngine(
        portfolio=portfolio,
        strategies=strategies,
        risk_limits=TradingConfig.RISK_LIMITS,
        commission_pct=TradingConfig.COMMISSION_PCT,
    )

    server = TradingViewWebhookServer(engine=engine, secret=secret)
    return server.app


# Module-level app for uvicorn (lazy-initialized)
app: Any = None
try:
    app = create_app_from_env()
except Exception:
    pass  # Will fail without engine config — that's OK for import
