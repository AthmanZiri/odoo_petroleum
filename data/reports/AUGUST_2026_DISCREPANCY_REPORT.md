# Jameel Petroleum — August 2026 Discrepancy Report

**Period in workbooks / loadings:** 2026-08-01 → 2026-08-10 (not a full month)  
**DB dump:** `jameel_petroleum_2026-08-12_05-56-15.zip` → local Postgres DB **`jameel_petroleum_aug12`** (posted through **2026-08-11**; Aug-11 has journal activity only, no new deals/payments)  
**Sources:**  
- `JAMEEL SUPPLIERS AUGUST 2026.xlsx` · `JAMEEL CUSTOMERS AUGUST 2026.xlsx`  
- `AUGUST LOADING 2026.xlsx` (sheet `AUGUST LOADING REPORT 2026`)  
- Restored Odoo (Trading Desk deals, invoices/bills, P&L, payments, POs)

**Constraint:** Findings only — **no auto-posted corrections**.

---

## Headline bridge (KES / litres)

| Source | Litres | Margin / Gross |
|---|---:|---:|
| Excel ledgers (supplier = customer) | **1,096,000** | Matched truck legs margin **1,277,400** |
| AUGUST LOADING sheet | **1,126,000** | Unit margin **1,566,200** |
| Odoo loaded deals (Aug 1–11 dates) | **1,126,000** | Stored margin **1,635,200** (sell−buy **1,662,200**) |
| Odoo posted customer invoices (Aug-dated) | **1,320,000** | `petro_margin_total` **1,885,000** |
| Accounting P&L Gross (Aug 1–11) | — | **102,786,165** |

**Litre check (Excel):** supplier − customer = **0**.  
**Litre check (Loading ≡ Odoo deals):** **1,126,000 = 1,126,000**.  
**Excel short vs Loading/Odoo:** **−30,000 L**.

---

## 1. AUGUST LOADING vs Excel ledgers

| | Loading sheet | Excel customers | Delta |
|---|---:|---:|---:|
| Load legs (grade lines) | 117 | 114 | +3 |
| Litres | 1,126,000 | 1,096,000 | **+30,000** |
| PMS / AGO | 620k / 506k | 605k / 491k | +15k / +15k |

Prior Excel truck cross-match (with ±1/±2d tolerance): **103** matched legs, margin **1,277,400**; **8** supplier-only / **11** customer-only (mostly split loads — see prior section below).

Loading ↔ Excel customer (truck+grade+qty ±2d): **109** matched; **8** sheet-only (66k L); **5** excel-only (36k L).

Material pattern: Excel often records **split sales** while the loading sheet still shows the **full supplier truck** (or vice versa):

| Date | Truck | Sheet | Excel |
|---|---|---|---|
| 08-07 | `KBK 308Q` AGO | 16,000 → BOLD @ 198.3 | 14,000 BOLD + 2,000 MAQBUL |
| 08-07 | `KDT 943V` PMS | 10,000 → BOLD @ 203.3 | 7,000 BOLD + 3,000 MAQBUL |
| 08-07 | `KDC 920Y` PMS | 10,000 → BOLD (sheet-only vs excel) | (see Bold rows / date offsets) |

Sheet-only examples also include Reem/Fossil/OilHub legs (`KDL 369T`, `KCN 025A`, `KBF 520W`) that need partner/truck alias checks in the customer workbook.

**Negative margin (both Loading + Excel + Odoo):**  
`2026-08-06` `KCA 072Q` PMS 10,000L Vitalac → Dimka · buy 200 / sell 199 · **−10,000**.

Excel also flagged `KDL 369T→KAV 369B` PMS 6,000L Vitalac → Arabiya **−18,000**; Loading shows Reem on `KDL 369T` at +spread — treat as **allocation / naming** discrepancy, not missing volume.

---

## 2. AUGUST LOADING vs Odoo Trading Desk

