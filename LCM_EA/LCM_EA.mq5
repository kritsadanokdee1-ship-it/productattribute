//+------------------------------------------------------------------+
//|                                                       LCM_EA.mq5 |
//|          LCM = Liquidity sweep -> CHoCH -> Mitigation (FVG)      |
//|                                                                  |
//|  โมเดล: 1) ราคากวาด liquidity (swing high/low, PDH/PDL)          |
//|         2) เกิด CHoCH ปิดแท่งทะลุโครงสร้างฝั่งตรงข้าม            |
//|         3) มี displacement + FVG                                 |
//|         4) วาง limit รอ mitigation กลับมาที่ FVG                 |
//|                                                                  |
//|  ***  เพื่อการศึกษา/backtest เท่านั้น ไม่ใช่คำแนะนำการลงทุน  *** |
//+------------------------------------------------------------------+
#property copyright "LCM EA - educational backtest template"
#property version   "1.00"
#property description "Liquidity sweep -> CHoCH -> Mitigation (FVG) entry model"

#include <Trade\Trade.mqh>

//+------------------------------------------------------------------+
//| Enums                                                            |
//+------------------------------------------------------------------+
enum ENUM_BIAS_MODE
  {
   BIAS_OFF       = 0, // ปิดฟิลเตอร์ (เทรดสองทาง)
   BIAS_EMA       = 1, // EMA บน Bias TF
   BIAS_STRUCTURE = 2  // โครงสร้าง HH/HL vs LH/LL บน Bias TF
  };

enum ENUM_TARGET_MODE
  {
   TARGET_RR        = 0, // TP = RR คงที่
   TARGET_LIQUIDITY = 1  // TP = liquidity ฝั่งตรงข้าม
  };

//+------------------------------------------------------------------+
//| Inputs                                                           |
//+------------------------------------------------------------------+
input group           "=== Timeframes ==="
input ENUM_TIMEFRAMES InpEntryTF            = PERIOD_M5;   // TF หา sweep/CHoCH/entry
input ENUM_TIMEFRAMES InpBiasTF             = PERIOD_H4;   // TF หา bias

input group           "=== Bias filter ==="
input ENUM_BIAS_MODE  InpBiasMode           = BIAS_STRUCTURE; // โหมด bias
input int             InpBiasEMAPeriod      = 50;          // EMA period (โหมด EMA)
input int             InpBiasSwingStrength  = 3;           // ความแรง swing บน Bias TF
input int             InpBiasLookback       = 120;         // มองย้อนหลังกี่แท่ง (Bias TF)

input group           "=== L : Liquidity sweep ==="
input int             InpSwingStrength      = 2;           // ความแรง swing บน Entry TF
input int             InpLiquidityLookback  = 60;          // หา liquidity ย้อนหลังกี่แท่ง
input int             InpSweepLookback      = 12;          // sweep ต้องเกิดภายในกี่แท่งล่าสุด
input int             InpMinSweepPoints     = 20;          // ต้องทะลุระดับอย่างน้อยกี่ point
input bool            InpUseDailyLevels     = true;        // ใช้ PDH/PDL เป็น liquidity ด้วย

input group           "=== C : CHoCH + displacement ==="
input int             InpMinBreakPoints     = 10;          // ปิดแท่งทะลุอย่างน้อยกี่ point
input double          InpDisplacementATR    = 0.8;         // body >= x * ATR (0 = ปิดเช็ค)
input int             InpATRPeriod          = 14;          // ATR period (Entry TF)

input group           "=== M : Mitigation / FVG entry ==="
input bool            InpRequireFVG         = true;        // บังคับต้องมี FVG
input int             InpMinFVGPoints       = 15;          // ขนาด FVG ขั้นต่ำ (point)
input double          InpFVGEntryPct        = 0.0;         // 0=ขอบใกล้ราคา 100=ขอบไกล
input double          InpMaxEntryDistATR    = 3.0;         // entry ห่างราคาได้ไม่เกิน x*ATR

