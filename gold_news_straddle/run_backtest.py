"""Backtest the NFP straddle: clip replication, parameter sweep with an
in-sample / out-of-sample split, cost sensitivity, a no-news placebo, and a
replay of the exact release shown in the source clip.

    python run_backtest.py
"""
from __future__ import annotations

import json
from dataclasses import asdict, replace
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

import straddle as S

HERE = Path(__file__).parent
OUT = HERE / "results"
OUT.mkdir(exist_ok=True)
SPLIT = pd.Timestamp("2023-01-01", tz="UTC")

# what the clip actually does: 0.01 lot a side, both sides allowed to fill
CLIP = S.Params(dist=0.60, sl=3.0, tp=0.0, trail=3.0, max_hold=60, hedge=True)


def split_stats(trades: pd.DataFrame, events: list[str]) -> dict:
    """Full-sample, pre-2023 and post-2023 stats from a single backtest run."""
    ts = pd.to_datetime(trades["event"], utc=True) if len(trades) else None
    ev_ts = pd.to_datetime(pd.Series(events), utc=True)
    out = {}
    for tag, mask in (("all", None), ("is", True), ("oos", False)):
        if mask is None:
            t, e = trades, events
        else:
            t = trades[(ts < SPLIT) == mask] if len(trades) else trades
            e = [x for x, d in zip(events, ev_ts) if (d < SPLIT) == mask]
        out[tag] = S.stats(t, e)
    return out


def yearly(trades: pd.DataFrame, events: list[str]) -> pd.DataFrame:
    ev = S.per_event(trades).reindex(sorted(events), fill_value=0.0)
    evr = S.per_event(trades, "r").reindex(sorted(events), fill_value=0.0)
    yr = pd.to_datetime(pd.Series(ev.index), utc=True).dt.year.values
    d = pd.DataFrame({"year": yr, "usd": ev.values, "R": evr.values})
    g = d.groupby("year").agg(releases=("usd", "size"), net_usd=("usd", "sum"),
                              per_event_R=("R", "mean"),
                              winrate=("usd", lambda x: (x > 0).mean() * 100))
    return g.round({"net_usd": 2, "per_event_R": 3, "winrate": 1})


# --------------------------------------------------------------------------- #
def grid() -> list[dict]:
    g = []
    for scale, dists, sls, tps, trails in (
        ("fixed", (0.30, 0.60, 1.00, 1.50, 2.50), (2.0, 3.0, 5.0, 8.0),
         (5.0, 10.0, 20.0), (2.0, 3.0, 5.0)),
        ("vol", (0.05, 0.10, 0.20, 0.35, 0.60), (0.25, 0.50, 1.00, 1.50),
         (0.50, 1.00, 2.00), (0.25, 0.50, 1.00)),
    ):
        for dist in dists:
            for hedge in (True, False):
                for sl in sls:
                    for tp in tps:
                        g.append(dict(scale=scale, dist=dist, hedge=hedge, sl=sl,
                                      tp=tp, trail=0.0, max_hold=60))
                    for tr in trails:
                        g.append(dict(scale=scale, dist=dist, hedge=hedge, sl=sl,
                                      tp=0.0, trail=tr, max_hold=60))
                    for hold in (15, 30, 60):
                        g.append(dict(scale=scale, dist=dist, hedge=hedge, sl=sl,
                                      tp=0.0, trail=0.0, max_hold=hold))
    return g


def sweep(bars: pd.DataFrame, events: list[str]) -> pd.DataFrame:
    """Every ticket risks the same 10 USD so configs are directly comparable."""
    rows = []
    for cfg in grid():
        p = replace(CLIP, risk_usd=10.0, **cfg)
        st = split_stats(S.backtest(bars, p), events)
        row = dict(cfg)
        row["exit"] = "target" if cfg["tp"] else "trail" if cfg["trail"] else "timeout"
        for tag in ("all", "is", "oos"):
            for k in ("net_usd", "per_event_R", "profit_factor", "event_winrate",
                      "max_dd_usd", "t_stat", "trades"):
                row[f"{tag}_{k}"] = st[tag][k]
        rows.append(row)
    return pd.DataFrame(rows)


KEEP = ("net_usd", "per_event_usd", "per_event_R", "profit_factor",
        "event_winrate", "max_dd_usd")