| | |
|---|---:|
| Loaded deals (Aug dates) | **104** |
| Deal litres | **1,126,000** (= loading sheet) |
| Deal margin stored | **1,635,200** |
| Deal sell − buy | **1,662,200** |
| Loading sheet unit margin | **1,566,200** |
| Sheet vs deal sell−buy | **−96,000** |

Loading legs ↔ deals (truck/date/grade soft match): **112 / 117** legs matched; **5** unmatched load legs / **56,000 L** unused on deals (matcher noise on multi-grade / split rows — volumes still tie in aggregate).

### Deal margin data issue (report only)

| Deal | Stored margin | Sell − buy |
|---|---:|---:|
| **DEAL/2026/0761** (`KBY 554Z` Bold, 08-05) | **−24,000** | **+3,000** |

Recompute would raise Aug deal margin by **27,000** (no posting done).

### Invoice vs deal (Aug)

| | Litres | Margin |
|---|---:|---:|
| Aug-dated posted out_invoices | 1,320,000 | 1,885,000 |
| … of which deal date **before** Aug | **184,000** | **283,800** |
| Invoices for Aug-dated deals | 1,136,000 | — |
| Aug loaded deal qty | 1,126,000 | — |

**+10,000 L** on Aug-deal invoices vs deal qty is **DEAL/2026/0741**: base `INV/2026/00692` (10k) plus customer_sell price-adjustment docs `INV/2026/00707` / `00708` that still carry product qty (4k+6k). Economics are price adjustments; litre sums double-count if naïvely totaled.

All **122** Aug out_invoices have `deal_id` set.

---

## 3. Trading Desk margin vs Accounting P&L

Same structural gap as prior finance audits — **do not equate** P&L Gross with Desk margin.

### August 1–11 (posted)

| Line | KES |
|---|---:|
| P&L Revenue | 243,007,407 |
| P&L Cost of Sales (`expense_direct_cost`) | 140,221,242 |
| **P&L Gross** | **102,786,165** |
| Expenses | 86,407 |
| **P&L Net** | **102,699,758** |
| Desk invoice `petro_margin` | **1,885,000** |
| Gross − Desk gap | **~100.9M** |

### Volume timing (Aug product lines)

| | Litres |
|---|---:|
| Customer invoice qty (Aug-dated) | 1,320,000 |
| Vendor bill qty (Aug-dated) | **767,000** |
| Sold − billed buys | **+553,000** |

Purchases hit CoS when billed; Desk stamps buy on each sale. Under-billing purchases in-period **inflates Gross** vs matched trading spread.

### YTD through 2026-08-11

| | KES |
|---|---:|
| Revenue | 1,541,966,043 |
| CoS | 1,342,215,625 |
| Gross | 199,750,419 |
| Expenses | 2,464,944 |
| Net | 197,285,474 |

---

## 4. PO vs vendor bills (August position POs)

| | |
|---|---:|
| Aug position PO untaxed | **207,714,815** |
| Aug posted vendor bills untaxed | **139,820,926** |
| Open `qty_to_invoice` on Aug POs | **385,000 L / 77,517,000** |
| Open Aug POs | **7** |

Largest open (report only — do not bill blindly):

| PO | Date | Supplier | To invoice L | To invoice KES | Note |
|---|---|---|---:|---:|---|
| P00159 | 08-07 | VITALAC | 167,000 | 33,701,000 | `invoice_count=1` but qty invoiced 0 (cancelled bill pattern) |
| P00163 | 08-10 | VITALAC | 104,000 | 21,028,000 | Partial |
| P00153 | 08-05 | VITALAC | 73,000 | 14,630,000 | Partial |
| P00161 | 08-10 | OIL HUB | 20,000 | 3,980,000 | Partial |
| P00155 / P00152 | 08-06 / 08-04 | VITALAC | 10k each | ~2M each | Small remainder |

Fully billed Aug examples: Aftah P00147, Raad P00149, Skybarrel P00150, Premium P00158, Fossil P00160, etc.