input group           "=== Risk / SL / TP ==="
input double          InpRiskPercent        = 1.0;         // เสี่ยงต่อไม้ (% ของ balance)
input int             InpSLBufferPoints     = 250;         // buffer เหนือ/ใต้จุดกวาด (point)
input ENUM_TARGET_MODE InpTargetMode        = TARGET_RR;   // โหมด TP
input double          InpTPRR               = 2.5;         // RR สำหรับ TARGET_RR
input double          InpMinRR              = 2.0;         // RR ขั้นต่ำ ไม่ถึง = ไม่เข้า
input bool            InpUsePartial         = true;        // ปิดบางส่วนที่ TP1
input double          InpTP1_RR             = 1.0;         // TP1 ที่ RR เท่าไร
input double          InpPartialPercent     = 50.0;        // ปิดกี่ % ที่ TP1
input int             InpBEOffsetPoints     = 20;          // BE offset (point)
input bool            InpUseTrailing        = false;       // trailing หลัง BE
input double          InpTrailATR           = 1.5;         // ระยะ trail = x * ATR

input group           "=== Filters / operations ==="
input int             InpPendingExpiryBars  = 12;          // pending อยู่ได้กี่แท่ง
input bool            InpUseTimeFilter      = true;        // ใช้ฟิลเตอร์เวลา
input int             InpStartHour          = 8;           // ชั่วโมงเริ่ม (server time)
input int             InpEndHour            = 22;          // ชั่วโมงหยุด (server time)
input int             InpMaxSpreadPoints    = 60;          // spread สูงสุดที่ยอมเข้า
input int             InpMaxTradesPerDay    = 3;           // จำนวนไม้สูงสุดต่อวัน
input int             InpMaxPositions       = 1;           // ถือพร้อมกันได้กี่ไม้
input long            InpMagic              = 20260803;    // Magic number
input bool            InpDrawObjects        = false;       // วาดโซนบนกราฟ (visual mode)

//+------------------------------------------------------------------+
//| Globals                                                          |
//+------------------------------------------------------------------+
CTrade        trade;
int           hATR      = INVALID_HANDLE;
int           hEMA      = INVALID_HANDLE;
datetime      lastBarTime = 0;
datetime      lastTradeDay = 0;
int           tradesToday  = 0;
int           g_lotDigits  = 2;
double        g_point      = 0.0;

//+------------------------------------------------------------------+
//| Init                                                             |
//+------------------------------------------------------------------+
int OnInit()
  {
   g_point = _Point;

   trade.SetExpertMagicNumber(InpMagic);
   trade.SetTypeFillingBySymbol(_Symbol);
   trade.SetDeviationInPoints(20);

   hATR = iATR(_Symbol, InpEntryTF, InpATRPeriod);
   if(hATR == INVALID_HANDLE)
     {
      Print("LCM: สร้าง ATR handle ไม่สำเร็จ");
      return(INIT_FAILED);
     }

   if(InpBiasMode == BIAS_EMA)
     {
      hEMA = iMA(_Symbol, InpBiasTF, InpBiasEMAPeriod, 0, MODE_EMA, PRICE_CLOSE);
      if(hEMA == INVALID_HANDLE)
        {
         Print("LCM: สร้าง EMA handle ไม่สำเร็จ");
         return(INIT_FAILED);
        }
     }

   double step = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
   if(step <= 0.0)
      step = 0.01;
   g_lotDigits = (int)MathMax(0.0, MathRound(-MathLog10(step)));

   PrintFormat("LCM EA start | %s | entryTF=%s biasTF=%s | point=%.5f digits=%d",
               _Symbol, EnumToString(InpEntryTF), EnumToString(InpBiasTF), g_point, _Digits);

   return(INIT_SUCCEEDED);
  }

//+------------------------------------------------------------------+
//| Deinit                                                           |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
  {
   if(hATR != INVALID_HANDLE)
      IndicatorRelease(hATR);
   if(hEMA != INVALID_HANDLE)
      IndicatorRelease(hEMA);
   if(InpDrawObjects)
      ObjectsDeleteAll(0, "LCM_");
  }

