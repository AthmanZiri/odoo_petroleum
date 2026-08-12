# Jameel Petroleum — August 2026 Excel Ledger Review

**Period in workbooks:** 2026-08-01 → 2026-08-10 (not a full month)  
**Sources:** `JAMEEL SUPPLIERS AUGUST 2026.xlsx` · `JAMEEL CUSTOMERS AUGUST 2026.xlsx`  
**DB restore:** blocked — `jameel_petroleum_*.zip` and `AUGUST LOADING 2026` not uploaded

## Headline

| Metric | Suppliers | Customers |
|---|---:|---:|
| August txns | 157 | 274 |
| Loadings | 96 | 99 |
| Payments/transfers | 61 | 175 |
| Loading litres | 1,096,000 | 1,096,000 |

**Litre check:** supplier − customer = **0** (balanced).

## Trading margin (Excel cross-match)

Matched truck + grade + qty with ±1/±2 day tolerance; economics from **qty × unit price** (avoids double-counting CREDIT on multi-grade Excel rows).

| | |
|---|---:|
| Matched legs | 103 |
| Supplier-only | 8 |
| Customer-only | 11 |
| Buy total | 205,098,500.00 |
| Sell total | 206,375,900.00 |
| **Margin total** | **1,277,400.00** |
| Margin % of sell | 0.619% |
| Avg margin / litre | 1.2414 |
| Negative-margin legs | 2 |

Date offsets (customer − supplier): `{-1: 1, 0: 94, 1: 6, 2: 2}`

### Negative margin exceptions
- 2026-08-06/2026-08-06 `KCA 072Q` PMS 10000L · VITALAC INTERNATIONAL  LIMITED → DIMKA · buy 200.0 / sell 199.0 · **margin -10,000**
- 2026-08-05/2026-08-07 `KDL 369T→KAV 369B` PMS 6000L · VITALAC INTERNATIONAL  LIMITED → ARABIYA · buy 204.5 / sell 201.5 · **margin -18,000**

### Unmatched supplier loadings
- 2026-08-04 `KAV 369B` PMS 6000L @ 198.0 · VITALAC INTERNATIONAL  LIMITED · 1,188,000
- 2026-08-04 `KAV 369B` AGO 4000L @ 198.0 · VITALAC INTERNATIONAL  LIMITED · 792,000
- 2026-08-07 `KBK 308Q` AGO 16000L @ 198.0 · PREMIUM ENERGY LIMITED · 3,168,000
- 2026-08-07 `KDC 920Y` PMS 10000L @ 200.0 · VITALAC INTERNATIONAL  LIMITED · 2,000,000
- 2026-08-07 `KDT 943V` PMS 10000L @ 200.0 · VITALAC INTERNATIONAL  LIMITED · 2,000,000
- 2026-08-07 `KDG 103L` AGO 5000L @ 199.5 · VITALAC INTERNATIONAL  LIMITED · 997,500
- 2026-08-10 `KCN 025A` PMS 6000L @ 205.0 · FOSSIL SUPPLIES  LIMITED · 1,230,000
- 2026-08-10 `KBF 520W` AGO 10000L @ 199.0 · OIL HUB ENERGY LIIMITED · 1,990,000

### Unmatched customer loadings
- 2026-08-01 `KCR 924W` AGO 10000L @ 199.3 · PETROL KIM · 1,993,000
- 2026-08-01 `KBB 038G` PMS 10000L @ 199.3 · PETROL KIM · 1,993,000
- 2026-08-01 `KBS 311L` PMS 10000L @ 199.3 · PETROL KIM · 1,993,000
- 2026-08-05 `KAV 369B` PMS 3000L @ 203.5 · KHADIJA · 610,500
- 2026-08-05 `KAV 369B` AGO 2000L @ 203.5 · KHADIJA · 407,000
- 2026-08-05 `KAV 369B` AGO 2000L @ 204.5 · SHAMEEL · 409,000
- 2026-08-06 `KAV 369B` PMS 4000L @ 203.0 · ARABIYA · 812,000
- 2026-08-07 `KBK 308Q` AGO 14000L @ 198.3 · BOLD · 2,776,200
- 2026-08-07 `KDT 943V` PMS 7000L @ 203.3 · BOLD · 1,423,100
- 2026-08-07 `KBK 308Q` AGO 2000L @ 201.5 · MAQBUL · 403,000
- 2026-08-07 `KDT 943V` PMS 3000L @ 204.5 · MAQBUL · 613,500


### Note on remaining unmatched legs

Several unmatched rows are **split loads**: one supplier truck quantity is sold to multiple customers (or vice versa), so truck+grade+qty 1:1 matching fails. Examples:

- `KDT 943V` 10,000L PMS (Vitalac) ↔ Bold 7,000 + Maqbul 3,000
- `KBK 308Q` 16,000L AGO (Premium) ↔ Bold 14,000 + Maqbul 2,000
- `KAV 369B` Aug 4 Vitalac 6k PMS + 4k AGO ↔ Khadija/Shameel/Arabiya partials on Aug 5–6

Treat these as **allocation discrepancies to verify in Trading Desk / loadings sheet**, not missing volume (total litres already balance).

Aug 1 PETROL KIM three trucks have **no supplier side in the Aug suppliers workbook** (likely July purchase / opening stock) — confirm against loadings sheet and PO/bills once DB is restored.

## Payments / transfers (Excel)

- Supplier payments: **61** rows, debit **177,596,500** (ABSA/KCB/EQUITY/PREMIER/GULF)
- Customer receipts: **175** rows, credit **217,084,735** (banks + third-party payers e.g. PETRONET)

## Blocked until files arrive

1. **DB** `jameel_petroleum_2026-08-12_05-56-15.zip` → restore, then compare Trading Desk margin, P&L gross profit, PO vs bills, AR/AP closings, bank journals to the Excel figures above (target margin ≈ **1,277,400**).
2. **AUGUST LOADING 2026 (6).xlsx** → independent loadings countercheck.

## Artifacts

`data/reports/august_2026_reconcile_excel.json`, `aug_matched_loadings_v2.csv`, `aug_all_transactions.csv`, partner & closing CSVs.
