#!/usr/bin/env python3
"""
Live Trading Runner — MT5 + TradingView Webhook Integration.

This is the entry point for live/paper trading:
  - Connects to MT5 terminal for order execution and market data
  - Starts TradingView webhook server for external signal ingestion
  - Runs all 6 strategy plans in real-time against live bars
  - Enforces full risk management

Usage:
  # Full live mode (MT5 + TV webhook):
  python live_trading.py --mode live --symbols EURUSD,GBPUSD,XAUUSD

  # Paper trading mode (no MT5, just TV webhook + simulated fills):
  python live_trading.py --mode paper --symbols AAPL,MSFT,TSLA

  # TV webhook only (receives external signals, executes on MT5):
  python live_trading.py --mode webhook --port 8080

Environment variables:
  MT5_LOGIN        MT5 account number
  MT5_PASSWORD     MT5 account password
  MT5_SERVER       MT5 broker server name
  TV_SECRET        TradingView webhook secret
  INITIAL_CAPITAL  Starting capital (default: 1000000)
  SYMBOLS          Comma-separated symbol list
"""
from __future__ import annotations
import os
import sys
import signal
import logging
import argparse
import threading
import time
from datetime import datetime
from typing import List, Optional

from trading import Portfolio
from trading.config import TradingConfig, build_default_strategies
from trading.execution import TradingEngine, RiskLimits
from trading.core.market_data import MarketState

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("trading_live.log"),
    ],
)
logger = logging.getLogger("live_trading")


def _parse_args():
    p = argparse.ArgumentParser(description="JP Morgan Trading System — Live Runner")
    p.add_argument("--mode", choices=["live", "paper", "webhook"], default="paper")
    p.add_argument("--symbols", default=os.getenv("SYMBOLS", "EURUSD,GBPUSD,XAUUSD"))
    p.add_argument("--timeframe", default="H1")
    p.add_argument("--capital", type=float, default=float(os.getenv("INITIAL_CAPITAL", "1000000")))
    p.add_argument("--port", type=int, default=8080)
    p.add_argument("--host", default="0.0.0.0")
    return p.parse_args()


def build_engine(symbols: List[str], capital: float) -> TradingEngine:
    portfolio = Portfolio(initial_capital=capital)
    strategies = build_default_strategies(symbols)
    engine = TradingEngine(
        portfolio=portfolio,
        strategies=strategies,
        risk_limits=RiskLimits(
            max_drawdown_pct=0.15,
            max_daily_loss_pct=0.04,
            max_position_pct=0.08,
            min_cash_reserve_pct=0.05,
        ),
        commission_pct=TradingConfig.COMMISSION_PCT,
    )
    engine.risk_manager.reset_daily(capital)
    return engine


def run_live_mode(args) -> None:
    """Full live mode: MT5 data feed + MT5 order execution + TV webhook."""
    try:
        from trading.connectors.mt5 import MT5Connector, MT5Config, MT5DataFeed, MT5OrderBridge, MT5PositionSync
        from trading.connectors.tradingview import TradingViewWebhookServer
    except ImportError as e:
        logger.error(f"Missing dependency: {e}")
        logger.error("Install: pip install MetaTrader5 fastapi uvicorn")
        sys.exit(1)

    symbols = [s.strip() for s in args.symbols.split(",")]
    logger.info(f"Starting LIVE mode | Symbols: {symbols} | TF: {args.timeframe}")

    # 1. Build engine
    engine = build_engine(symbols, args.capital)

    # 2. Connect to MT5
    config = MT5Config(
        login=int(os.getenv("MT5_LOGIN", "0")),
        password=os.getenv("MT5_PASSWORD", ""),
        server=os.getenv("MT5_SERVER", ""),
    )
    connector = MT5Connector(config)
    if not connector.connect():
        logger.error("Failed to connect to MT5. Check terminal is running.")
        sys.exit(1)

    # 3. Sync existing positions
    sync = MT5PositionSync(connector, engine.portfolio)
    imported = sync.import_existing_positions()
    logger.info(f"Imported {imported} existing MT5 positions")
    equity = sync.sync_account_equity()
    if equity:
        engine.portfolio.cash = equity
        engine.portfolio.initial_capital = equity

    # 4. Start data feed
    feed = MT5DataFeed(
        connector=connector,
        market_state=engine.market,
        symbols=symbols,
        timeframe=args.timeframe,
        lookback_bars=500,
        poll_interval_sec=60.0,
    )
    logger.info("Backfilling historical data...")
    n_bars = feed.backfill()
    logger.info(f"Backfilled {n_bars} bars")

    # 5. Wire new bars → engine + MT5 order execution
    order_bridge = MT5OrderBridge(connector)

    def on_new_bar(bar):
        events = engine.on_bar(bar)
        for ev in events:
            if ev["event"] == "ORDER_SUBMITTED":
                oid = ev["order_id"]
                order = engine.order_manager.open_orders.get(oid)
                if order:
                    ok, msg, ticket = order_bridge.send_order(order)
                    if ok:
                        logger.info(f"MT5 order sent: {oid} ticket={ticket}")
                    else:
                        logger.error(f"MT5 order failed: {msg}")
        # Log equity every bar
        prices = {sym: engine.market.last_price(sym) for sym in symbols}
        prices = {k: v for k, v in prices.items() if v}
        snap = engine.portfolio.snapshot(prices, bar.timestamp)
        logger.info(
            f"Bar {bar.symbol} @ {bar.close:.4f} | "
            f"Equity=${snap.equity:,.2f} | DD={snap.drawdown:.1%}"
        )

    feed.on_bar(on_new_bar)
    feed.start()

    # 6. Start TV webhook
    tv_secret = os.getenv("TV_SECRET", "")
    tv_server = TradingViewWebhookServer(engine, secret=tv_secret, host=args.host, port=args.port)

    def shutdown(sig, frame):
        logger.info("Shutting down...")
        feed.stop()
        connector.disconnect()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    logger.info(f"TradingView webhook: http://{args.host}:{args.port}/webhook/tv")
    tv_server.run()  # Blocks


def run_paper_mode(args) -> None:
    """Paper trading: TV webhook receives signals, fills simulated locally."""
    try:
        from trading.connectors.tradingview import TradingViewWebhookServer
    except ImportError as e:
        logger.error(f"Missing dependency: {e}\nInstall: pip install fastapi uvicorn")
        sys.exit(1)

    symbols = [s.strip() for s in args.symbols.split(",")]
    logger.info(f"Starting PAPER mode | Symbols: {symbols}")

    engine = build_engine(symbols, args.capital)
    tv_secret = os.getenv("TV_SECRET", "")
    server = TradingViewWebhookServer(engine, secret=tv_secret, host=args.host, port=args.port)

    logger.info(f"Paper trading started. Webhook at http://{args.host}:{args.port}/webhook/tv")
    logger.info(f"Portfolio dashboard:  http://{args.host}:{args.port}/portfolio")
    server.run()


def run_webhook_mode(args) -> None:
    """Webhook only mode — just start the HTTP server."""
    run_paper_mode(args)


def print_setup_info(args) -> None:
    from trading.connectors.tradingview import print_setup_guide
    print_setup_guide()
    print(f"\nStarting server at http://{args.host}:{args.port}")
    print(f"Symbols: {args.symbols}")
    print(f"Mode: {args.mode.upper()}")
    print(f"Initial capital: ${args.capital:,.0f}\n")


if __name__ == "__main__":
    args = _parse_args()
    print_setup_info(args)

    if args.mode == "live":
        run_live_mode(args)
    elif args.mode in ("paper", "webhook"):
        run_paper_mode(args)