//+------------------------------------------------------------------+
//| Tick                                                             |
//+------------------------------------------------------------------+
void OnTick()
  {
   ManageOpenPositions();     // ทุก tick: partial / BE / trailing
   ManagePendingOrders();     // ทุก tick: หมดอายุ / setup เสีย

   if(!IsNewBar())
      return;

   ResetDailyCounter();

   if(CountMyPositions() >= InpMaxPositions)
      return;
   if(CountMyOrders() > 0)
      return;
   if(InpMaxTradesPerDay > 0 && tradesToday >= InpMaxTradesPerDay)
      return;
   if(!TimeFilterOK())
      return;
   if((int)SymbolInfoInteger(_Symbol, SYMBOL_SPREAD) > InpMaxSpreadPoints)
      return;

   int need = InpLiquidityLookback + InpSweepLookback + InpSwingStrength + 10;
   if(Bars(_Symbol, InpEntryTF) < need)
      return;

   int bias = BiasDirection();

   if(InpBiasMode == BIAS_OFF || bias < 0)
      if(TryBearishSetup())
         return;

   if(InpBiasMode == BIAS_OFF || bias > 0)
      TryBullishSetup();
  }

//+------------------------------------------------------------------+
//| Helpers: bar / time / counters                                   |
//+------------------------------------------------------------------+
bool IsNewBar()
  {
   datetime t = iTime(_Symbol, InpEntryTF, 0);
   if(t == 0)
      return(false);
   if(t == lastBarTime)
      return(false);
   lastBarTime = t;
   return(true);
  }

void ResetDailyCounter()
  {
   MqlDateTime dt;
   TimeToStruct(TimeCurrent(), dt);
   dt.hour = 0;
   dt.min  = 0;
   dt.sec  = 0;
   datetime day = StructToTime(dt);
   if(day != lastTradeDay)
     {
      lastTradeDay = day;
      tradesToday  = 0;
     }
  }

bool TimeFilterOK()
  {
   if(!InpUseTimeFilter)
      return(true);
   MqlDateTime dt;
   TimeToStruct(TimeCurrent(), dt);
   int h = dt.hour;
   if(InpStartHour == InpEndHour)
      return(true);
   if(InpStartHour < InpEndHour)
      return(h >= InpStartHour && h < InpEndHour);
   return(h >= InpStartHour || h < InpEndHour);   // ข้ามเที่ยงคืน
  }

int CountMyPositions()
  {
   int n = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      ulong tk = PositionGetTicket(i);
      if(tk == 0)
         continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol)
         continue;
      if(PositionGetInteger(POSITION_MAGIC) != InpMagic)
         continue;
      n++;
     }
   return(n);
  }

int CountMyOrders()
  {
   int n = 0;
   for(int i = OrdersTotal() - 1; i >= 0; i--)
     {
      ulong tk = OrderGetTicket(i);
      if(tk == 0)
         continue;
      if(OrderGetString(ORDER_SYMBOL) != _Symbol)
         continue;
      if(OrderGetInteger(ORDER_MAGIC) != InpMagic)
         continue;
      n++;
     }
   return(n);
  }

double GetATR()
  {
   double buf[];
   if(CopyBuffer(hATR, 0, 1, 1, buf) < 1)
      return(0.0);
   return(buf[0]);
  }

//+------------------------------------------------------------------+
//| Swing detection (generic)                                        |
//+------------------------------------------------------------------+
bool IsSwingHighTF(const ENUM_TIMEFRAMES tf, const int idx, const int strength)
  {
   if(idx - strength < 1)
      return(false);
   double h = iHigh(_Symbol, tf, idx);
   if(h <= 0.0)
      return(false);
   for(int i = 1; i <= strength; i++)
     {
      if(iHigh(_Symbol, tf, idx + i) >  h)
         return(false);
      if(iHigh(_Symbol, tf, idx - i) >= h)
         return(false);
     }
   return(true);
  }

bool IsSwingLowTF(const ENUM_TIMEFRAMES tf, const int idx, const int strength)
  {
   if(idx - strength < 1)
      return(false);
   double l = iLow(_Symbol, tf, idx);
   if(l <= 0.0)
      return(false);
   for(int i = 1; i <= strength; i++)
     {
      if(iLow(_Symbol, tf, idx + i) <  l)
         return(false);
      if(iLow(_Symbol, tf, idx - i) <= l)
         return(false);
     }
   return(true);
  }

