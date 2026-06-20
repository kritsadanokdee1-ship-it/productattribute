"""
Backtesting Engine: runs a TradingEngine over historical bar data,
collects results, and computes performance statistics.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional
import json

from ..core.market_data import Bar
from ..core.portfolio import Portfolio
from ..execution.engine import TradingEngine
from ..execution.risk_manager import RiskLimits
from ..strategies.base import BaseStrategy


@dataclass
class BacktestConfig:
    initial_capital: float = 1_000_000.0
    commission_pct: float = 0.0005
    risk_limits: Optional[RiskLimits] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None


@dataclass
class BacktestResult:
    config: BacktestConfig
    portfolio_summary: dict
    risk_summary: dict
    fill_log: List[dict]
    equity_curve: List[dict]
    trade_analysis: dict
    bars_processed: int
    duration_seconds: float


class Backtester:
    """Multi-strategy backtester with full performance reporting."""

    def __init__(
        self,
        strategies: List[BaseStrategy],
        config: Optional[BacktestConfig] = None,
    ):
        self.strategies = strategies
        self.config = config or BacktestConfig()

    def run(self, bars_by_symbol: Dict[str, List[Bar]]) -> BacktestResult:
        """Run backtest. bars_by_symbol: {symbol: [Bar, ...]}"""
        t0 = datetime.utcnow()
        portfolio = Portfolio(self.config.initial_capital)
        engine = TradingEngine(
            portfolio=portfolio,
            strategies=self.strategies,
            risk_limits=self.config.risk_limits,
            commission_pct=self.config.commission_pct,
        )

        # Merge and sort all bars by timestamp
        all_bars: List[Bar] = []
        for sym_bars in bars_by_symbol.values():
            all_bars.extend(sym_bars)
        all_bars.sort(key=lambda b: b.timestamp)

        # Filter by date range if specified
        if self.config.start_date:
            all_bars = [b for b in all_bars if b.timestamp >= self.config.start_date]
        if self.config.end_date:
            all_bars = [b for b in all_bars if b.timestamp <= self.config.end_date]

        for bar in all_bars:
            engine.on_bar(bar)

        prices = {sym: engine.market.last_price(sym) for sym in engine.market.bars}
        prices = {k: v for k, v in prices.items() if v is not None}

        equity_curve = [
            {
                "ts": s.timestamp.isoformat(),
                "equity": round(s.equity, 2),
                "cash": round(s.cash, 2),
                "unrealized_pnl": round(s.unrealized_pnl, 2),
                "drawdown_pct": round(s.drawdown * 100, 2),
            }
            for s in portfolio.equity_curve
        ]

        trade_analysis = self._analyze_trades(portfolio)
        t1 = datetime.utcnow()

        return BacktestResult(
            config=self.config,
            portfolio_summary=portfolio.summary(prices),
            risk_summary=engine.risk_manager.summary(),
            fill_log=engine.order_manager.fill_log(),
            equity_curve=equity_curve,
            trade_analysis=trade_analysis,
            bars_processed=engine._bar_count,
            duration_seconds=(t1 - t0).total_seconds(),
        )

    def _analyze_trades(self, portfolio: Portfolio) -> dict:
        trades = portfolio.closed_trades
        if not trades:
            return {"message": "No closed trades"}

        pnls = [t.realized_pnl for t in trades]
        winners = [p for p in pnls if p > 0]
        losers = [p for p in pnls if p < 0]

        by_strategy: Dict[str, list] = {}
        for t in trades:
            sid = t.strategy_id
            by_strategy.setdefault(sid, []).append(t.realized_pnl)

        return {
            "total_trades": len(trades),
            "winners": len(winners),
            "losers": len(losers),
            "win_rate_pct": round(len(winners) / len(trades) * 100, 1),
            "avg_win": round(sum(winners) / len(winners), 2) if winners else 0,
            "avg_loss": round(sum(losers) / len(losers), 2) if losers else 0,
            "largest_win": round(max(pnls), 2),
            "largest_loss": round(min(pnls), 2),
            "total_pnl": round(sum(pnls), 2),
            "expectancy": round(sum(pnls) / len(pnls), 2),
            "by_strategy": {
                sid: {
                    "trades": len(spnls),
                    "total_pnl": round(sum(spnls), 2),
                    "win_rate": round(
                        len([p for p in spnls if p > 0]) / len(spnls) * 100, 1
                    ),
                }
                for sid, spnls in by_strategy.items()
            },
            "tp_hit_count": len([t for t in trades if "TP" in t.status.value]),
            "sl_hit_count": len([t for t in trades if "SL" in t.status.value]),
        }

    def print_report(self, result: BacktestResult) -> None:
        print("=" * 70)
        print(" JP MORGAN TRADING SYSTEM - BACKTEST REPORT")
        print("=" * 70)
        p = result.portfolio_summary
        print(f"\n{'PORTFOLIO PERFORMANCE':^70}")
        print("-" * 70)
        print(f"  Initial Capital:     ${p['initial_capital']:>15,.2f}")
        print(f"  Final Equity:        ${p['equity']:>15,.2f}")
        print(f"  Realized PnL:        ${p['realized_pnl']:>+15,.2f}")
        print(f"  Unrealized PnL:      ${p['unrealized_pnl']:>+15,.2f}")
        print(f"  Total Return:        {p['total_return_pct']:>+14.2f}%")
        print(f"  Max Drawdown:        {p['max_drawdown_pct']:>14.2f}%")
        print(f"  Sharpe Ratio:        {p['sharpe_ratio']:>15.4f}")
        print(f"  Win Rate:            {p['win_rate_pct']:>14.2f}%")
        print(f"  Profit Factor:       {p['profit_factor']:>15.4f}")
        print(f"  Total Trades:        {p['total_trades']:>15,}")
        print(f"  Commission Paid:     ${p['total_commission']:>15,.2f}")

        t = result.trade_analysis
        if "total_trades" in t:
            print(f"\n{'TRADE ANALYSIS':^70}")
            print("-" * 70)
            print(f"  Total Closed Trades: {t['total_trades']:>15,}")
            print(f"  Winners:             {t['winners']:>15,}")
            print(f"  Losers:              {t['losers']:>15,}")
            print(f"  Avg Win:             ${t['avg_win']:>+15,.2f}")
            print(f"  Avg Loss:            ${t['avg_loss']:>+15,.2f}")
            print(f"  Largest Win:         ${t['largest_win']:>+15,.2f}")
            print(f"  Largest Loss:        ${t['largest_loss']:>+15,.2f}")
            print(f"  Expectancy/Trade:    ${t['expectancy']:>+15,.2f}")
            print(f"  TP Hit Count:        {t['tp_hit_count']:>15,}")
            print(f"  SL Hit Count:        {t['sl_hit_count']:>15,}")

            print(f"\n{'STRATEGY BREAKDOWN':^70}")
            print("-" * 70)
            for sid, stats in t.get("by_strategy", {}).items():
                print(f"  {sid:<30} Trades={stats['trades']:>4}  "
                      f"PnL=${stats['total_pnl']:>+10,.2f}  "
                      f"WR={stats['win_rate']:>5.1f}%")

        r = result.risk_summary
        print(f"\n{'RISK SUMMARY':^70}")
        print("-" * 70)
        print(f"  Trading Halted:      {r['trading_halted']}")
        print(f"  Total Rejections:    {r['total_rejections']:>15,}")

        print(f"\n  Bars Processed:      {result.bars_processed:>15,}")
        print(f"  Backtest Duration:   {result.duration_seconds:>14.3f}s")
        print("=" * 70)
