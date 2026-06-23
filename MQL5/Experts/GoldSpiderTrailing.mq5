//+------------------------------------------------------------------+
//|                                         GoldSpiderTrailing.mq5    |
//|                       Spider grid pending-order EA (martingale)   |
//|                                                                  |
//|  Reproduces the "gold spider trailing" strategy shown in the     |
//|  reference image: a symmetric web of BUY STOP orders above price |
//|  and SELL STOP orders below price, with a doubling (martingale)  |
//|  lot progression. The whole grid TRAILS the market - when price  |
//|  drifts away from the grid centre the pending orders are deleted |
//|  and re-seeded around the new price, so the "spider" follows the |
//|  candles. Filled positions are managed as a single basket with a |
//|  money / point trailing stop.                                    |
//|                                                                  |
//|  EDUCATIONAL / RESEARCH USE. Martingale grids carry unbounded    |
//|  risk: a sustained trend can blow the account. Test on a demo    |
//|  account in the Strategy Tester before risking real capital.     |
//+------------------------------------------------------------------+
#property copyright "GoldSpiderTrailing"
#property version   "1.00"
#property strict

#include <Trade/Trade.mqh>

//--- lot progression mode for the grid levels
enum ENUM_LOT_MODE
  {
   LOT_MARTINGALE_FARTHEST_BIGGEST, // farthest level = biggest lot (image style)
   LOT_MARTINGALE_NEAREST_BIGGEST,  // nearest level = biggest lot
   LOT_FIXED                        // every level uses BaseLot
  };

//============================== INPUTS ==============================
input group           "=== Grid layout ==="
input int             GridLevels        = 10;        // pending orders per side
input double          GridStepPoints    = 300;       // spacing between levels (points)
input double          FirstStepPoints   = 300;       // distance from price to 1st order (points)

input group           "=== Lot progression ==="
input double          BaseLot           = 0.01;      // smallest lot (nearest level)
input double          LotMultiplier     = 2.0;       // x per level (2.0 = doubling)
input ENUM_LOT_MODE   LotMode           = LOT_MARTINGALE_FARTHEST_BIGGEST;
input double          MaxLot            = 5.12;      // hard cap per order (0 = none)

input group           "=== Spider trailing (grid follows price) ==="
input bool            TrailGrid         = true;      // re-centre grid when price drifts
input double          ReCentrePoints    = 300;       // drift before grid is re-seeded (points)

input group           "=== Basket / position management ==="
input double          BasketTakeProfit  = 50.0;      // close all at this profit (account ccy, 0=off)
input double          BasketStopLoss     = 0.0;      // close all at this loss (account ccy, 0=off)
input bool            UsePositionTrail  = true;      // trail SL on each filled position
input double          TrailStartPoints  = 400;       // profit before trailing starts (points)
input double          TrailStepPoints   = 200;       // trailing distance (points)

input group           "=== General ==="
input ulong           MagicNumber       = 20240623;  // EA id (orders/positions tagged)
input int             MaxSlippage       = 30;        // deviation (points)
input bool            DrawLabels        = true;      // draw "BUY STOP x.xx" labels like the image

//=============================== STATE =============================
CTrade        trade;
double        g_point;          // symbol point
int           g_digits;         // symbol digits
double        g_gridCentre = 0; // price the current grid is anchored to
string        g_prefix;         // object-name prefix for chart labels

//+------------------------------------------------------------------+
//| Initialisation                                                   |
//+------------------------------------------------------------------+
int OnInit()
  {
   g_point  = SymbolInfoDouble(_Symbol, SYMBOL_POINT);
   g_digits = (int)SymbolInfoInteger(_Symbol, SYMBOL_DIGITS);
   g_prefix = "GST_" + (string)MagicNumber + "_";

   trade.SetExpertMagicNumber(MagicNumber);
   trade.SetDeviationInPoints(MaxSlippage);
   trade.SetTypeFillingBySymbol(_Symbol);

   if(GridLevels < 1 || BaseLot <= 0 || GridStepPoints <= 0)
     {
      Print("Invalid inputs: check GridLevels / BaseLot / GridStepPoints.");
      return(INIT_PARAMETERS_INCORRECT);
     }

   Print("GoldSpiderTrailing started on ", _Symbol,
         "  levels=", GridLevels, "  step=", GridStepPoints, "pts");
   return(INIT_SUCCEEDED);
  }

//+------------------------------------------------------------------+
//| De-initialisation                                                |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
  {
   ObjectsDeleteAll(0, g_prefix);
   // Pending orders are left in place on purpose; remove manually or
   // call DeleteAllPending() here if you prefer a clean shutdown.
  }