//+------------------------------------------------------------------+
//| Bias                                                             |
//| return +1 = ขาขึ้น, -1 = ขาลง, 0 = ไม่ชัด                        |
//+------------------------------------------------------------------+
int BiasDirection()
  {
   if(InpBiasMode == BIAS_OFF)
      return(0);

   if(InpBiasMode == BIAS_EMA)
     {
      double ema[];
      if(CopyBuffer(hEMA, 0, 1, 1, ema) < 1)
         return(0);
      double c = iClose(_Symbol, InpBiasTF, 1);
      if(c > ema[0])
         return(1);
      if(c < ema[0])
         return(-1);
      return(0);
     }

   // BIAS_STRUCTURE
   double h1 = 0.0, h2 = 0.0, l1 = 0.0, l2 = 0.0;
   if(!FindLastTwoSwings(true,  h1, h2))
      return(0);
   if(!FindLastTwoSwings(false, l1, l2))
      return(0);

   if(h1 > h2 && l1 > l2)
      return(1);
   if(h1 < h2 && l1 < l2)
      return(-1);
   return(0);
  }

//--- หา swing 2 จุดล่าสุดบน Bias TF (v1 = ล่าสุด, v2 = ก่อนหน้า)
bool FindLastTwoSwings(const bool wantHigh, double &v1, double &v2)
  {
   int found = 0;
   int start = 1 + InpBiasSwingStrength;
   for(int i = start; i <= InpBiasLookback; i++)
     {
      bool isSwing = wantHigh ? IsSwingHighTF(InpBiasTF, i, InpBiasSwingStrength)
                              : IsSwingLowTF(InpBiasTF, i, InpBiasSwingStrength);
      if(!isSwing)
         continue;
      double v = wantHigh ? iHigh(_Symbol, InpBiasTF, i) : iLow(_Symbol, InpBiasTF, i);
      if(found == 0)
        {
         v1 = v;
         found = 1;
        }
      else
        {
         v2 = v;
         return(true);
        }
     }
   return(false);
  }

//+------------------------------------------------------------------+
//| L : หา liquidity sweep ล่าสุด                                    |
//| bearish = กวาดยอดบน (เตรียม sell)                                |
//+------------------------------------------------------------------+
bool FindSweep(const bool bearish, int &sweepBar, double &sweepExtreme, double &sweptLevel)
  {
   double minPen = InpMinSweepPoints * g_point;
   double dailyLv = 0.0;
   if(InpUseDailyLevels)
      dailyLv = bearish ? iHigh(_Symbol, PERIOD_D1, 1) : iLow(_Symbol, PERIOD_D1, 1);

   for(int j = 2; j <= InpSweepLookback; j++)
     {
      double ej = bearish ? iHigh(_Symbol, InpEntryTF, j) : iLow(_Symbol, InpEntryTF, j);
      double cj = iClose(_Symbol, InpEntryTF, j);
      if(ej <= 0.0 || cj <= 0.0)
         continue;

      bool   found = false;
      double best  = 0.0;

      for(int m = j + 1; m <= j + InpLiquidityLookback; m++)
        {
         bool isSwing = bearish ? IsSwingHighTF(InpEntryTF, m, InpSwingStrength)
                                : IsSwingLowTF(InpEntryTF, m, InpSwingStrength);
         if(!isSwing)
            continue;
         double lv = bearish ? iHigh(_Symbol, InpEntryTF, m) : iLow(_Symbol, InpEntryTF, m);

         bool swept = bearish ? (ej > lv + minPen && cj < lv)
                              : (ej < lv - minPen && cj > lv);
         if(!swept)
            continue;

         // เลือกระดับที่ "ใกล้ราคาที่สุด" = ระดับที่เพิ่งถูกกวาดจริง
         if(!found || (bearish ? (lv < best) : (lv > best)))
           {
            best  = lv;
            found = true;
           }
        }

      if(InpUseDailyLevels && dailyLv > 0.0)
        {
         bool swept = bearish ? (ej > dailyLv + minPen && cj < dailyLv)
                              : (ej < dailyLv - minPen && cj > dailyLv);
         if(swept && (!found || (bearish ? (dailyLv < best) : (dailyLv > best))))
           {
            best  = dailyLv;
            found = true;
           }
        }

      if(found)
        {
         sweepBar     = j;
         sweepExtreme = ej;
         sweptLevel   = best;
         return(true);
        }
     }
   return(false);
  }