def cost_sensitivity(bars: pd.DataFrame, p: S.Params, events: list[str]) -> pd.DataFrame:
    """Execution quality is the whole ballgame on a news straddle, so vary the
    two things a retail account cannot control: the spread it is quoted in the
    seconds after the print, and how far a stop order slips on the spike."""
    rows = []
    for ns in (0.30, 0.80, 1.50, 3.00):
        for sf, smax in ((0.00, 0.50), (0.10, 2.00), (0.25, 5.00), (0.50, 10.00)):
            st = S.stats(S.backtest(bars, replace(p, news_spread=ns,
                                                  slip_range_frac=sf,
                                                  slip_max=smax)), events)
            rows.append(dict(news_spread=ns, slip_frac=sf, slip_cap=smax,
                             **{k: st[k] for k in KEEP}))
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- #
def charts(ev: pd.Series, tag: str, title: str) -> None:
    eq = ev.cumsum()
    x = pd.to_datetime(ev.index, utc=True)
    fig, ax = plt.subplots(2, 1, figsize=(11, 7.5), height_ratios=[2, 1], sharex=True)
    ax[0].plot(x, eq.values, lw=1.8, color="#c9a227")
    ax[0].fill_between(x, eq.values, 0, alpha=.15, color="#c9a227")
    ax[0].axhline(0, color="#888", lw=.8)
    ax[0].axvline(SPLIT, color="#888", ls="--", lw=1)
    ax[0].text(SPLIT, eq.max() * .9, "  out-of-sample →", fontsize=9, color="#666")
    ax[0].set_title(title)
    ax[0].set_ylabel("cumulative USD")
    ax[0].grid(alpha=.25)
    ax[1].bar(x, ev.values, width=18,
              color=["#2e7d32" if v > 0 else "#c62828" for v in ev.values])
    ax[1].axhline(0, color="#888", lw=.8)
    ax[1].set_ylabel("USD / release")
    ax[1].grid(alpha=.25)
    fig.tight_layout()
    fig.savefig(OUT / f"equity_{tag}.png", dpi=140)
    plt.close(fig)


def hist(ev: pd.Series) -> None:
    fig, ax = plt.subplots(figsize=(7, 4.5))
    ax.hist(ev.values, bins=28, color="#c9a227", edgecolor="#7a6218")
    ax.axvline(0, color="#333", lw=1)
    ax.axvline(ev.mean(), color="#2e7d32", ls="--", lw=1.4,
               label=f"mean {ev.mean():+.2f} USD")
    ax.set_title("P/L per NFP release — 0.01 lot a side")
    ax.set_xlabel("USD")
    ax.legend()
    ax.grid(alpha=.25)
    fig.tight_layout()
    fig.savefig(OUT / "pnl_distribution.png", dpi=140)
    plt.close(fig)


def clip_replay(p: S.Params):
    bars = S.load(HERE / "data" / "xauusd_m1_clip_event.csv.gz")
    w = S.windows(bars)[0]
    trades = S.run_event(w, p)
    rel = w.release
    v = bars.loc[rel - pd.Timedelta(minutes=8): rel + pd.Timedelta(minutes=15)]

    fig, ax = plt.subplots(figsize=(11, 5.5))
    for t, b in v.iterrows():
        c = "#26a69a" if b["close"] >= b["open"] else "#ef5350"
        ax.plot([t, t], [b["low"], b["high"]], color=c, lw=1)
        ax.plot([t, t], [b["open"], b["close"]], color=c, lw=6, solid_capstyle="butt")
    for tr in trades:
        col = "#1565c0" if tr.side == "long" else "#ad1457"
        ax.scatter([tr.entry_time], [tr.entry_price], marker="^" if tr.side == "long"
                   else "v", s=150, color=col, zorder=5)
        ax.scatter([tr.exit_time], [tr.exit_price], marker="x", s=120, color="#222", zorder=5)
        ax.annotate(f"{tr.side} {tr.pnl:+.2f} USD ({tr.reason})",
                    (tr.exit_time, tr.exit_price), fontsize=9, color=col,
                    xytext=(8, 8), textcoords="offset points")
    ax.axvline(rel, color="#888", ls="--", lw=1)
    ax.set_title(f"Clip replay — {rel:%Y-%m-%d %H:%M} UTC release, XAUUSD M1")
    ax.set_ylabel("USD / oz")
    ax.grid(alpha=.25)
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(OUT / "clip_event.png", dpi=140)
    plt.close(fig)
    return trades


