"""News-straddle backtester for XAUUSD on one-minute bars.

The strategy reverse-engineered from the clip: a minute before a scheduled US
release the EA brackets the market with a BUY STOP above and a SELL STOP below,
0.01 lot each.  The number prints, price jumps, one (or both) of the stops
fills, and the fill is managed with a protective stop plus either a fixed target
or a trailing stop.

Fills are simulated by walking an assumed intrabar path rather than by reading
bar extremes only: an up bar is traversed open -> low -> high -> close, a down
bar open -> high -> low -> close (MetaTrader's "1 minute OHLC" model).  That
ordering is what makes a straddle backtest meaningful - on the release minute
both stop levels usually sit inside the same candle, and which one is touched
first decides the trade.

Every price in the feed is a BID.  ASK = BID + spread.  Longs enter at the ask
and exit at the bid, shorts the other way round, so the spread is paid twice.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

CONTRACT = 100.0          # XAUUSD: 1.00 lot = 100 oz -> a 1.00 USD move = 100 USD
POINT = 0.001             # the feed stores spread in points of 0.001 USD

HERE = Path(__file__).parent
DATA = HERE / "data" / "xauusd_m1_nfp_windows.csv.gz"


# --------------------------------------------------------------------------- #
# parameters
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Params:
    # --- entry -------------------------------------------------------------
    dist: float = 0.60            # stop-order distance from mid price
    place_lead: int = 1           # minutes before the release the orders go in
    pending_expiry: int = 5       # unfilled pendings deleted N min after release
    hedge: bool = True            # let both sides fill (the clip shows this)
    # --- management --------------------------------------------------------
    sl: float = 3.00              # protective stop, distance from entry
    tp: float = 0.00              # fixed target (0 = off)
    trail: float = 0.00           # trailing stop distance (0 = off)
    trail_start: float = 0.00     # only start trailing past this much profit
    breakeven: float = 0.00       # move the stop to entry past this much profit
    max_hold: int = 60            # minutes, then close at market
    # --- how the distances above are interpreted ---------------------------
    scale: str = "fixed"          # "fixed" = USD, "vol" = multiples of `unit`
    vol_lookback: int = 120       # minutes before the release that define `unit`
    # --- sizing ------------------------------------------------------------
    lots: float = 0.01
    risk_usd: float = 0.0         # >0: size each ticket so the stop costs this
    # --- costs -------------------------------------------------------------
    min_spread: float = 0.16      # USD, floor on the recorded spread
    news_spread: float = 0.80     # spread floor for `news_window` min post-release
    news_window: int = 3
    slip_base: float = 0.05       # USD, always paid on a stop fill
    slip_range_frac: float = 0.10 # plus this fraction of the filling bar's range
    slip_max: float = 2.00        # cap
    commission_per_lot_side: float = 3.50   # USD per 1.0 lot per side


@dataclass
class Trade:
    event: str = ""
    side: str = ""
    entry_time: pd.Timestamp = None
    entry_price: float = 0.0
    exit_time: pd.Timestamp = None
    exit_price: float = 0.0
    reason: str = ""
    lots: float = 0.0
    risk_usd: float = 0.0
    sl: float = 0.0
    tp: float = 0.0
    gross: float = 0.0
    pnl: float = 0.0
    r: float = 0.0


# --------------------------------------------------------------------------- #
# event windows (built once, reused across every parameter set)
# --------------------------------------------------------------------------- #
class Window:
    __slots__ = ("event", "release", "t", "o", "h", "l", "c", "sp", "idx")

    def __init__(self, event: str, g: pd.DataFrame):
        self.event = event
        self.release = pd.Timestamp(event, tz="UTC")
        self.t = g.index.to_numpy()
        self.sp = g["spread"].to_numpy(float) * POINT
        # the feed quotes bids; work in mid prices so a widening spread moves
        # the bid down and the ask up symmetrically, the way it really does
        half = self.sp / 2.0
        self.o = g["open"].to_numpy(float) + half
        self.h = g["high"].to_numpy(float) + half
        self.l = g["low"].to_numpy(float) + half
        self.c = g["close"].to_numpy(float) + half
        self.idx = {pd.Timestamp(v): i for i, v in enumerate(self.t)}


_CACHE: dict[int, list[Window]] = {}


def windows(bars: pd.DataFrame) -> list[Window]:
    key = id(bars)
    if key not in _CACHE:
        _CACHE[key] = [Window(ev, g) for ev, g in bars.groupby("event", sort=True)]
    return _CACHE[key]


# --------------------------------------------------------------------------- #
# engine
# --------------------------------------------------------------------------- #
def _segments(o: float, h: float, l: float, c: float):
    """Assumed intrabar path: up bars dip first, down bars pop first."""
    if c >= o:
        return ((o, l), (l, h), (h, c))
    return ((o, h), (h, l), (l, c))


def run_event(w: Window, p: Params) -> list[Trade]:
    rel = w.release
    ref_i = w.idx.get(rel - pd.Timedelta(minutes=p.place_lead))
    if ref_i is None or ref_i + 1 >= len(w.t):
        return []

    mid = w.c[ref_i]

    # Gold traded near 1250 USD in 2017 and near 4500 in 2026, so a level set in
    # fixed dollars is a different strategy in each era.  In "vol" mode every
    # distance is a multiple of the pre-release range - known before the orders
    # go in, so the sizing stays causal.
    unit = 1.0
    if p.scale == "vol":
        j = w.idx.get(rel - pd.Timedelta(minutes=p.vol_lookback), 0)
        unit = float(w.h[j:ref_i + 1].max() - w.l[j:ref_i + 1].min())
        if not np.isfinite(unit) or unit <= 0:
            return []
    dist, sl, tp = p.dist * unit, p.sl * unit, p.tp * unit
    trail, trail_start, be = p.trail * unit, p.trail_start * unit, p.breakeven * unit
    if sl <= 0:
        return []

    lots = p.risk_usd / (sl * CONTRACT) if p.risk_usd > 0 else p.lots
    risk = sl * CONTRACT * lots
    comm = p.commission_per_lot_side * lots * 2.0

    buy_level = mid + dist            # an ASK level
    sell_level = mid - dist           # a BID level
    buy_live = sell_live = True

    expiry_i = w.idx.get(rel + pd.Timedelta(minutes=p.pending_expiry), len(w.t))
    last_i = min(len(w.t) - 1,
                 w.idx.get(rel + pd.Timedelta(minutes=p.max_hold), len(w.t) - 1))
    news_end_i = w.idx.get(rel + pd.Timedelta(minutes=p.news_window), 0)

    live: list[Trade] = []
    done: list[Trade] = []

    def close(t: Trade, price: float, i: int, reason: str) -> None:
        t.exit_price, t.exit_time, t.reason = price, pd.Timestamp(w.t[i]), reason
        sign = 1.0 if t.side == "long" else -1.0
        t.gross = sign * (price - t.entry_price) * CONTRACT * lots
        t.pnl = t.gross - comm
        t.r = t.pnl / risk if risk else 0.0
        done.append(t)
        live.remove(t)

    for i in range(ref_i + 1, last_i + 1):
        sp = max(w.sp[i], p.min_spread)
        if i < news_end_i:
            sp = max(sp, p.news_spread)
        hs = sp / 2.0
        slip = min(p.slip_max, p.slip_base + p.slip_range_frac * (w.h[i] - w.l[i]))
        if i > expiry_i:
            buy_live = sell_live = False

        for a, b in _segments(w.o[i], w.h[i], w.l[i], w.c[i]):
            up = b >= a
            cur = a
            for _ in range(12):                     # guard against re-entry loops
                best = None
                if up:
                    if buy_live:
                        # a wide spread can lift the ask through the level even
                        # with the mid standing still - then it fills at market
                        lvl = max(cur, buy_level - hs)
                        if lvl <= b:
                            best = (lvl, "fill_buy", None)
                    for t in live:
                        if t.side == "short":
                            lvl, kind = t.sl - hs, "stop"
                        elif t.tp:
                            lvl, kind = t.tp + hs, "target"
                        else:
                            continue
                        lvl = max(lvl, cur) if lvl < cur else lvl
                        if lvl > b:
                            continue
                        if best is None or lvl < best[0]:
                            best = (lvl, kind, t)
                else:
                    if sell_live:
                        lvl = min(cur, sell_level + hs)
                        if lvl >= b:
                            best = (lvl, "fill_sell", None)
                    for t in live:
                        if t.side == "long":
                            lvl, kind = t.sl + hs, "stop"
                        elif t.tp:
                            lvl, kind = t.tp - hs, "target"
                        else:
                            continue
                        lvl = min(lvl, cur) if lvl > cur else lvl
                        if lvl < b:
                            continue
                        if best is None or lvl > best[0]:
                            best = (lvl, kind, t)
                if best is None:
                    break

                lvl, kind, tr = best
                cur = lvl
                if kind == "fill_buy":
                    buy_live = False
                    if not p.hedge:
                        sell_live = False
                    entry = max(buy_level, lvl + hs) + slip       # ask
                    live.append(Trade(w.event, "long", pd.Timestamp(w.t[i]), entry,
                                      lots=lots, risk_usd=risk,
                                      sl=entry - sl, tp=entry + tp if tp else 0.0))
                elif kind == "fill_sell":
                    sell_live = False
                    if not p.hedge:
                        buy_live = False
                    entry = min(sell_level, lvl - hs) - slip      # bid
                    live.append(Trade(w.event, "short", pd.Timestamp(w.t[i]), entry,
                                      lots=lots, risk_usd=risk,
                                      sl=entry + sl, tp=entry - tp if tp else 0.0))
                elif kind == "stop":
                    close(tr, tr.sl - slip if tr.side == "long" else tr.sl + slip,
                          i, "stop")
                else:
                    close(tr, tr.tp, i, "target")

        # end-of-bar management: breakeven, then trailing, both off the close
        for t in live:
            if t.side == "long":
                gain = (w.c[i] - hs) - t.entry_price
                if be and gain >= be:
                    t.sl = max(t.sl, t.entry_price)
                if trail and gain >= max(trail_start, trail):
                    t.sl = max(t.sl, (w.c[i] - hs) - trail)
            else:
                gain = t.entry_price - (w.c[i] + hs)
                if be and gain >= be:
                    t.sl = min(t.sl, t.entry_price)
                if trail and gain >= max(trail_start, trail):
                    t.sl = min(t.sl, (w.c[i] + hs) + trail)

    hs = max(w.sp[last_i], p.min_spread) / 2.0
    for t in list(live):
        close(t, w.c[last_i] - hs if t.side == "long" else w.c[last_i] + hs,
              last_i, "timeout")
    return done


def backtest(bars: pd.DataFrame, p: Params) -> pd.DataFrame:
    rows = [t.__dict__ for w in windows(bars) for t in run_event(w, p)]
    if not rows:
        return pd.DataFrame(columns=list(Trade().__dict__))
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- #
# reporting
# --------------------------------------------------------------------------- #
def per_event(trades: pd.DataFrame, col: str = "pnl") -> pd.Series:
    if trades.empty:
        return pd.Series(dtype=float)
    return trades.groupby("event")[col].sum()


def stats(trades: pd.DataFrame, events) -> dict:
    """`events` is the full list of scheduled releases; ones the straddle never
    filled count as a flat 0.00, not as a missing observation."""
    if np.isscalar(events):
        idx, n_events = None, int(events)
    else:
        idx = sorted(set(events))
        n_events = len(idx)
    ev = per_event(trades).sort_index()
    evr = per_event(trades, "r").sort_index()
    if idx is not None:
        ev = ev.reindex(idx, fill_value=0.0)
        evr = evr.reindex(idx, fill_value=0.0)
    eq = ev.cumsum()
    dd = float((eq.cummax() - eq).max()) if len(eq) else 0.0
    wins = trades[trades.pnl > 0]["pnl"] if len(trades) else pd.Series(dtype=float)
    losses = trades[trades.pnl <= 0]["pnl"] if len(trades) else pd.Series(dtype=float)
    gp, gl = wins.sum(), -losses.sum()
    return {
        "events": int(n_events),
        "traded_events": int(len(trades.groupby("event")) if len(trades) else 0),
        "trades": int(len(trades)),
        "net_usd": round(float(ev.sum()), 2),
        "per_event_usd": round(float(ev.mean()), 3) if len(ev) else 0.0,
        "per_event_R": round(float(evr.mean()), 3) if len(evr) else 0.0,
        "event_winrate": round(float((ev > 0).mean() * 100), 1) if len(ev) else 0.0,
        "trade_winrate": round(len(wins) / len(trades) * 100, 1) if len(trades) else 0.0,
        "profit_factor": round(float(gp / gl), 2) if gl > 0 else float("inf"),
        "avg_win": round(float(wins.mean()), 2) if len(wins) else 0.0,
        "avg_loss": round(float(losses.mean()), 2) if len(losses) else 0.0,
        "best_event": round(float(ev.max()), 2) if len(ev) else 0.0,
        "worst_event": round(float(ev.min()), 2) if len(ev) else 0.0,
        "max_dd_usd": round(dd, 2),
        "t_stat": round(float(ev.mean() / (ev.std(ddof=1) / np.sqrt(len(ev)))), 2)
                  if len(ev) > 2 and ev.std(ddof=1) > 0 else 0.0,
    }


def load(path: Path | str = DATA) -> pd.DataFrame:
    df = pd.read_csv(path, parse_dates=["time"])
    df["time"] = pd.to_datetime(df["time"], utc=True)
    return df.set_index("time").sort_index()
