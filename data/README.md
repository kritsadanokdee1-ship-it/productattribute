# data/

Extracted from `ST_July_copy.xlsx` — the ATV (Asia Tires Ventures) price list for
SENTURY tyres, 2026 prices. Backing data for the Rokudo reports view.

Three renderings of the same 72 rows:

| File | Use |
|---|---|
| `sentury_pricelist_2026.csv`  | UTF-8 with BOM — paste or import straight into Google Sheets |
| `sentury_pricelist_2026.xlsx` | Same table with autofilter and a frozen header row |
| `sentury_pricelist_2026.json` | Machine-readable, for the app to consume directly |

## Columns

`แบรนด์`, `รุ่นยาง (Pattern)`, `ประเภท`, `ขนาดยาง`, `WL`, `Load/Speed Index`,
`ขอบ`, `Pricelist`, `ราคาทุน (Pack 12)`, `ราคาขาย (แนะนำ)`, `กำไร/เส้น`, `% กำไร`

Cost is the source file's **Pack 12** column; selling price is **ราคาแนะนำขาย**.

## Patterns

Pattern names are not text in the source file — they are images anchored over
column E. They were read from the embedded images and matched to row ranges via
the column-E merges:

| Pattern | Segment | Source rows | Sizes |
|---|---|---|---|
| Qirin 990 | Passenger / UHP | 6–30 | 25 |
| Roadtrexx H/T | SUV H/T | 31 | 1 |
| UHP1 | SUV UHP | 32–35 | 4 |
| Terraintrexx A/T | A/T | 36–43 | 8 |
| Mudtrexx M/T | M/T | 45–49 | 5 |
| Crossover | Sub/Compact SUV | 54–57 | 4 |
| Qirin 990 EV | EV, แก้มยางกำมะหยี่ | 64–88 | 25 |

## Margin is recomputed, not copied

The source file's `กำไร/เส้น` column is wrong: the formula reads `=K6-H6`, which
subtracts the **rim diameter** (column H) from the selling price instead of the
cost — so 175/65R15 showed 1675 where the real margin is 1690 − 1080 = 610. Only
19 of 72 rows carried the formula at all; the rest were `#REF!` from a broken
external link to `Z:\Price list - ATV\New Pricelist Sentury June 2026 3.xlsx`.

`กำไร/เส้น` here is `ราคาขาย − ราคาทุน`, computed for all 72 rows. Margins run
23.1%–53.3%, median 35%.

## Terms carried in the source header

- ผ่อน 0% 6 เดือน Support ดอกเบี้ย 100%
- รับประกัน 1 ปี หรือ 25,000 กม. บาด บวม แตก
