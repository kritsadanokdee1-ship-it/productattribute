# LCM EA (MT5) — Liquidity → CHoCH → Mitigation

EA แปลงโมเดล **L-C-M** เป็นโค้ด MQL5 สำหรับ backtest บน MetaTrader 5

> ⚠️ **เพื่อการศึกษาและ backtest เท่านั้น ไม่ใช่คำแนะนำการลงทุน**
> โค้ดนี้ยังไม่เคยถูกคอมไพล์ทดสอบ (เขียนบน Linux ที่ไม่มี MetaEditor) — ถ้าเจอ error ตอนคอมไพล์ให้แจ้งกลับมาแก้

---

## ติดตั้ง

1. เปิด MT5 → `File > Open Data Folder`
2. คัดลอก `LCM_EA.mq5` ไปที่ `MQL5/Experts/`
3. เปิด MetaEditor (F4) → เปิดไฟล์ → กด **Compile** (F7)
4. กลับมาที่ MT5 → กด **Ctrl+R** เปิด Strategy Tester → เลือก `LCM_EA`

---

## ตรรกะที่โค้ดทำจริง

| ขั้น | เงื่อนไขในโค้ด | ฟังก์ชัน |
|---|---|---|
| **Bias** | โครงสร้าง HH/HL vs LH/LL บน H4 (หรือ EMA) | `BiasDirection()` |
| **L** | หาแท่งใน `SweepLookback` ล่าสุดที่ `high > swingHigh + MinSweepPoints` **และ `close < swingHigh`** (รวม PDH/PDL) | `FindSweep()` |
| **C** | หา swing low ที่เกิดก่อน sweep แล้วรอแท่งที่ **ปิด** ต่ำกว่าจุดนั้น | `FindRefStructure()` + `FindCHoCH()` |
| **displacement** | body ของแท่ง CHoCH ≥ `DisplacementATR × ATR` | `HasDisplacement()` |
| **M** | หา FVG (`low[m+1] > high[m-1]`) รอบแท่ง CHoCH แล้ววาง **Sell Limit** ที่ขอบโซน | `FindFVG()` |
| **SL** | เหนือจุดที่กวาด + `SLBufferPoints` | `TrySetup()` |
| **TP** | RR คงที่ หรือ liquidity ฝั่งตรงข้าม (ต้องผ่าน `MinRR`) | `FindOppositeLiquidity()` |
| **Lot** | `risk% ÷ (SL distance × tick value)` — **ปัดลงเสมอ** ต่ำกว่า min lot = ไม่เทรด | `CalcLot()` |
| **จัดการไม้** | ปิดครึ่งที่ TP1 → เลื่อน SL ไป BE → (ออปชัน) trail ด้วย ATR | `ManageOpenPositions()` |
| **ยกเลิก setup** | pending หมดอายุตามจำนวนแท่ง หรือราคาไปโดน SL ก่อน fill | `ManagePendingOrders()` |

---

## Inputs หลัก (ค่า default ตั้งมาสำหรับ XAUUSD M5)

### Timeframes
| Input | Default | ความหมาย |
|---|---|---|
| `InpEntryTF` | M5 | TF ที่หา sweep / CHoCH / entry |
| `InpBiasTF` | H4 | TF ที่หา bias |

### Bias
| Input | Default | ความหมาย |
|---|---|---|
| `InpBiasMode` | BIAS_STRUCTURE | `OFF` / `EMA` / `STRUCTURE` |
| `InpBiasSwingStrength` | 3 | ความแรง swing บน bias TF |

### L — Liquidity
| Input | Default | ความหมาย |
|---|---|---|
| `InpSwingStrength` | 2 | fractal กี่แท่งซ้าย-ขวา |
| `InpLiquidityLookback` | 60 | มองหา liquidity ย้อนหลังกี่แท่ง |
| `InpSweepLookback` | 12 | sweep ต้องเพิ่งเกิดภายในกี่แท่ง |
| `InpMinSweepPoints` | 20 | ต้องทะลุระดับอย่างน้อยกี่ point |
| `InpUseDailyLevels` | true | นับ PDH/PDL เป็น liquidity ด้วย |

### C — CHoCH
| Input | Default | ความหมาย |
|---|---|---|
| `InpMinBreakPoints` | 10 | ปิดแท่งทะลุขั้นต่ำ |
| `InpDisplacementATR` | 0.8 | body ≥ x×ATR (0 = ปิดเช็ค) |

### M — Entry
| Input | Default | ความหมาย |
|---|---|---|
| `InpRequireFVG` | true | ไม่มี FVG = ไม่เข้า |
| `InpMinFVGPoints` | 15 | ขนาด gap ขั้นต่ำ |
| `InpFVGEntryPct` | 0 | 0 = ขอบใกล้ราคา (fill ง่าย), 100 = ขอบไกล (RR ดีกว่า) |

