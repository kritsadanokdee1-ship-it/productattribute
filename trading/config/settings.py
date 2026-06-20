"""
Default configuration and strategy builder.
Mirrors how a desk would configure multiple trading plans.
"""
from __future__ import annotations
from typing import List

from ..strategies import (
    BaseStrategy, StrategyConfig,
    MomentumStrategy,
    MeanReversionStrategy,
    VWAPStrategy,
    BreakoutStrategy,
    PairsStrategy, PairConfig,
    MarketMakingStrategy,
)
from ..execution.risk_manager import RiskLimits


class TradingConfig:
    """Central configuration for the trading system."""

    SYMBOLS_EQUITY = ["AAPL", "MSFT", "JPM", "GS", "TSLA"]
    SYMBOLS_ALL = SYMBOLS_EQUITY + ["SPY", "QQQ"]
    PAIRS = [
        ("JPM", "GS"),
        ("AAPL", "MSFT"),
    ]
    INITIAL_CAPITAL = 5_000_000.0
    COMMISSION_PCT = 0.0005

    RISK_LIMITS = RiskLimits(
        max_position_pct=0.08,
        max_gross_exposure_pct=1.20,
        max_net_exposure_pct=0.40,
        max_drawdown_pct=0.15,
        max_daily_loss_pct=0.04,
        max_orders_per_symbol=4,
        max_risk_per_trade_pct=0.015,
        min_cash_reserve_pct=0.05,
    )


def build_default_strategies(symbols: List[str] = None) -> List[BaseStrategy]:
    """
    Build all 6 trading plans:
    A - Momentum EMA Cross
    B - Mean Reversion Bollinger Bands
    C - VWAP Reversion
    D - Donchian Breakout
    E - Pairs Stat Arb
    F - Market Making
    """
    syms = symbols or TradingConfig.SYMBOLS_EQUITY

    strategies: List[BaseStrategy] = []

    # Plan A: Momentum
    strategies.append(MomentumStrategy(
        config=StrategyConfig(
            plan_id="PLAN_A_MOMENTUM",
            symbols=syms,
            max_position_pct=0.08,
            min_bars=30,
        ),
        fast_ema=9, slow_ema=21, rsi_period=14,
        rsi_ob=65, rsi_os=35,
        tp_atr=3.0, sl_atr=1.5,
    ))

    # Plan B: Mean Reversion
    strategies.append(MeanReversionStrategy(
        config=StrategyConfig(
            plan_id="PLAN_B_MEAN_REVERSION",
            symbols=syms,
            max_position_pct=0.06,
            min_bars=25,
        ),
        bb_period=20, bb_std=2.0,
        rsi_ob=70, rsi_os=30,
        sl_atr_mult=1.0,
    ))

    # Plan C: VWAP
    strategies.append(VWAPStrategy(
        config=StrategyConfig(
            plan_id="PLAN_C_VWAP",
            symbols=syms,
            max_position_pct=0.05,
            min_bars=25,
        ),
        vwap_period=20,
        deviation_pct=0.005,
        tp_pct=0.004,
        sl_pct=0.003,
    ))

    # Plan D: Breakout
    strategies.append(BreakoutStrategy(
        config=StrategyConfig(
            plan_id="PLAN_D_BREAKOUT",
            symbols=syms,
            max_position_pct=0.08,
            min_bars=25,
        ),
        entry_period=20, exit_period=10,
        tp_channel_mult=2.0, sl_atr_mult=2.0,
    ))

    # Plan E: Pairs Stat Arb
    pairs = [
        PairConfig(sym_a, sym_b, hedge_ratio=1.0, entry_z=2.0, exit_z=0.5)
        for sym_a, sym_b in TradingConfig.PAIRS
        if sym_a in syms and sym_b in syms
    ]
    if pairs:
        strategies.append(PairsStrategy(
            config=StrategyConfig(
                plan_id="PLAN_E_PAIRS",
                symbols=[s for pair in pairs for s in (pair.symbol_a, pair.symbol_b)],
                max_position_pct=0.05,
                min_bars=60,
            ),
            pairs=pairs,
        ))

    # Plan F: Market Making (on most liquid)
    strategies.append(MarketMakingStrategy(
        config=StrategyConfig(
            plan_id="PLAN_F_MARKET_MAKING",
            symbols=["AAPL", "MSFT"],
            max_position_pct=0.04,
            min_bars=20,
        ),
        spread_pct=0.0008,
        order_size_pct=0.005,
        sl_pct=0.006,
        tp_pct=0.003,
    ))

    return strategies
