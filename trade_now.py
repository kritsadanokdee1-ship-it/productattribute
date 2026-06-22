#!/usr/bin/env python3
"""
JP Morgan Trading System — Live MT5 Executor
Target: +$1,000 profit on Demo account
Instruments: XAUUSD (Gold) + EURUSD
Max orders: 10 open at once (existing orders preserved)

HOW TO RUN (Windows with MT5 open):
  1. pip install MetaTrader5
  2. python trade_now.py

IMPORTANT:
  - Will NOT touch any orders already open before this script runs
  - Uses tight risk management: max 1% risk per trade
  - Circuit breaker stops if equity drops more than 3% from start
"""
import time
import logging
from datetime import datetime
from typing import Optional

import MetaTrader5 as mt5
import numpy as np

# ─── CONFIG — fill in your Demo credentials ───────────────────────────────────
MT5_LOGIN    = 0           # <-- your account number
MT5_PASSWORD = ""          # <-- your password
MT5_SERVER   = ""          # <-- e.g. "ICMarkets-Demo01"

INSTRUMENTS = {
    "XAUUSD": {
        "lot":        0.01,     # starting lot
        "max_lot":    0.10,
        "tp_pips":    200,      # Gold pips (0.01 per pip)
        "sl_pips":    80,
        "atr_period": 14,
    },
    "EURUSD": {
        "lot":        0.05,
        "max_lot":    0.50,
        "tp_pips":    30,       # Forex pips (0.0001 per pip)
        "sl_pips":    15,
        "atr_period": 14,
    },
}

TARGET_PROFIT_USD   = 1_000.0
MAX_OPEN_ORDERS     = 10       # hard cap incl. existing
MAX_NEW_ORDERS      = 5        # new orders we can add
RISK_PER_TRADE_PCT  = 0.01     # 1% account equity per trade
CIRCUIT_BREAKER_PCT = 0.03     # stop if drawdown > 3%
MAGIC               = 20260622  # identifies our orders
POLL_INTERVAL_SEC   = 30       # check every 30 seconds

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler("trade_now.log")],
)
log = logging.getLogger("trade_now")

# ─── MT5 Helpers ──────────────────────────────────────────────────────────────

def connect() -> bool:
    if not mt5.initialize(login=MT5_LOGIN, password=MT5_PASSWORD, server=MT5_SERVER):
        log.error(f"MT5 init failed: {mt5.last_error()}")
        return False
    info = mt5.account_info()
    if info is None:
        log.error("Cannot read account info")
        return False
    log.info(f"Connected: {info.name} | {info.server} | Balance={info.balance:,.2f} {info.currency}")
    return True


def account_equity() -> float:
    info = mt5.account_info()
    return info.equity if info else 0.0


def account_profit() -> float:
    info = mt5.account_info()
    return info.profit if info else 0.0


def count_all_open() -> int:
    positions = mt5.positions_get()
    return len(positions) if positions else 0


def count_our_open(symbol: Optional[str] = None) -> int:
    kw = {"magic": MAGIC}
    if symbol:
        kw["symbol"] = symbol
    positions = mt5.positions_get(**kw) or []
    return len(positions)


def total_our_profit() -> float:
    positions = mt5.positions_get(magic=MAGIC) or []
    return sum(p.profit for p in positions)


def get_atr(symbol: str, period: int = 14, tf=mt5.TIMEFRAME_H1) -> float:
    rates = mt5.copy_rates_from_pos(symbol, tf, 0, period + 2)
    if rates is None or len(rates) < period:
        return 0.0
    trs = []
    for i in range(1, len(rates)):
        tr = max(
            rates[i]["high"] - rates[i]["low"],
            abs(rates[i]["high"] - rates[i - 1]["close"]),
            abs(rates[i]["low"] - rates[i - 1]["close"]),
        )
        trs.append(tr)
    return float(np.mean(trs[-period:]))


def get_ema(symbol: str, period: int, tf=mt5.TIMEFRAME_H1) -> Optional[float]:
    rates = mt5.copy_rates_from_pos(symbol, tf, 0, period * 3)
    if rates is None or len(rates) < period:
        return None
    closes = np.array([r["close"] for r in rates])
    k = 2 / (period + 1)
    ema = closes[0]
    for c in closes[1:]:
        ema = c * k + ema * (1 - k)
    return float(ema)


