"""
Pine Script alert message templates for each trading plan.
Copy-paste these into the TradingView alert "Message" box.
"""

WEBHOOK_URL = "http://YOUR_SERVER:8080/webhook/tv"
SECRET = "CHANGE_ME"


def get_templates() -> dict:
    """Return Pine Script JSON alert templates for all 6 plans."""
    return {
        "PLAN_A_MOMENTUM": {
            "description": "EMA Crossover — fires on BUY/SELL cross signals",
            "buy_message": f"""{{
  "secret": "{SECRET}",
  "symbol": "{{{{ticker}}}}",
  "action": "buy",
  "qty": 100,
  "price": {{{{close}}}},
  "atr": {{{{ta.atr(14)}}}},
  "tp_atr_mult": 3.0,
  "sl_atr_mult": 1.5,
  "strategy": "MomentumEMACross",
  "plan": "PLAN_A_MOMENTUM",
  "comment": "EMA cross buy"
}}""",
            "sell_message": f"""{{
  "secret": "{SECRET}",
  "symbol": "{{{{ticker}}}}",
  "action": "sell",
  "qty": 100,
  "price": {{{{close}}}},
  "atr": {{{{ta.atr(14)}}}},
  "tp_atr_mult": 3.0,
  "sl_atr_mult": 1.5,
  "strategy": "MomentumEMACross",
  "plan": "PLAN_A_MOMENTUM",
  "comment": "EMA cross sell"
}}""",
        },

        "PLAN_B_MEAN_REVERSION": {
            "description": "Bollinger Band bounce — fires when price touches band extremes",
            "buy_message": f"""{{
  "secret": "{SECRET}",
  "symbol": "{{{{ticker}}}}",
  "action": "buy",
  "qty": 80,
  "price": {{{{close}}}},
  "tp_price": {{{{ta.sma(close, 20)}}}},
  "sl_pct": 0.01,
  "strategy": "MeanReversionBB",
  "plan": "PLAN_B_MEAN_REVERSION",
  "comment": "lower_band_bounce"
}}""",
        },

        "PLAN_C_VWAP": {
            "description": "VWAP reversion — fires when price deviates from VWAP",
            "buy_message": f"""{{
  "secret": "{SECRET}",
  "symbol": "{{{{ticker}}}}",
  "action": "buy",
  "qty": 60,
  "price": {{{{close}}}},
  "tp_pct": 0.004,
  "sl_pct": 0.003,
  "strategy": "VWAPReversion",
  "plan": "PLAN_C_VWAP",
  "comment": "below_vwap"
}}""",
        },

        "PLAN_D_BREAKOUT": {
            "description": "Donchian breakout — fires when price breaks 20-bar high/low",
            "buy_message": f"""{{
  "secret": "{SECRET}",
  "symbol": "{{{{ticker}}}}",
  "action": "buy",
  "qty": 50,
  "price": {{{{close}}}},
  "atr": {{{{ta.atr(14)}}}},
  "tp_atr_mult": 4.0,
  "sl_atr_mult": 2.0,
  "strategy": "DonchianBreakout",
  "plan": "PLAN_D_BREAKOUT",
  "comment": "breakout_up"
}}""",
        },

        "PLAN_F_MARKET_MAKING": {
            "description": "Market maker quotes — fires every N bars for limit order refresh",
            "bid_message": f"""{{
  "secret": "{SECRET}",
  "symbol": "{{{{ticker}}}}",
  "action": "buy",
  "qty": 20,
  "price": {{{{close}}}},
  "tp_pct": 0.004,
  "sl_pct": 0.006,
  "strategy": "MarketMaker",
  "plan": "PLAN_F_MARKET_MAKING",
  "comment": "mm_bid"
}}""",
        },
    }


def print_setup_guide() -> None:
    print("=" * 70)
    print(" TRADINGVIEW WEBHOOK SETUP GUIDE")
    print("=" * 70)
    print(f"\n  Webhook URL: {WEBHOOK_URL}")
    print(f"  Secret:      {SECRET}\n")
    print("  Steps:")
    print("  1. Open TradingView → Create Alert")
    print("  2. Set 'Condition' to your indicator/strategy signal")
    print("  3. In 'Notifications' → enable 'Webhook URL'")
    print(f"  4. Enter webhook URL: {WEBHOOK_URL}")
    print("  5. In 'Message' paste the JSON template for your plan")
    print("  6. TradingView will POST the alert to your server\n")

    templates = get_templates()
    for plan, tdata in templates.items():
        print(f"  [{plan}]")
        print(f"  Description: {tdata['description']}")
        first_key = next(k for k in tdata if k != "description")
        print(f"  Alert Message ({first_key}):")
        for line in tdata[first_key].split("\n"):
            print(f"    {line}")
        print()