# --------------------------------------------------------------------------- #
def main() -> None:
    bars = S.load()
    events = sorted(bars["event"].unique())
    n = len(events)
    print(f"loaded {n} NFP windows, {len(bars)} M1 bars "
          f"({bars.index.min():%Y-%m-%d} .. {bars.index.max():%Y-%m-%d})\n")

    # 1. straight replication of the clip -----------------------------------
    tr = S.backtest(bars, CLIP)
    clip_split = split_stats(tr, events)
    tr.to_csv(OUT / "clip_config_trades.csv", index=False)
    ev = S.per_event(tr).sort_index()
    ev.to_csv(OUT / "clip_config_per_event.csv")
    print("=== A. CLIP CONFIG (0.01 lot, dist 0.60, SL 3.00, trail 3.00) ===")
    for k, v in clip_split.items():
        print(f"  {k:4s} {json.dumps(v)}")
    ev = ev.reindex(events, fill_value=0.0)
    charts(ev, "clip_config",
           "XAUUSD NFP straddle — clip settings, 0.01 lot a side")
    hist(ev)
    yr = yearly(tr, events)
    yr.to_csv(OUT / "clip_config_by_year.csv")
    print("\n  by year (clip config):\n" +
          "\n".join("    " + l for l in yr.to_string().splitlines()))

    # 2. sweep, selected in-sample only -------------------------------------
    sw = sweep(bars, events)
    sw.to_csv(OUT / "sweep.csv", index=False)
    ranked = sw[sw["is_trades"] >= 60].sort_values("is_per_event_R", ascending=False)
    best = ranked.iloc[0]
    print("\n=== B. SWEEP: top 12 ranked by IN-SAMPLE (2017-2022) R/event ===")
    cols = ["scale", "dist", "sl", "exit", "tp", "trail", "max_hold", "hedge",
            "is_per_event_R", "oos_per_event_R", "all_per_event_R",
            "all_profit_factor", "all_t_stat"]
    print(ranked.head(12)[cols].to_string(index=False))
    print(f"\n  top-20 IS configs -> median OOS R/event "
          f"{ranked.head(20)['oos_per_event_R'].median():+.3f}, "
          f"{(ranked.head(20)['oos_per_event_R'] > 0).sum()}/20 profitable OOS")

    bp = replace(CLIP, risk_usd=10.0, **{k: best[k] for k in
                 ("scale", "dist", "hedge", "sl", "tp", "trail", "max_hold")})
    bp = replace(bp, hedge=bool(best["hedge"]), max_hold=int(best["max_hold"]))
    btr = S.backtest(bars, bp)
    btr.to_csv(OUT / "selected_trades.csv", index=False)
    bev = S.per_event(btr).reindex(events, fill_value=0.0)
    charts(bev, "selected", "XAUUSD NFP straddle — IS-selected settings, 10 USD risk/ticket")
    print("\n=== C. IS-SELECTED CONFIG, full sample ===")
    print("  params:", json.dumps({k: (float(v) if isinstance(v, (int, float, np.floating))
                                       else v) for k, v in asdict(bp).items()}, default=str))
    sel_split = split_stats(btr, events)
    for k, v in sel_split.items():
        print(f"  {k:4s} {json.dumps(v)}")
    yr2 = yearly(btr, events)
    yr2.to_csv(OUT / "selected_by_year.csv")
    print("  by year (selected):\n" +
          "\n".join("    " + l for l in yr2.to_string().splitlines()))

    # 3. cost sensitivity ----------------------------------------------------
    cs = cost_sensitivity(bars, CLIP, events)
    cs.to_csv(OUT / "cost_sensitivity.csv", index=False)
    print("\n=== D. COST SENSITIVITY (clip config) ===")
    print(cs.to_string(index=False))

    # 4. placebo -------------------------------------------------------------
    pb = S.load(HERE / "data" / "xauusd_m1_placebo_windows.csv.gz")
    pst = S.stats(S.backtest(pb, CLIP), sorted(pb["event"].unique()))
    print("\n=== E. PLACEBO: same trade, same clock slot, no scheduled release ===")
    print(" ", json.dumps(pst))

    # 5. the clip's own event ------------------------------------------------
    clip = clip_replay(CLIP)
    print("\n=== F. CLIP EVENT REPLAY (2026-08-12 12:30 UTC) ===")
    for t in clip:
        print(f"  {t.side:5s} in {t.entry_price:9.2f} @ {t.entry_time:%H:%M}"
              f"  ->  out {t.exit_price:9.2f} @ {t.exit_time:%H:%M}"
              f"  ({t.reason:7s}) {t.pnl:+7.2f} USD")
    print(f"  net {sum(t.pnl for t in clip):+.2f} USD")

    json.dump({"clip_config": {"params": asdict(CLIP), **clip_split},
               "selected": {"params": asdict(bp), **sel_split},
               "placebo": pst,
               "cost_sensitivity": cs.to_dict("records"),
               "clip_event": [t.__dict__ for t in clip]},
              open(OUT / "summary.json", "w"), indent=2, default=str)
    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    main()