def get_rsi(symbol: str, period: int = 14, tf=mt5.TIMEFRAME_H1) -> Optional[float]:
    rates = mt5.copy_rates_from_pos(symbol, tf, 0, period + 2)
    if rates is None or len(rates) < period + 1:
        return None
    closes = [r["close"] for r in rates]
    gains, losses = [], []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i - 1]
        gains.append(max(d, 0))
        losses.append(max(-d, 0))
    ag = np.mean(gains[-period:])
    al = np.mean(losses[-period:])
    return 100.0 if al == 0 else float(100 - 100 / (1 + ag / al))


def pip_value(symbol: str) -> float:
    """Returns pip size in price units."""
    info = mt5.symbol_info(symbol)
    if info is None:
        return 0.0001
    # Gold: point=0.01 → pip=0.10; Forex: point=0.00001 → pip=0.0001
    return info.point * (10 if "XAU" not in symbol else 10)


# ─── Signal Generation ────────────────────────────────────────────────────────

def compute_signal(symbol: str) -> Optional[str]:
    """
    Multi-timeframe signal:
    H4 trend direction + H1 EMA cross + RSI filter.
    Returns 'BUY', 'SELL', or None.
    """
    # H4 trend
    ema_fast_h4 = get_ema(symbol, 9, mt5.TIMEFRAME_H4)
    ema_slow_h4 = get_ema(symbol, 21, mt5.TIMEFRAME_H4)
    # H1 entry
    ema_fast_h1 = get_ema(symbol, 9, mt5.TIMEFRAME_H1)
    ema_slow_h1 = get_ema(symbol, 21, mt5.TIMEFRAME_H1)
    rsi = get_rsi(symbol, 14, mt5.TIMEFRAME_H1)

    if None in (ema_fast_h4, ema_slow_h4, ema_fast_h1, ema_slow_h1, rsi):
        return None

    bull_trend = ema_fast_h4 > ema_slow_h4
    bear_trend = ema_fast_h4 < ema_slow_h4

    if bull_trend and ema_fast_h1 > ema_slow_h1 and rsi < 65:
        return "BUY"
    if bear_trend and ema_fast_h1 < ema_slow_h1 and rsi > 35:
        return "SELL"
    return None


# ─── Order Execution ──────────────────────────────────────────────────────────

def send_market_order(
    symbol: str,
    direction: str,
    lot: float,
    tp_price: float,
    sl_price: float,
    comment: str = "",
) -> bool:
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        log.error(f"No tick for {symbol}")
        return False

    price = tick.ask if direction == "BUY" else tick.bid
    order_type = mt5.ORDER_TYPE_BUY if direction == "BUY" else mt5.ORDER_TYPE_SELL

    request = {
        "action":      mt5.TRADE_ACTION_DEAL,
        "symbol":      symbol,
        "volume":      float(round(lot, 2)),
        "type":        order_type,
        "price":       float(price),
        "tp":          float(round(tp_price, mt5.symbol_info(symbol).digits)),
        "sl":          float(round(sl_price, mt5.symbol_info(symbol).digits)),
        "deviation":   20,
        "magic":       MAGIC,
        "comment":     comment or f"JPM|{symbol}",
        "type_time":   mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }

    result = mt5.order_send(request)
    if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
        err = mt5.last_error()
        log.error(f"Order failed for {symbol} {direction}: retcode={getattr(result,'retcode',None)} {err}")
        return False

    log.info(
        f"✅ {direction} {lot}lot {symbol} "
        f"@ {result.price:.4f}  TP={tp_price:.4f}  SL={sl_price:.4f}  "
        f"ticket={result.order}"
    )
    return True