//+------------------------------------------------------------------+
//| C : หา reference structure + CHoCH                               |
//+------------------------------------------------------------------+
//--- swing ฝั่งตรงข้ามที่เกิดก่อน sweep (จุดที่ต้องถูกเบรก)
bool FindRefStructure(const bool bearish, const int sweepBar, double &refPrice)
  {
   for(int m = sweepBar + 1; m <= sweepBar + InpLiquidityLookback; m++)
     {
      bool isSwing = bearish ? IsSwingLowTF(InpEntryTF, m, InpSwingStrength)
                             : IsSwingHighTF(InpEntryTF, m, InpSwingStrength);
      if(!isSwing)
         continue;
      refPrice = bearish ? iLow(_Symbol, InpEntryTF, m) : iHigh(_Symbol, InpEntryTF, m);
      return(true);
     }
   return(false);
  }

//--- แท่งแรกหลัง sweep ที่ "ปิด" ทะลุ refPrice
bool FindCHoCH(const bool bearish, const int sweepBar, const double refPrice, int &chochBar)
  {
   double minBrk = InpMinBreakPoints * g_point;
   for(int k = sweepBar - 1; k >= 1; k--)
     {
      double c = iClose(_Symbol, InpEntryTF, k);
      if(c <= 0.0)
         continue;
      bool broke = bearish ? (c < refPrice - minBrk) : (c > refPrice + minBrk);
      if(broke)
        {
         chochBar = k;
         return(true);
        }
     }
   return(false);
  }

//--- displacement: body ของแท่ง CHoCH ต้องแรงพอ
bool HasDisplacement(const int chochBar, const double atr)
  {
   if(InpDisplacementATR <= 0.0)
      return(true);
   if(atr <= 0.0)
      return(false);
   double o = iOpen(_Symbol, InpEntryTF, chochBar);
   double c = iClose(_Symbol, InpEntryTF, chochBar);
   return(MathAbs(c - o) >= InpDisplacementATR * atr);
  }

//+------------------------------------------------------------------+
//| M : หา FVG รอบแท่ง CHoCH                                         |
//| bearish FVG: low[m+1] > high[m-1]  (โซน = high[m-1] .. low[m+1]) |
//+------------------------------------------------------------------+
bool FindFVG(const bool bearish, const int chochBar, double &zoneNear, double &zoneFar)
  {
   double minGap = InpMinFVGPoints * g_point;

   for(int off = 0; off <= 2; off++)
     {
      int m = chochBar + off;
      if(m < 2)
         continue;

      if(bearish)
        {
         double lowOld  = iLow(_Symbol,  InpEntryTF, m + 1);
         double highNew = iHigh(_Symbol, InpEntryTF, m - 1);
         if(lowOld > 0.0 && highNew > 0.0 && (lowOld - highNew) >= minGap)
           {
            zoneNear = highNew;   // ขอบล่าง = ใกล้ราคาปัจจุบัน
            zoneFar  = lowOld;    // ขอบบน
            return(true);
           }
        }
      else
        {
         double highOld = iHigh(_Symbol, InpEntryTF, m + 1);
         double lowNew  = iLow(_Symbol,  InpEntryTF, m - 1);
         if(highOld > 0.0 && lowNew > 0.0 && (lowNew - highOld) >= minGap)
           {
            zoneNear = lowNew;    // ขอบบน = ใกล้ราคาปัจจุบัน
            zoneFar  = highOld;   // ขอบล่าง
            return(true);
           }
        }
     }
   return(false);
  }

//+------------------------------------------------------------------+
//| หา liquidity ฝั่งตรงข้ามไว้เป็น TP                                |
//+------------------------------------------------------------------+
bool FindOppositeLiquidity(const bool bearish, const double entry, double &target)
  {
   bool   found = false;
   double best  = 0.0;
   int    start = 1 + InpSwingStrength;

   for(int i = start; i <= InpLiquidityLookback; i++)
     {
      bool isSwing = bearish ? IsSwingLowTF(InpEntryTF, i, InpSwingStrength)
                             : IsSwingHighTF(InpEntryTF, i, InpSwingStrength);
      if(!isSwing)
         continue;
      double v = bearish ? iLow(_Symbol, InpEntryTF, i) : iHigh(_Symbol, InpEntryTF, i);

      if(bearish && v >= entry)
         continue;
      if(!bearish && v <= entry)
         continue;

      // เอาจุดที่ไกลสุด = liquidity pool ใหญ่
      if(!found || (bearish ? (v < best) : (v > best)))
        {
         best  = v;
         found = true;
        }
     }

   if(found)
      target = best;
   return(found);
  }