//+------------------------------------------------------------------+
//| Main loop                                                        |
//+------------------------------------------------------------------+
void OnTick()
  {
   ManageBasket();        // TP/SL on the whole basket
   if(UsePositionTrail)
      TrailPositions();   // per-position trailing stop

   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);

   // (Re)build the spider web when there is no grid yet, or when the
   // market has drifted far enough from the current grid centre.
   bool needSeed = (CountPending() == 0);
   if(TrailGrid && g_gridCentre > 0)
     {
      double drift = MathAbs(bid - g_gridCentre) / g_point;
      if(drift >= ReCentrePoints)
         needSeed = true;
     }

   if(needSeed && CountPositions() == 0) // don't reshuffle while in a trade
      SeedGrid(bid);
  }

//+------------------------------------------------------------------+
//| Lot size for a given level (0 = nearest price)                   |
//+------------------------------------------------------------------+
double LotForLevel(const int level)
  {
   double lot = BaseLot;
   switch(LotMode)
     {
      case LOT_FIXED:
         lot = BaseLot;
         break;
      case LOT_MARTINGALE_NEAREST_BIGGEST:
         lot = BaseLot * MathPow(LotMultiplier, GridLevels - 1 - level);
         break;
      case LOT_MARTINGALE_FARTHEST_BIGGEST:
      default:
         lot = BaseLot * MathPow(LotMultiplier, level);
         break;
     }
   return(NormalizeLot(lot));
  }

//+------------------------------------------------------------------+
//| Seed the full grid: BUY STOPs above, SELL STOPs below            |
//+------------------------------------------------------------------+
void SeedGrid(const double bid)
  {
   DeleteAllPending();
   ObjectsDeleteAll(0, g_prefix);

   double ask  = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double first = FirstStepPoints * g_point;
   double step  = GridStepPoints  * g_point;

   for(int i = 0; i < GridLevels; i++)
     {
      double lot   = LotForLevel(i);
      double dist  = first + i * step;

      // BUY STOP above current price
      double buyPrice = NormalizeDouble(ask + dist, g_digits);
      if(trade.BuyStop(lot, buyPrice, _Symbol, 0, 0, ORDER_TIME_GTC, 0,
                       "spider_buy_" + (string)i))
         DrawLabel(g_prefix + "buy_" + (string)i, buyPrice, lot, true);

      // SELL STOP below current price
      double sellPrice = NormalizeDouble(bid - dist, g_digits);
      if(trade.SellStop(lot, sellPrice, _Symbol, 0, 0, ORDER_TIME_GTC, 0,
                        "spider_sell_" + (string)i))
         DrawLabel(g_prefix + "sell_" + (string)i, sellPrice, lot, false);
     }

   g_gridCentre = bid;
   if(MQLInfoInteger(MQL_TESTER) == 0)
      Print("Spider grid (re)seeded around ", DoubleToString(bid, g_digits));
  }

//+------------------------------------------------------------------+
//| Close the whole basket on money TP / SL                          |
//+------------------------------------------------------------------+
void ManageBasket()
  {
   if(BasketTakeProfit <= 0 && BasketStopLoss <= 0)
      return;

   double profit = BasketProfit();
   if(CountPositions() == 0)
      return;

   if(BasketTakeProfit > 0 && profit >= BasketTakeProfit)
     {
      CloseAllPositions();
      DeleteAllPending();
      ObjectsDeleteAll(0, g_prefix);
      Print("Basket TP hit: ", DoubleToString(profit, 2));
     }
   else if(BasketStopLoss > 0 && profit <= -BasketStopLoss)
     {
      CloseAllPositions();
      DeleteAllPending();
      ObjectsDeleteAll(0, g_prefix);
      Print("Basket SL hit: ", DoubleToString(profit, 2));
     }
  }

//+------------------------------------------------------------------+
//| Per-position trailing stop                                       |
//+------------------------------------------------------------------+
void TrailPositions()
  {
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);

   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0)
         continue;
      if(!PositionSelectByTicket(ticket))
         continue;
      if(PositionGetInteger(POSITION_MAGIC) != (long)MagicNumber)
         continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol)
         continue;

      long   type   = PositionGetInteger(POSITION_TYPE);
      double open   = PositionGetDouble(POSITION_PRICE_OPEN);
      double curSL  = PositionGetDouble(POSITION_SL);
      double tp     = PositionGetDouble(POSITION_TP);

      if(type == POSITION_TYPE_BUY)
        {
         double profitPts = (bid - open) / g_point;
         if(profitPts >= TrailStartPoints)
           {
            double newSL = NormalizeDouble(bid - TrailStepPoints * g_point, g_digits);
            if(newSL > open && (curSL == 0 || newSL > curSL))
               trade.PositionModify(ticket, newSL, tp);
           }
        }
      else if(type == POSITION_TYPE_SELL)
        {
         double profitPts = (open - ask) / g_point;
         if(profitPts >= TrailStartPoints)
           {
            double newSL = NormalizeDouble(ask + TrailStepPoints * g_point, g_digits);
            if(newSL < open && (curSL == 0 || newSL < curSL))
               trade.PositionModify(ticket, newSL, tp);
           }
        }
     }
  }