def place_trade(symbol: str, signal: str, equity: float) -> bool:
    cfg = INSTRUMENTS[symbol]
    atr = get_atr(symbol, cfg["atr_period"])
    pip = pip_value(symbol)
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        return False

    price = tick.ask if signal == "BUY" else tick.bid

    # TP/SL based on ATR (min: config pip levels)
    if atr > 0:
        tp_dist = max(atr * 2.0, cfg["tp_pips"] * pip)
        sl_dist = max(atr * 1.0, cfg["sl_pips"] * pip)
    else:
        tp_dist = cfg["tp_pips"] * pip
        sl_dist = cfg["sl_pips"] * pip

    if signal == "BUY":
        tp = price + tp_dist
        sl = price - sl_dist
    else:
        tp = price - tp_dist
        sl = price + sl_dist

    # Risk-based lot sizing: risk = equity * 1%
    risk_amount = equity * RISK_PER_TRADE_PCT
    lot_info = mt5.symbol_info(symbol)
    lot = risk_amount / (sl_dist / lot_info.point * lot_info.trade_tick_value)
    lot = max(cfg["lot"], min(cfg["max_lot"], round(lot / lot_info.volume_step) * lot_info.volume_step))

    return send_market_order(symbol, signal, lot, tp, sl, f"JPM|{signal}|ATR")


# ─── Main Loop ────────────────────────────────────────────────────────────────

def main():
    log.info("=" * 60)
    log.info(" JP Morgan Trading System — LIVE MT5 Executor")
    log.info(f" Target: +${TARGET_PROFIT_USD:,.0f}  |  Instruments: {list(INSTRUMENTS)}")
    log.info("=" * 60)

    if not connect():
        return

    start_equity = account_equity()
    circuit_breaker_floor = start_equity * (1 - CIRCUIT_BREAKER_PCT)
    start_all_positions = set(
        p.ticket for p in (mt5.positions_get() or [])
    )
    log.info(f"Starting equity: ${start_equity:,.2f}")
    log.info(f"Pre-existing orders: {len(start_all_positions)} (will NOT be touched)")
    log.info(f"Circuit breaker at: ${circuit_breaker_floor:,.2f}")
    log.info(f"Target reached at:  ${start_equity + TARGET_PROFIT_USD:,.2f}")
    log.info("-" * 60)

    iteration = 0
    while True:
        iteration += 1
        now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        equity = account_equity()
        our_profit = total_our_profit()
        all_open = count_all_open()
        our_open = count_our_open()

        log.info(
            f"[{now}] Iter={iteration} | Equity=${equity:,.2f} | "
            f"Our P/L=${our_profit:+,.2f} | "
            f"AllOrders={all_open} | OurOrders={our_open}"
        )

        # ── Target reached ──
        if our_profit >= TARGET_PROFIT_USD:
            log.info(f"🎯 TARGET REACHED! Our profit = ${our_profit:+,.2f} (target: ${TARGET_PROFIT_USD:,.0f})")
            log.info("Stopping new orders. Existing positions managed by MT5 TP/SL.")
            break

        # ── Circuit breaker ──
        if equity < circuit_breaker_floor:
            log.warning(
                f"⛔ CIRCUIT BREAKER: equity ${equity:,.2f} < floor ${circuit_breaker_floor:,.2f}"
            )
            break

        # ── Max orders check (leave room for existing) ──
        slots_available = MAX_OPEN_ORDERS - all_open
        new_slots = min(slots_available, MAX_NEW_ORDERS - our_open)
        if new_slots <= 0:
            log.info(f"No slots: allOpen={all_open}/{MAX_OPEN_ORDERS} ourOpen={our_open}/{MAX_NEW_ORDERS}")
        else:
            for symbol in INSTRUMENTS:
                if count_our_open(symbol) >= 2:
                    log.info(f"  {symbol}: already has 2 our orders — skipping")
                    continue
                if count_all_open() >= MAX_OPEN_ORDERS:
                    break

                signal = compute_signal(symbol)
                log.info(f"  {symbol}: signal={signal}")

                if signal:
                    ok = place_trade(symbol, signal, equity)
                    if ok:
                        new_slots -= 1
                        time.sleep(1)

        time.sleep(POLL_INTERVAL_SEC)

    # Final summary
    equity_final = account_equity()
    our_profit_final = total_our_profit()
    log.info("=" * 60)
    log.info(" FINAL SUMMARY")
    log.info(f"  Start equity:    ${start_equity:,.2f}")
    log.info(f"  Final equity:    ${equity_final:,.2f}")
    log.info(f"  Our positions P/L: ${our_profit_final:+,.2f}")
    log.info(f"  Net change:      ${equity_final - start_equity:+,.2f}")
    log.info("=" * 60)
    mt5.shutdown()


if __name__ == "__main__":
    main()