//+------------------------------------------------------------------+
//| Setup builders                                                   |
//+------------------------------------------------------------------+
bool TryBearishSetup()
  {
   return(TrySetup(true));
  }

bool TryBullishSetup()
  {
   return(TrySetup(false));
  }

bool TrySetup(const bool bearish)
  {
   int    sweepBar = 0;
   double sweepExtreme = 0.0, sweptLevel = 0.0;
   if(!FindSweep(bearish, sweepBar, sweepExtreme, sweptLevel))
      return(false);

   double refPrice = 0.0;
   if(!FindRefStructure(bearish, sweepBar, refPrice))
      return(false);

   int chochBar = 0;
   if(!FindCHoCH(bearish, sweepBar, refPrice, chochBar))
      return(false);

   double atr = GetATR();
   if(!HasDisplacement(chochBar, atr))
      return(false);

   double zoneNear = 0.0, zoneFar = 0.0;
   if(!FindFVG(bearish, chochBar, zoneNear, zoneFar))
     {
      if(InpRequireFVG)
         return(false);
      // ไม่มี FVG -> ใช้ตัวแท่ง CHoCH เป็นโซนแทน (close = ขอบใกล้, extreme = ขอบไกล)
      zoneNear = iClose(_Symbol, InpEntryTF, chochBar);
      zoneFar  = bearish ? iHigh(_Symbol, InpEntryTF, chochBar) : iLow(_Symbol, InpEntryTF, chochBar);
     }

   double pct   = MathMax(0.0, MathMin(100.0, InpFVGEntryPct)) / 100.0;
   double entry = zoneNear + (zoneFar - zoneNear) * pct;
   entry = NormalizeDouble(entry, _Digits);

   double sl = bearish ? sweepExtreme + InpSLBufferPoints * g_point
                       : sweepExtreme - InpSLBufferPoints * g_point;
   sl = NormalizeDouble(sl, _Digits);

   double risk = bearish ? (sl - entry) : (entry - sl);
   if(risk <= 0.0)
      return(false);

   //--- TP
   double tp = 0.0;
   if(InpTargetMode == TARGET_LIQUIDITY)
     {
      double target = 0.0;
      if(!FindOppositeLiquidity(bearish, entry, target))
         return(false);
      tp = target;
     }
   else
     {
      tp = bearish ? entry - risk * InpTPRR : entry + risk * InpTPRR;
     }
   tp = NormalizeDouble(tp, _Digits);

   double reward = bearish ? (entry - tp) : (tp - entry);
   if(reward <= 0.0)
      return(false);
   if(reward / risk < InpMinRR)
      return(false);

   //--- ระยะห่างจากราคาปัจจุบัน / stops level
   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   long   stopsLevel = SymbolInfoInteger(_Symbol, SYMBOL_TRADE_STOPS_LEVEL);
   double minDist = (stopsLevel + 5) * g_point;

   if(bearish)
     {
      if(entry <= bid + minDist)
         return(false);              // ราคาผ่านโซนไปแล้ว
      if(sl - entry <= minDist)
         return(false);
      if(entry - tp <= minDist)
         return(false);
     }
   else
     {
      if(entry >= ask - minDist)
         return(false);
      if(entry - sl <= minDist)
         return(false);
      if(tp - entry <= minDist)
         return(false);
     }

   if(atr > 0.0 && InpMaxEntryDistATR > 0.0)
     {
      double dist = bearish ? (entry - bid) : (ask - entry);
      if(dist > InpMaxEntryDistATR * atr)
         return(false);
     }

   //--- lot
   double lot = CalcLot(risk);
   if(lot <= 0.0)
      return(false);

   string cmt = bearish ? "LCM_SELL" : "LCM_BUY";
   bool ok = bearish ? trade.SellLimit(lot, entry, _Symbol, sl, tp, ORDER_TIME_GTC, 0, cmt)
                     : trade.BuyLimit(lot, entry, _Symbol, sl, tp, ORDER_TIME_GTC, 0, cmt);

   if(!ok)
     {
      PrintFormat("LCM: วาง order ไม่สำเร็จ ret=%d %s | entry=%.*f sl=%.*f tp=%.*f lot=%.*f",
                  trade.ResultRetcode(), trade.ResultRetcodeDescription(),
                  _Digits, entry, _Digits, sl, _Digits, tp, g_lotDigits, lot);
      return(false);
     }

   tradesToday++;
   PrintFormat("LCM %s | swept=%.*f sweepBar=%d chochBar=%d | entry=%.*f sl=%.*f tp=%.*f RR=%.2f lot=%.*f",
               (bearish ? "SELL" : "BUY"), _Digits, sweptLevel, sweepBar, chochBar,
               _Digits, entry, _Digits, sl, _Digits, tp, reward / risk, g_lotDigits, lot);

   if(InpDrawObjects)
      DrawSetup(bearish, chochBar, zoneNear, zoneFar, sl, tp);

   return(true);
  }

