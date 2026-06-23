# Gold Spider Trailing — MQL5 Expert Advisor

An MT5 Expert Advisor that reproduces the **"gold spider trailing"** grid shown
in the reference image: a symmetric web of pending **stop** orders fanned out
above and below the current price, with a **doubling (martingale) lot
progression**, that **trails the market** as price moves.

```
        BUY STOP 5.12   ── farthest above  (biggest lot)
        BUY STOP 2.56
        BUY STOP 1.28
        ...
        BUY STOP 0.02
        BUY STOP 0.01   ── nearest above   (smallest lot)
  ────────────────────  ◄ current price (grid centre)
        SELL STOP 0.01  ── nearest below   (smallest lot)
        SELL STOP 0.02
        ...
        SELL STOP 5.12  ── farthest below  (biggest lot)
```

## How it works

1. **Seed the web** — on the first tick (and whenever there are no pending
   orders) the EA places `GridLevels` BUY STOP orders above the Ask and the
   same number of SELL STOP orders below the Bid, spaced `GridStepPoints` apart.
2. **Martingale lots** — each level's lot is `BaseLot × LotMultiplier^n`. With
   the default `LOT_MARTINGALE_FARTHEST_BIGGEST` mode the farthest order is the
   biggest (matching the image: `0.01 → 0.02 → … → 5.12`).
3. **Spider trailing** — when price drifts `ReCentrePoints` away from the grid
   centre (and no position is open yet), the pending grid is deleted and
   re-seeded around the new price, so the "spider" follows the candles.
4. **Basket management** — filled positions are managed together: close all at
   `BasketTakeProfit` / `BasketStopLoss` (account currency), and/or trail each
   filled position's stop (`UsePositionTrail`).

## Inputs

| Group | Input | Meaning |
|-------|-------|---------|
| Grid layout | `GridLevels` | pending orders per side (image uses 10) |
| | `GridStepPoints` | spacing between levels (points) |
| | `FirstStepPoints` | distance from price to the first order |
| Lot progression | `BaseLot` | smallest lot (nearest level) |
| | `LotMultiplier` | × per level — `2.0` = doubling |
| | `LotMode` | which end of the grid gets the biggest lot |
| | `MaxLot` | hard cap per order (`0` = none) |
| Spider trailing | `TrailGrid` | re-centre the grid when price drifts |
| | `ReCentrePoints` | drift required before re-seeding |
| Basket | `BasketTakeProfit` | close all at this profit (ccy, `0` = off) |
| | `BasketStopLoss` | close all at this loss (ccy, `0` = off) |
| | `UsePositionTrail` | trail SL on each filled position |
| | `TrailStartPoints` / `TrailStepPoints` | trailing start / distance |
| General | `MagicNumber` | tags this EA's orders/positions |
| | `MaxSlippage` | max deviation (points) |
| | `DrawLabels` | draw the `BUY STOP x.xx` lines like the image |

## Install

1. Copy `GoldSpiderTrailing.mq5` into your terminal's
   `MQL5/Experts/` folder (open it from MetaTrader via
   **File → Open Data Folder**).
2. In MetaEditor press **F7** to compile → produces `GoldSpiderTrailing.ex5`.
3. In MetaTrader, drag the EA onto a chart, allow **Algo Trading**, and set the
   inputs. Test in the **Strategy Tester** first.

## ⚠️ Risk warning

This is a **martingale grid**. Doubling lots means a sustained one-way trend can
escalate exposure extremely fast and **wipe an account**. The defaults
(`0.01 → 5.12` over 10 levels) commit a very large total volume if every level
fills. Use only on a **demo account** for study, size positions to your actual
risk tolerance, and never run it with money you cannot afford to lose. Provided
for **educational / research purposes**; no profitability is implied or
guaranteed.
