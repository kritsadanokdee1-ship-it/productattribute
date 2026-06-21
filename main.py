#!/usr/bin/env python3
"""
JP Morgan Trading System - Main Entry Point
Runs a full multi-strategy backtest across 6 trading plans.
"""
import sys
import json
from datetime import datetime

from trading import (
    MarketDataGenerator,
    Backtester, BacktestConfig,
    TradingConfig, build_default_strategies,
)
from trading.execution.risk_manager import RiskLimits
from trading.strategies import PairConfig


def run_backtest(n_bars: int = 300, seed: int = 42) -> None:
    print(f"\nJP Morgan Trading System v1.0")
    print(f"{'─' * 50}")
    print(f"Generating synthetic market data ({n_bars} bars per symbol)...")

    gen = MarketDataGenerator(seed=seed)
    symbols = TradingConfig.SYMBOLS_EQUITY
    bars_by_symbol = {}

    # Generate main equity symbols
    for i, sym in enumerate(symbols):
        start_price = {"AAPL": 185.0, "MSFT": 375.0, "JPM": 200.0, "GS": 450.0, "TSLA": 250.0}[sym]
        mu = [0.0003, 0.0003, 0.0002, 0.0002, 0.0004][i]
        sigma = [0.012, 0.011, 0.010, 0.011, 0.020][i]
        bars_by_symbol[sym] = gen.generate_gbm_bars(
            sym, start_price=start_price, n_bars=n_bars,
            mu=mu, sigma=sigma, regime_shift=True, fat_tails=True,
        )

    # Generate correlated pairs (overwrites individual bars)
    for sym_a, sym_b in [("JPM", "GS"), ("AAPL", "MSFT")]:
        pa = {"JPM": 200.0, "AAPL": 185.0}[sym_a]
        pb = {"GS": 450.0, "MSFT": 375.0}[sym_b]
        bars_a, bars_b = gen.generate_correlated_pair(
            sym_a, sym_b,
            start_price_a=pa, start_price_b=pb,
            n_bars=n_bars, correlation=0.82,
            mean_reversion_speed=0.15,
        )
        bars_by_symbol[sym_a] = bars_a
        bars_by_symbol[sym_b] = bars_b

    print(f"Generated {sum(len(v) for v in bars_by_symbol.values())} total bars across {len(bars_by_symbol)} symbols")
    print(f"\nBuilding trading plans...")

    strategies = build_default_strategies(symbols)
    plan_names = [s.config.plan_id for s in strategies]
    for name in plan_names:
        print(f"  + {name}")

    config = BacktestConfig(
        initial_capital=TradingConfig.INITIAL_CAPITAL,
        commission_pct=TradingConfig.COMMISSION_PCT,
        risk_limits=TradingConfig.RISK_LIMITS,
    )

    print(f"\nRunning backtest with ${config.initial_capital:,.0f} initial capital...")
    print(f"Commission: {config.commission_pct * 100:.3f}% per side")
    backtester = Backtester(strategies=strategies, config=config)
    result = backtester.run(bars_by_symbol)

    backtester.print_report(result)

    # Save detailed results to JSON
    output = {
        "run_at": datetime.utcnow().isoformat(),
        "config": {
            "initial_capital": config.initial_capital,
            "commission_pct": config.commission_pct,
            "symbols": symbols,
            "n_bars": n_bars,
        },
        "portfolio_summary": result.portfolio_summary,
        "trade_analysis": result.trade_analysis,
        "risk_summary": result.risk_summary,
        "equity_curve": result.equity_curve,
        "recent_fills": result.fill_log,
    }
    with open("backtest_results.json", "w") as f:
        json.dump(output, f, indent=2, default=str)
    print(f"\nDetailed results saved to backtest_results.json")

    from trading.reporting import generate_html_report
    generate_html_report("backtest_results.json", "trading_report.html")


def run_live_demo(n_ticks: int = 50) -> None:
    """Demo: simulate live bar-by-bar processing."""
    from trading import TradingEngine, Portfolio
    from trading.execution.risk_manager import RiskLimits

    print(f"\n{'─' * 50}")
    print("LIVE DEMO MODE - Processing bars one at a time")
    print(f"{'─' * 50}")

    gen = MarketDataGenerator(seed=99)
    bars = gen.generate_gbm_bars("AAPL", start_price=185.0, n_bars=n_ticks, sigma=0.015)
    strategies = build_default_strategies(["AAPL"])

    portfolio = Portfolio(initial_capital=1_000_000.0)
    engine = TradingEngine(
        portfolio=portfolio,
        strategies=strategies,
        risk_limits=RiskLimits(max_drawdown_pct=0.20, max_daily_loss_pct=0.05),
    )
    engine.risk_manager.reset_daily(1_000_000.0)

    for i, bar in enumerate(bars):
        events = engine.on_bar(bar)
        for ev in events:
            if ev["event"] in ("FILL", "TP", "SL", "ORDER_SUBMITTED"):
                print(
                    f"  [{bar.timestamp.strftime('%H:%M')}] "
                    f"{ev['event']:<18} {bar.symbol}  "
                    f"@ {bar.close:.2f}  "
                    f"PnL={ev.get('pnl', 'N/A')}"
                )

        if (i + 1) % 10 == 0:
            status = engine.status()
            p = status["portfolio"]
            print(
                f"\n  --- Bar {i+1:>3} | Equity: ${p['equity']:>12,.2f} | "
                f"Return: {p['total_return_pct']:>+6.2f}% | "
                f"Open orders: {status['open_orders']} ---\n"
            )

    print("\nFinal portfolio state:")
    status = engine.status()
    for k, v in status["portfolio"].items():
        if k != "open_positions":
            print(f"  {k:<25} {v}")


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "backtest"
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 300

    if mode == "live":
        run_live_demo(n_ticks=n)
    else:
        run_backtest(n_bars=n)
