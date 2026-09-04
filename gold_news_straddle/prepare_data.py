"""Slice XAUUSD M1 bars around every NFP release into a small, committed dataset.

Source: https://github.com/sherwynjoel/xauusd-historical-data
        `xauusd_m1_full.parquet` - 3.27M one-minute bars pulled from a live
        Exness MT5 terminal (symbol XAUUSDm), 2017-04-28 -> 2026-08-18.
        OHLC are bid prices; `spread` is in points (1 point = 0.001 USD).

Usage:
    python prepare_data.py --source /path/to/xauusd_m1_full.parquet
"""
from __future__ import annotations

import argparse
import datetime as dt
from pathlib import Path

import pandas as pd

from calendar_events import release_datetimes

HERE = Path(__file__).parent
OUT = HERE / "data" / "xauusd_m1_nfp_windows.csv.gz"
PRE_MIN, POST_MIN = 120, 120


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True)
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args()

    df = pd.read_parquet(args.source)
    df.index = pd.to_datetime(df.index, utc=True)
    df = df[["open", "high", "low", "close", "spread", "tick_volume"]].sort_index()

    events = release_datetimes(dt.date(2017, 5, 1), dt.date(2026, 12, 31))
    frames = []
    for ts in events:
        lo = pd.Timestamp(ts) - pd.Timedelta(minutes=PRE_MIN)
        hi = pd.Timestamp(ts) + pd.Timedelta(minutes=POST_MIN)
        w = df.loc[lo:hi].copy()
        if len(w) < 60:                       # market closed (e.g. Good Friday)
            print(f"skip {ts:%Y-%m-%d} - only {len(w)} bars")
            continue
        w["event"] = pd.Timestamp(ts).strftime("%Y-%m-%dT%H:%M")
        frames.append(w)

    out = pd.concat(frames)
    out.index.name = "time"
    out.to_csv(args.out, float_format="%.3f")
    print(f"{out['event'].nunique()} events, {len(out)} bars -> {args.out}")
    extras(args.source)




# --------------------------------------------------------------------------- #
# extras: a placebo set (same clock window on days with no first-tier release)
# and the single event shown in the source clip.
# --------------------------------------------------------------------------- #
def extras(source: str) -> None:
    import calendar as _cal

    df = pd.read_parquet(source)
    df.index = pd.to_datetime(df.index, utc=True)
    df = df[["open", "high", "low", "close", "spread", "tick_volume"]].sort_index()

    # placebo: the Tuesday nearest the 20th of each month, same 08:30 New York
    # slot.  Tuesdays that late in the month rarely carry a first-tier US print,
    # so this is the "same trade, no news" control.
    from calendar_events import NY
    rows = []
    for y in range(2017, 2027):
        for m in range(1, 13):
            days = [d for d in range(15, _cal.monthrange(y, m)[1] + 1)
                    if dt.date(y, m, d).weekday() == 1]
            if not days:
                continue
            d = min(days, key=lambda x: abs(x - 20))
            ts = dt.datetime(y, m, d, 8, 30, tzinfo=NY).astimezone(dt.timezone.utc)
            w = df.loc[pd.Timestamp(ts) - pd.Timedelta(minutes=PRE_MIN):
                       pd.Timestamp(ts) + pd.Timedelta(minutes=POST_MIN)].copy()
            if len(w) < 60:
                continue
            w["event"] = pd.Timestamp(ts).strftime("%Y-%m-%dT%H:%M")
            rows.append(w)
    placebo = pd.concat(rows)
    placebo.index.name = "time"
    placebo.to_csv(HERE / "data" / "xauusd_m1_placebo_windows.csv.gz",
                   float_format="%.3f")
    print(f"placebo: {placebo['event'].nunique()} events, {len(placebo)} bars")

    # the release visible in the clip: 2026-08-12 12:30 UTC (08:30 New York)
    ts = pd.Timestamp("2026-08-12T12:30", tz="UTC")
    w = df.loc[ts - pd.Timedelta(minutes=PRE_MIN): ts + pd.Timedelta(minutes=POST_MIN)].copy()
    w["event"] = ts.strftime("%Y-%m-%dT%H:%M")
    w.index.name = "time"
    w.to_csv(HERE / "data" / "xauusd_m1_clip_event.csv.gz", float_format="%.3f")
    print(f"clip event: {len(w)} bars")


if __name__ == "__main__":
    main()