//+------------------------------------------------------------------+
//| Lot sizing                                                       |
//+------------------------------------------------------------------+
double CalcLot(const double slDistancePrice)
  {
   if(slDistancePrice <= 0.0)
      return(0.0);

   double balance   = AccountInfoDouble(ACCOUNT_BALANCE);
   double riskMoney = balance * InpRiskPercent / 100.0;

   double tickValue = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE);
   double tickSize  = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
   if(tickValue <= 0.0 || tickSize <= 0.0)
      return(0.0);

   double lossPerLot = (slDistancePrice / tickSize) * tickValue;
   if(lossPerLot <= 0.0)
      return(0.0);

   double lot = riskMoney / lossPerLot;

   double mn   = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double mx   = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
   double step = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
   if(step <= 0.0)
      step = 0.01;

   lot = MathFloor(lot / step) * step;      // ปัดลงเสมอ
   lot = NormalizeDouble(lot, g_lotDigits);

   if(lot < mn)
      return(0.0);                          // เล็กกว่าขั้นต่ำ = ไม่เทรด (ไม่ปัดขึ้น)
   if(lot > mx)
      lot = mx;

   return(lot);
  }

//+------------------------------------------------------------------+
//| Pending management                                                |
//+------------------------------------------------------------------+
void ManagePendingOrders()
  {
   for(int i = OrdersTotal() - 1; i >= 0; i--)
     {
      ulong tk = OrderGetTicket(i);
      if(tk == 0)
         continue;
      if(OrderGetString(ORDER_SYMBOL) != _Symbol)
         continue;
      if(OrderGetInteger(ORDER_MAGIC) != InpMagic)
         continue;

      ENUM_ORDER_TYPE type = (ENUM_ORDER_TYPE)OrderGetInteger(ORDER_TYPE);
      double sl = OrderGetDouble(ORDER_SL);
      double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
      double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);

      //--- setup เสีย: ราคาไปโดน SL ก่อนที่ order จะถูก fill
      bool invalid = false;
      if(type == ORDER_TYPE_SELL_LIMIT && sl > 0.0 && ask >= sl)
         invalid = true;
      if(type == ORDER_TYPE_BUY_LIMIT  && sl > 0.0 && bid <= sl)
         invalid = true;
      if(invalid)
        {
         trade.OrderDelete(tk);
         continue;
        }

      //--- หมดอายุตามจำนวนแท่ง
      if(InpPendingExpiryBars > 0)
        {
         datetime setup = (datetime)OrderGetInteger(ORDER_TIME_SETUP);
         int secs = PeriodSeconds(InpEntryTF) * InpPendingExpiryBars;
         if(TimeCurrent() - setup >= secs)
            trade.OrderDelete(tk);
        }
     }
  }