//=========================== HELPERS ===============================

//--- aggregate floating P/L of this EA's positions
double BasketProfit()
  {
   double total = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0 || !PositionSelectByTicket(ticket))
         continue;
      if(PositionGetInteger(POSITION_MAGIC) != (long)MagicNumber)
         continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol)
         continue;
      total += PositionGetDouble(POSITION_PROFIT)
             + PositionGetDouble(POSITION_SWAP);
     }
   return(total);
  }

//--- number of this EA's open positions on the symbol
int CountPositions()
  {
   int n = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0 || !PositionSelectByTicket(ticket))
         continue;
      if(PositionGetInteger(POSITION_MAGIC) == (long)MagicNumber &&
         PositionGetString(POSITION_SYMBOL) == _Symbol)
         n++;
     }
   return(n);
  }

//--- number of this EA's pending orders on the symbol
int CountPending()
  {
   int n = 0;
   for(int i = OrdersTotal() - 1; i >= 0; i--)
     {
      ulong ticket = OrderGetTicket(i);
      if(ticket == 0 || !OrderSelect(ticket))
         continue;
      if(OrderGetInteger(ORDER_MAGIC) == (long)MagicNumber &&
         OrderGetString(ORDER_SYMBOL) == _Symbol)
         n++;
     }
   return(n);
  }

//--- delete every pending order belonging to this EA
void DeleteAllPending()
  {
   for(int i = OrdersTotal() - 1; i >= 0; i--)
     {
      ulong ticket = OrderGetTicket(i);
      if(ticket == 0 || !OrderSelect(ticket))
         continue;
      if(OrderGetInteger(ORDER_MAGIC) == (long)MagicNumber &&
         OrderGetString(ORDER_SYMBOL) == _Symbol)
         trade.OrderDelete(ticket);
     }
  }

//--- close every position belonging to this EA
void CloseAllPositions()
  {
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0 || !PositionSelectByTicket(ticket))
         continue;
      if(PositionGetInteger(POSITION_MAGIC) == (long)MagicNumber &&
         PositionGetString(POSITION_SYMBOL) == _Symbol)
         trade.PositionClose(ticket);
     }
  }

//--- clamp/round a lot to the symbol's volume constraints + MaxLot
double NormalizeLot(double lot)
  {
   double minLot  = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double maxLot  = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
   double lotStep = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);

   if(MaxLot > 0 && lot > MaxLot)
      lot = MaxLot;
   if(lotStep > 0)
      lot = MathFloor(lot / lotStep + 1e-9) * lotStep;
   if(lot < minLot)
      lot = minLot;
   if(lot > maxLot)
      lot = maxLot;

   int lotDigits = (lotStep >= 1.0) ? 0 : (int)MathRound(-MathLog10(lotStep));
   return(NormalizeDouble(lot, lotDigits));
  }

//--- draw a coloured "BUY STOP x.xx" / "SELL STOP x.xx" line + label
void DrawLabel(const string name, const double price,
               const double lot, const bool isBuy)
  {
   if(!DrawLabels)
      return;

   color clr = isBuy ? clrRoyalBlue : clrCrimson;

   // horizontal line at the order price
   if(ObjectFind(0, name) < 0)
      ObjectCreate(0, name, OBJ_HLINE, 0, 0, price);
   ObjectSetDouble(0, name, OBJPROP_PRICE, price);
   ObjectSetInteger(0, name, OBJPROP_COLOR, clr);
   ObjectSetInteger(0, name, OBJPROP_STYLE, STYLE_DOT);
   ObjectSetInteger(0, name, OBJPROP_WIDTH, 1);
   ObjectSetInteger(0, name, OBJPROP_BACK, true);
   ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);

   // text tag with the lot size, like the screenshot
   string txtName = name + "_t";
   string txt = (isBuy ? "BUY STOP " : "SELL STOP ") + DoubleToString(lot, 2);
   if(ObjectFind(0, txtName) < 0)
      ObjectCreate(0, txtName, OBJ_TEXT, 0, TimeCurrent(), price);
   ObjectSetInteger(0, txtName, OBJPROP_TIME, TimeCurrent());
   ObjectSetDouble(0, txtName, OBJPROP_PRICE, price);
   ObjectSetString(0, txtName, OBJPROP_TEXT, txt);
   ObjectSetInteger(0, txtName, OBJPROP_COLOR, clr);
   ObjectSetInteger(0, txtName, OBJPROP_FONTSIZE, 8);
   ObjectSetInteger(0, txtName, OBJPROP_ANCHOR, ANCHOR_LEFT);
   ObjectSetInteger(0, txtName, OBJPROP_SELECTABLE, false);
  }
//+------------------------------------------------------------------+