### Risk
| Input | Default | ความหมาย |
|---|---|---|
| `InpRiskPercent` | 1.0 | % ของ balance ต่อไม้ |
| `InpSLBufferPoints` | 250 | buffer เหนือจุดกวาด — **XAUUSD 2 digits: 250 point = $2.50** |
| `InpTPRR` | 2.5 | RR เป้าหมาย |
| `InpMinRR` | 2.0 | ต่ำกว่านี้ = ไม่เข้า |
| `InpTP1_RR` / `InpPartialPercent` | 1.0 / 50% | ปิดครึ่งที่ RR 1:1 แล้วเลื่อน BE |

> **หน่วย point ขึ้นกับโบรก** — XAUUSD บางเจ้าเป็น 2 digits (point = 0.01) บางเจ้า 3 digits (point = 0.001) ถ้าเป็น 3 digits ให้คูณค่า `*Points` ทั้งหมด **×10**

---

## ตั้งค่า Strategy Tester ที่แนะนำ

| หัวข้อ | ค่า |
|---|---|
| Symbol | XAUUSD |
| Period | **M5** (ต้องตรงกับ `InpEntryTF`) |
| Modelling | **Every tick based on real ticks** (สำคัญมาก — โมเดลนี้ใช้ไส้เทียน) |
| Deposit | 2,000 USD |
| Leverage | 1:100 |
| Period ทดสอบ | อย่างน้อย 1–2 ปี |

**อย่าใช้ "Open prices only"** — จะได้ผลหลอกเพราะ EA พึ่งพา wick และ limit fill

---

## แนวทาง optimize (เรียงตามผลกระทบ)

1. `InpFVGEntryPct` — 0 / 25 / 50 / 75 (trade-off ระหว่างอัตราการ fill กับ RR)
2. `InpSLBufferPoints` — 150 → 400 step 50
3. `InpDisplacementATR` — 0.4 → 1.4 step 0.2
4. `InpTPRR` — 1.5 → 4.0 step 0.5
5. `InpSweepLookback` — 6 → 20 step 2
6. `InpBiasMode` — ลองทั้ง 3 โหมด

**ระวัง overfitting:** optimize บนช่วงเวลา A แล้วต้องเอาพารามิเตอร์ไปทดสอบซ้ำบนช่วง B ที่ไม่เคยเห็น (walk-forward) ถ้าผลพังทันที = ฟิตกับ noise

---

## ข้อจำกัดที่รู้อยู่ (อ่านก่อนเชื่อผล backtest)

1. **ไม่มี news filter** — MT5 tester ไม่มีข้อมูลปฏิทินข่าว เช็กลิสต์ข้อ 6 (เลี่ยง NFP/CPI/FOMC) จึงทำในโค้ดไม่ได้ ใช้ `InpUseTimeFilter` เลี่ยงช่วงเวลาแทนได้บางส่วน — ผลจริงจะแย่กว่า backtest เสมอ
2. **Equal Highs/Lows ยังไม่ได้แยกออกมาเป็นเงื่อนไขเฉพาะ** — โค้ดใช้ swing high/low ทั่วไป + PDH/PDL ถ้าอยากบังคับ EQH จริงต้องเพิ่มเงื่อนไข tolerance เอง
3. **Slippage/commission** — ต้องตั้งใน tester เอง ทองมี commission และ spread ถ่างช่วงตลาดเปิด ผล backtest ที่ไม่ใส่ต้นทุนจริงจะสวยเกินจริงมาก
4. **Trailing ทำงานหลัง BE เท่านั้น** — ถ้าปิด `InpUsePartial` จะไม่มีการเลื่อน BE จึงไม่มี trailing ด้วย
5. **ไม่รองรับหลาย symbol พร้อมกัน** — ออกแบบให้แปะกราฟเดียวต่อ 1 instance

---

## ถ้าผล backtest ออกมาแย่ ให้ไล่เช็กตามนี้

| อาการ | สาเหตุที่พบบ่อย | แก้ |
|---|---|---|
| ไม่มีไม้เลย | เงื่อนไขแน่นเกิน | ตั้ง `InpBiasMode = BIAS_OFF`, `InpRequireFVG = false`, `InpDisplacementATR = 0` แล้วดูว่ามีไม้ไหม แล้วค่อยเปิดกลับทีละตัว |
| ไม้เยอะแต่ไม่ fill | โซนอยู่ไกลเกิน | เพิ่ม `InpPendingExpiryBars`, ลด `InpFVGEntryPct` เป็น 0 |
| โดน SL ถี่ | buffer แคบ | เพิ่ม `InpSLBufferPoints` |
| lot = 0 / ไม่มี order | balance เล็กเทียบกับ SL | เพิ่มทุน หรือลด `InpRiskPercent` ไม่ได้ (มันจะยิ่งเล็ก) → ต้องเพิ่มทุน |

ดู log ใน tab **Journal / Experts** — EA พิมพ์รายละเอียดทุกไม้ (sweep level, sweepBar, chochBar, entry, SL, TP, RR, lot) และเหตุผลที่วาง order ไม่สำเร็จ