//+------------------------------------------------------------------+
//| Position management: partial + BE + trailing                     |
//+------------------------------------------------------------------+
void ManageOpenPositions()
  {
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      ulong tk = PositionGetTicket(i);
      if(tk == 0)
         continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol)
         continue;
      if(PositionGetInteger(POSITION_MAGIC) != InpMagic)
         continue;

      ENUM_POSITION_TYPE ptype = (ENUM_POSITION_TYPE)PositionGetInteger(POSITION_TYPE);
      double open = PositionGetDouble(POSITION_PRICE_OPEN);
      double sl   = PositionGetDouble(POSITION_SL);
      double tp   = PositionGetDouble(POSITION_TP);
      double vol  = PositionGetDouble(POSITION_VOLUME);
      bool   isBuy = (ptype == POSITION_TYPE_BUY);
      double cur   = isBuy ? SymbolInfoDouble(_Symbol, SYMBOL_BID)
                           : SymbolInfoDouble(_Symbol, SYMBOL_ASK);

      if(sl <= 0.0)
         continue;

      // SL ถูกเลื่อนถึง BE แล้วหรือยัง (ใช้แทน state flag เพื่อให้ทน restart)
      bool beDone = isBuy ? (sl >= open) : (sl <= open);

      double risk = isBuy ? (open - sl) : (sl - open);
      if(!beDone && risk > 0.0 && InpUsePartial && InpTP1_RR > 0.0)
        {
         double trigger = isBuy ? open + risk * InpTP1_RR : open - risk * InpTP1_RR;
         bool hit = isBuy ? (cur >= trigger) : (cur <= trigger);
         if(hit)
           {
            double step = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
            if(step <= 0.0)
               step = 0.01;
            double mn = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);

            double closeVol = MathFloor((vol * InpPartialPercent / 100.0) / step) * step;
            closeVol = NormalizeDouble(closeVol, g_lotDigits);

            if(closeVol >= mn && (vol - closeVol) >= mn)
               trade.PositionClosePartial(tk, closeVol);

            double be = isBuy ? open + InpBEOffsetPoints * g_point
                              : open - InpBEOffsetPoints * g_point;
            be = NormalizeDouble(be, _Digits);
            if(PositionSelectByTicket(tk))
               trade.PositionModify(tk, be, tp);
            continue;
           }
        }

      //--- trailing หลัง BE
      if(beDone && InpUseTrailing && InpTrailATR > 0.0)
        {
         double atr = GetATR();
         if(atr <= 0.0)
            continue;
         double newSL = isBuy ? cur - InpTrailATR * atr : cur + InpTrailATR * atr;
         newSL = NormalizeDouble(newSL, _Digits);
         long stopsLevel = SymbolInfoInteger(_Symbol, SYMBOL_TRADE_STOPS_LEVEL);
         double minDist = (stopsLevel + 5) * g_point;

         if(isBuy && newSL > sl && (cur - newSL) > minDist)
            trade.PositionModify(tk, newSL, tp);
         if(!isBuy && newSL < sl && (newSL - cur) > minDist)
            trade.PositionModify(tk, newSL, tp);
        }
     }
  }

//+------------------------------------------------------------------+
//| Drawing (visual mode)                                            |
//+------------------------------------------------------------------+
void DrawSetup(const bool bearish, const int chochBar, const double zoneNear,
               const double zoneFar, const double sl, const double tp)
  {
   string id = "LCM_" + IntegerToString((int)TimeCurrent());
   datetime t1 = iTime(_Symbol, InpEntryTF, chochBar + 2);
   datetime t2 = iTime(_Symbol, InpEntryTF, 0) + PeriodSeconds(InpEntryTF) * 20;

   string zone = id + "_zone";
   if(ObjectCreate(0, zone, OBJ_RECTANGLE, 0, t1, zoneNear, t2, zoneFar))
     {
      ObjectSetInteger(0, zone, OBJPROP_COLOR, bearish ? clrTomato : clrDodgerBlue);
      ObjectSetInteger(0, zone, OBJPROP_FILL, true);
      ObjectSetInteger(0, zone, OBJPROP_BACK, true);
     }

   string slLine = id + "_sl";
   if(ObjectCreate(0, slLine, OBJ_TREND, 0, t1, sl, t2, sl))
     {
      ObjectSetInteger(0, slLine, OBJPROP_COLOR, clrRed);
      ObjectSetInteger(0, slLine, OBJPROP_STYLE, STYLE_DOT);
     }

   string tpLine = id + "_tp";
   if(ObjectCreate(0, tpLine, OBJ_TREND, 0, t1, tp, t2, tp))
     {
      ObjectSetInteger(0, tpLine, OBJPROP_COLOR, clrLimeGreen);
      ObjectSetInteger(0, tpLine, OBJPROP_STYLE, STYLE_DOT);
     }
  }
//+------------------------------------------------------------------+