---

## 5. Payments / transfers

### Excel (Aug 1–10 workbooks)

| | Count | Amount (KES) |
|---|---:|---:|
| Supplier payment rows | 61 | Debit **177,596,500** (banks ABSA/KCB/EQUITY/PREMIER/GULF) |
| Customer receipt rows | 175 | Credit **217,084,735** (banks + third parties e.g. PETRONET) |

### Odoo posted `account.payment` (Aug 1–10)

| | Count | Amount (KES) |
|---|---:|---:|
| Inbound | **180** | **220,646,839** |
| Outbound | **83** | **218,229,805** |

AR credits / AP debits (same window): receipts **220,685,258** · supplier payments **217,781,500**.

| Gap | Approx |
|---|---:|
| Odoo inbound − Excel customer credits | **~+3.6M** |
| Odoo outbound − Excel supplier debits | **~+40.6M** |

Likely drivers (not corrected here): Excel incomplete bank coverage / third-party labeling, Odoo including more AP clearings, timing vs statement cut, and bank↔M-Pesa funding entries.

### Bank ↔ M-Pesa funding (Odoo refs)

| Date | Move | Ref | Amount |
|---|---|---|---:|
| 08-01 | PREM/2026/00073 | Transfer Premier → M-Pesa | 130,716 |
| 08-08 | KCB/2026/00142 | Transfer KCB → M-Pesa | 250,000 |
| 08-08 | KCB/2026/00143 | Transfer KCB → M-Pesa | 44,250 |

These are **internal liquidity moves**, not supplier/customer settlements — exclude when reconciling Excel partner ledgers to Desk.

---

## 6. Excel ledger review (unchanged baseline)

Retained from pre-restore Excel-only pass:

| Metric | Suppliers | Customers |
|---|---:|---:|
| August txns | 157 | 274 |
| Loadings | 96 | 99 |
| Payments/transfers | 61 | 175 |
| Loading litres | 1,096,000 | 1,096,000 |

Matched truck economics: buy **205,098,500** · sell **206,375,900** · margin **1,277,400** (0.619% of sell).

Unmatched / split-load notes from Excel remain valid; Loading + Odoo now confirm the **30k L** Excel shortfall and that Desk deals track the Loading sheet total.

---

## Recommended next actions (manual — do not auto-post)

1. **Excel ledgers:** Add / re-allocate the **30,000 L** gap vs Loading (split Bold/Maqbul trucks + Reem/Fossil/OilHub sheet-only legs).  
2. **DEAL/2026/0761:** Recompute stored `margin_total` to sell−buy (**+3,000**).  
3. **Price-adj invoices:** When totaling litres, exclude `petro_price_adjustment` customer_sell docs (or zero their qty) so Desk ≠ invoice litre bridges stay clean.  
4. **P00159 / Aug open POs:** Decide bill vs cancel vs link; **77.5M** open CoS backlog explains part of Gross vs Desk.  
5. **Payments:** Reconcile the **~41M** Excel vs Odoo supplier payment gap by bank journal (ABSA/KCB first) before trusting either AR/AP closing.  
6. **P&L:** Keep Gross as statutory period view; use Loading / deal / `petro_margin` for trading spread (~**1.6–1.9M** Aug), not **~103M** Gross.

---

## Artifacts

| File | Content |
|---|---|
| `august_2026_reconcile_excel.json` | Excel truck cross-match |
| `august_2026_excel_summary.json` | Excel workbook totals |
| `august_loading_parsed.json` / `august_loading_legs.csv` | Parsed AUGUST LOADING |
| `august_2026_odoo_crosscheck.json` | Loading ↔ Excel ↔ Odoo bridges |
| `aug_matched_loadings_v2.csv`, `aug_*_only_loadings.csv`, closings CSVs | Excel detail extracts |

**Restore note:** DB name `jameel_petroleum_aug12` on compose Postgres; web container restarted after restore. No correction wizards or margin backfills were executed.
