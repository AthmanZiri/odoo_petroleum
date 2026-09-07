# Jameel Petroleum Limited

**31 August 2026 customer and supplier ledger cut-over**

| | |
|---|---|
| Date of this report | 7 September 2026 |
| Applied to | Live database `jameel_petroleum` (Odoo 19) |
| Cut-over date in the books | 31 August 2026 |
| Source of truth | August 2026 Excel customer and supplier ledgers |
| Prepared for | Directors, Finance, and Trading |

---

## 1. One-page summary

On the morning of 7 September 2026 the live books were reset to the August Excel ledgers and then left to run from 1 September onward.

The workbooks are **full August partner ledgers**, not a list of opening balances. Each tab is one customer or supplier: a brought-forward figure, every August loading and payment, and a running `BALANCE`. After cut-over, Odoo as at 31 August matches that `BALANCE` cell for every partner.

**What was done**

1. A snapshot of live was taken first (`jameel_petroleum_pre_aug31`).
2. Everything dated before 1 September was removed, except Capital & Loans and Staff Claims.
3. Both August workbooks were imported: B/F as a 31 July opening, every August loading as a customer invoice or vendor bill, every August payment as a bank entry.
4. Sheet `BALANCE` was then locked. Where imported lines did not already land on that figure, one Excel-close adjustment was posted.

**Result as at 31 August 2026**

| | Workbook | Odoo | Difference |
|---|---:|---:|---:|
| Customer AR | 57,931,140 | 57,931,140 | 0 |
| Supplier AP (workbook sign) | 33,527,669 | 33,527,669 | 0 |
| Combined (AR + AP) | 91,458,809 | 91,458,809 | 0 |
| Partner sections reconciled | 186 | 186 | 0 mismatches |

**1–7 September was not touched.** 196 journal entries, 77 deals, 87 sale orders, 16 purchase orders, 25 daily positions, 77 trips, and 21 Muhidin loans are still there.

**What this is not.** Bank and profit-and-loss before September now follow the Excel lines only. They will not match the old May–July import history. That is intended.

Rollback, if ever needed: restore `jameel_petroleum` from template `jameel_petroleum_pre_aug31`.

---

## 2. Why this was done

The live books had grown a messy pre-cut-over history (May–July imports, duplicate partners, inverted supplier payments on earlier trials, and trading documents that did not agree with the Excel ledgers finance actually uses).

Two approaches were considered:

- **Opening-only cut-over** — wipe history and post one receivable/payable per partner equal to the 31 August close. Fast, but August loadings and payments would disappear.
- **Ledger replay** — wipe history, then reproduce the Excel month as real documents. Chosen. Finance can still open August invoices, bills, and bank entries, and 31 August still matches the sheet.

The instruction for the live run was explicit: **treat the Excel books as source of truth.** If Odoo and the sheet disagreed after import, the sheet won.

---

## 3. Source files and how they were read

| Workbook | File | Usable partner tabs | Ledger sections parsed |
|---|---|---:|---:|
| Customers | `JAMEEL CUSTOMERS AUGUST 2026 (1).xlsx` | 111 (Sheet1 / Sheet2 skipped) | 122 |
| Suppliers | `JAMEEL SUPPLIERS AUGUST 2026 (1).xlsx` | 61 | 64 |
| **Total** | | **172** | **186** |

A few tabs contain more than one header block (for example a receivable pane and a payable pane, or a copied header). Each block is a section. That is why 172 tabs became 186 sections.

**Sign convention (as written on the sheets)**

- Customers (AR): +Debit −Credit. Positive means the customer owes Jameel. Negative means the customer is in credit.
- Suppliers (AP): +Credit −Debit. Positive means Jameel owes the supplier. Negative means Jameel has prepaid.

Many supplier sheets put Credit before Debit. The importer does **not** trust column order for payments. A row marked `PAYMENT` always settles the partner; `REFUND` reverses it. That rule was added after the trial clone showed RAAD, Skybarrel, Premium, and Oil Hub at roughly twice payable, because payments had been posted as extra bills.

**Special layouts**

- **REEM VENTURES** is a two-pane sheet (loadings on the left, payments and B/F on the right). B/F 16,851,253.11; 25 loadings; 36 payments; close **19,316,420.61**.
- Three supplier tabs reuse another partner’s title in cell A1. The **tab name** is used, not A1:

| Tab | A1 title (ignored) | Partner created / used | 31 Aug close |
|---|---|---|---:|
| PRIZE | ENWORLD HOLDING LIMITED | PRIZE (created) | 0 |
| GAPCO IRO | GAPCO KENYA LIMITED | GAPCO IRO | −1,000 |
| PETRO IRSHAD | PETRO OIL KENYA LIMITED | PETRO IRSHAD (created) | 0 |

**Name matching.** Short Excel names are mapped to the existing commercial partner where one already exists (for example DARRUSALAAM → DARUSALAAM, PETROL KIM → PETROLKIM, BLUE → BLUE JAY AGENCY LTD, REEM VENTURES LIMITED → REEM VENTURES). When two partners share a name, the importer takes the one with the higher customer + supplier rank. That is why BLOT/BOLD activity from the customer book went to partner id 6, not the quieter duplicate id 337.

---

## 4. What was deleted (everything before 1 September)

The wipe kept journals **CAPLN** (Capital & Loans) and **STCLM** (Staff Claims). Everything else dated before 1 September was removed.

| Removed | Count |
|---|---:|
| Journal entries | 3,761 |
| Payments | 1,586 |
| Trading deals | 1,003 |
| Daily position lines | 321 |
| Trips | 1,052 |
| Sale orders | 999 |
| Purchase orders | 199 |

After the wipe, no pre-September deals, sale orders, purchase orders, positions, or trips remain. September counts were checked after import and match the pre-wipe September population:

| Still on live (1–7 September) | Count |
|---|---:|
| Posted journal entries | 196 |
| Deals | 77 |
| Sale orders | 87 |
| Purchase orders | 16 |
| Daily positions | 25 |
| Trips | 77 |
| Loans issued (Muhidin) | 21 |

September journals: 87 customer invoices, 22 vendor bills, 86 miscellaneous/bank entries, 1 in-receipt. Banks used in September: KCB 28, Equity 24, ABSA 21, Premier 7, plus 4 Capital & Loans, 2 miscellaneous, 1 staff claim.

---

## 5. What was posted from the workbooks

Batch reference: **PETRO-IMP-AUG31-2026**. Dates on the batch run from 31 July (openings) through 31 August. 1,475 documents, zero section errors.

| Document | Count | How it is produced |
|---|---:|---|
| Opening entries (31 July) | 53 | B/F, plus any pre-1-August lines on the sheet (there were none) |
| Customer invoices | 343 | August AR loadings (PMS / AGO / IK, price, truck, invoice no.) |
| Vendor bills | 318 | August AP loadings |
| Bank / cash payments | 760 | August PAYMENT / REFUND rows |
| Excel-close adjustments | 1 | Forces sheet `BALANCE` where lines alone did not |

343 + 318 = **661 August loadings**, which is exactly the number of loading rows the importer read. **760 payments** matches the payment rows. **53 openings** matches the 53 sections whose opening was not zero.

**Payment journals** (from the payer name on the sheet):

| Journal | Code | Entries in the batch |
|---|---|---:|
| ABSA Bank | ABSA | 262 |
| KCB Bank | KCB | 167 |
| Bank — Unspecified | BNKU | 141 |
| Equity Bank | EQTY | 98 |
| Premier Bank | PREM | 82 |
| Gulf African Bank | GULF | 10 |
| Sales | INV | 343 |
| Purchases | BILL | 318 |
| Miscellaneous (openings + lock) | MISC | 54 |

Payer names ABSA, KCB, EQUITY, PREMIER, GULF, and MPESA map to those journals. Anything else (cash, “transfer”, a person’s name) goes to **Bank — Unspecified**. Prices were taken as written. No sales or purchase tax was applied on the import, so invoice and bill totals stay equal to the sheet amounts.

---

## 6. 31 August balances — every partner that is not zero

Odoo figures below are as at 31 August (September sits on top and is excluded from this comparison). All of these match the sheet. Amounts in KES.

### 6.1 Customers (AR) — 31 partners, 57,931,140

Positive = customer owes Jameel. Negative = customer is in credit / prepaid.

| Partner | B/F 31 Jul | Aug loadings | Aug payments | 31 Aug close |
|---|---:|---:|---:|---:|
| REEM VENTURES LIMITED | 16,851,253 | 25 | 36 | 19,316,421 |
| BOLD | 16,956,100 | 137 | 131 | 10,549,048 |
| MAQBUL | 5,232,000 | 12 | 23 | 6,113,700 |
| WAFI | 5,399,093 | 8 | 12 | 5,769,094 |
| PETROL KIM | 1,199,902 | 37 | 15 | 5,443,402 |
| WBP INVEST. | 0 | 6 | 16 | 4,918,000 |
| ELYAAS | 0 | 7 | 10 | 2,015,000 |
| MARZIQ | 2,405,000 | 4 | 4 | 1,995,000 |
| QUBAA | 0 | 2 | 3 | −1,990,000 |
| LANDMARK | 41,635 | 5 | 14 | −1,891,365 |
| MOHAMED | 0 | 2 | 6 | −824,000 |
| KUSOW | 2,495,117 | 6 | 78 | 805,903 |
| KHADIJA | 603,000 | 5 | 11 | 797,000 |
| GULNAZ | 824,000 | 1 | 3 | 742,600 |
| SHAMEEL | 703,590 | 6 | 17 | 696,790 |
| BLUE | 647,500 | 0 | 0 | 647,500 |
| SAYUSA | 890,000 | 7 | 9 | 560,000 |
| UPSALA | 0 | 2 | 10 | 545,000 |
| HOKOLA | 646,150 | 2 | 19 | 400,300 |
| DARRUSALAAM | 7,023,624 | 6 | 17 | 359,625 |
| TRANSFORCE INVEST. | 355,556 | 0 | 0 | 355,556 |
| SAKATII | 599,527 | 5 | 28 | 344,527 |
| CHESEFIELD | 70,100 | 4 | 7 | 289,100 |
| AUTOPORT | −73,779 | 0 | 0 | −73,779 |
| RAMCO | 698,568 | 1 | 5 | 41,068 |
| RANWAY | 3,000 | 0 | 0 | 3,000 |
| ECONOMY | 2,900 | 0 | 0 | 2,900 |
| MWAMU | 296,736 | 1 | 11 | −264 |
| OREY | 7,110,200 | 1 | 2 | 200 |
| SALLAM | −100 | 0 | 0 | −100 |
| HERMOON | −86 | 0 | 0 | −86 |
| **AR total** | | **343** | | **57,931,140** |

RANWAY 3,000 and ECONOMY 2,900 **are** Excel closes. They are not leftovers from the old books.

The six largest debtors (REEM, BOLD, MAQBUL, WAFI, PETROL KIM, WBP) are **52.1 million**, about 90% of AR.

### 6.2 Suppliers (AP) — 20 partners, 33,527,669

Positive = Jameel owes the supplier. Negative = prepaid.

| Partner | B/F 31 Jul | Aug loadings | Aug payments | 31 Aug close |
|---|---:|---:|---:|---:|
| PIN OIL | 9,277,500 | 30 | 8 | 34,799,500 |
| ASTROMILE ENERGY LIMITED | −3,171,967 | 1 | 6 | −3,171,967 |
| VITALAC INTERNATIONAL LIMITED | 24,357,955 | 240 | 120 | 2,243,455 |
| KENGAS KENYA LIMITED | 737,631 | 2 | 4 | 737,631 |
| PETRO OIL KENYA LIMITED | 635,031 | 0 | 0 | 635,031 |
| LEADWAY PETROLEUM LIMITED | −540,000 | 0 | 0 | −540,000 |
| DALBIT PETROLEUM LIMITED | −539,571 | 0 | 0 | −539,571 |
| BE ENERGY LIMITED | −425,452 | 0 | 0 | −425,452 |
| ABRAHAM MAHAT | 300,000 | 0 | 0 | 300,000 |
| TARITA | −200,000 | 0 | 0 | −200,000 |
| DC ENERGY LIMITED LIMITED | −175,150 | 0 | 0 | −175,150 |
| AFTAH PETROLEUM LIMITED | 3,949,000 | 2 | 4 | −125,000 |
| GAPCO KENYA LIMITED | 122,891 | 0 | 0 | 122,891 |
| TOTAL ENERGIES MARKETING | −57,180 | 7 | 2 | −57,180 |
| INDEPENDENT PETROLEUM GROUP | −51,659 | 0 | 0 | −51,659 |
| WNINE ENERGY LIMITED | −11,200 | 0 | 0 | −11,200 |
| OCEAN ENERGY LIMITED | −5,000 | 0 | 0 | −5,000 |
| KENCOR FORT RETAIL KENYA LTD | −4,500 | 0 | 0 | −4,500 |
| OLA ENERGIES KENYA LTD | −2,160 | 2 | 2 | −3,160 |
| GAPCO IRO | −1,000 | 0 | 0 | −1,000 |
| **AP total** | | **318** | | **33,527,669** |

PIN OIL alone is 34.8 million payable. Astromile’s 3.2 million prepaid is the main offset. Vitalac opened August at 24.4 million and closed at 2.2 million after 240 bills and 120 payments.

### 6.3 Partners who traded in August and closed at zero

These 35 sections are on the books as August invoices/bills/payments and correctly show **nil** at 31 August. They are not missing.

| Sheet | Side | Opening | Loadings | Payments |
|---|---|---:|---:|---:|
| MALUINI | AR | 3,955,000 | 10 | 17 |
| ARABIYA | AR | 2,163,268 | 4 | 14 |
| QUALITY | AP | 9,765,000 | 0 | 5 |
| SKYHAS | AP | 1,970,000 | 0 | 1 |
| BURKO | AR | 1,740,000 | 0 | 1 |
| MAOW | AR | 1,382,000 | 6 | 9 |
| ZAYNU | AR | 0 | 6 | 10 |
| RAAD | AP | 0 | 7 | 6 |
| PREMIUM | AP | 0 | 7 | 5 |
| SKYBARREL | AP | 0 | 5 | 8 |
| TRANSGLIDE | AR | 0 | 5 | 6 |
| OIL HUB | AP | 0 | 6 | 5 |
| DIMKA | AR | 0 | 3 | 5 |
| CHEVAM | AP | 0 | 4 | 4 |
| FRABIJE | AR | 0 | 2 | 3 |
| NATO | AR | −144,832 | 0 | 1 |
| HK, NURKEN, BAZMALINK, HESFAN, GACAL, BRENTWOOD, FOSSIL | mixed | 0 | 1–2 | 2–3 |
| ABSAL, FACHINO, PETRO POINT, DOKOTA, HASHAM, MAJESTIC, BILL, SIMAD, TASANAAH, ZAHIRA, ONE P., SALMAN | mixed | 0 | 1 | 1 |

RAAD, Skybarrel, Premium, and Oil Hub are the suppliers that looked double-counted on the first trial, when payment signs were inverted. After the fix they close at zero, which is what the sheets say.

The remaining ~100 sections are blank or already nil with no August rows. They were parsed, reconciled, and left at zero. They do not appear on the import mismatch table because both sides are zero.

---

## 7. Decisions and exceptions

### 7.1 Excel close lock — Astromile

One journal entry was posted on 31 August:

- Reference: `Excel close ASTROMILE ENERGY LIMITED`
- Creditors Control Account: **credit 2,385,000**
- Contra: Opening Balance Import equity

Astromile’s sheet opens and closes at **−3,171,967** (prepaid) and also lists one August loading and six payments. Three of those payments (Chevam transfer 1,200,000; ABSA 1,000,000 and 200,000) do not stay in the sheet’s running close. A 15,000 Capital & Loans inter-transfer dated 22 July was also kept on purpose (CAPLN is not wiped).

Net: after import, Odoo was 2,385,000 more prepaid than the sheet (`2,400,000 − 15,000`). Because Excel is the source of truth, the lock reversed that 2,385,000 so the 31 August partner balance is exactly **−3,171,967**.

The three transfer rows remain visible as August bank entries. The lock is the document that makes the close agree with the cell finance signed off.

### 7.2 Two BOLD partners

| Partner id | Name | Rank used | AR at 31 Aug | AR now (7 Sep) | September invoices |
|---:|---|---:|---:|---:|---:|
| 6 | BOLD | 1,451 (chosen) | 10,549,048 | 35,775,848 | 13 |
| 337 | BOLD | 51 | 0 | 18,447,452 | 24 |

The August customer book was posted on id 6. September invoices already sitting on the duplicate (id 337, about 18.5 million) were left alone. Finance should decide whether those September invoices belong on the main BOLD and merge the contacts.

### 7.3 Partners created by the import

Only two new commercial partners were created, both from the mis-titled supplier tabs: **PRIZE** and **PETRO IRSHAD**. Both close at zero.

### 7.4 What was deliberately not wiped

**Loans issued to Muhidin — 21 posted, KES 17,137,340.17 outstanding.** Capital & Loans journals from 30 June through 3 September remain (26 entries). Nothing was received back; these are not mixed with the Excel AR/AP ledgers.

| Loan | Amount |
|---|---:|
| LOAN/0001 | 9,676,340.17 |
| LOAN/0012 | 2,000,000 |
| LOAN/0008, LOAN/0011 | 600,000 each |
| LOAN/0006 | 595,000 |
| LOAN/0019 | 500,000 |
| LOAN/0017 | 475,000 |
| LOAN/0009 | 367,000 |
| LOAN/0016 | 340,000 |
| LOAN/0007 | 312,000 |
| LOAN/0018 | 295,000 |
| LOAN/0015 | 260,000 |
| LOAN/0002, LOAN/0021 | 200,000 each |
| LOAN/0004, LOAN/0013 | 150,000 each |
| LOAN/0010 | 103,000 |
| LOAN/0022 | 100,000 |
| LOAN/0014 | 82,000 |
| LOAN/0020 | 75,000 |
| LOAN/0005 | 57,000 |
| **Total** | **17,137,340.17** |

Staff Claims: one posted entry remains (KES 2,250, in September).

### 7.5 Trial clone before live

The same wipe and import were run first on `jameel_petroleum_aug31_import` (a clone of live). That is where the supplier payment-sign bug was found and fixed, and where the Excel-close lock was proven (0 mismatches, same 91,458,809 total). Live was not changed until that clone was clean and the instruction was given to treat Excel as truth.

---

## 8. How to read the books from 1 September

- **Partner statements as at 31 August** should now match the Excel August ledgers. If a later Excel revision changes a close, say so — do not “fix” Odoo back to the old import.
- **1 September onward** is live trading on top of those closes. Today’s AR (about 162.6 million) and AP (about 124.6 million payable in raw ledger terms) include 1–7 September and are **not** comparable to the 31 August Excel.
- **Do not raise new May–July invoices or bills** for fuel that is now represented by the 31 July openings. That would double the books.
- **Bank and P&L before September** are rebuilt from the Excel payment and loading rows only. They will not reproduce the previous May–July imported history, and they will not include bank movements that never appeared on a customer or supplier sheet.
- **Opening Balance Import** is the equity clearing account for the 53 openings and the Astromile lock. It is not a trading account.

---

## 9. Databases and rollback

| Database | Role |
|---|---|
| `jameel_petroleum` | Live. Cut-over applied 7 September 2026. |
| `jameel_petroleum_pre_aug31` | Snapshot of live taken immediately before the wipe. Use this to roll back. |
| `jameel_petroleum_aug31_import` | Trial clone. Can be dropped when no longer needed. |

To roll back: terminate connections to `jameel_petroleum`, drop it, and recreate it `WITH TEMPLATE jameel_petroleum_pre_aug31`.

---

## 10. Technical notes (for the implementer)

- Importer: `petroleum.data.import`, cutoff `2026-08-01`, batch `PETRO-IMP-AUG31-2026`, `clean_existing` off on the live run (the wipe had already cleared the old documents).
- Wipe implementation: SQL detach of foreign keys, then delete of pre-1-Sep moves and payments except journals CAPLN and STCLM; then ORM unlink of deals, positions, trips, desk expenses, sale orders, and purchase orders dated before 1 September.
- Lock date: last day of the cutoff month when cutoff is the 1st → **31 August 2026**.
- Recon compares sheet `last_balance` to Odoo receivable/payable as at that lock date (AP sign flipped so it matches the workbook). Zero-zero partners are omitted from the on-screen table but are included in the 186-section count.
- Scripts: `data/imports/run_aug31_cutover.py` (wipe + import + lock), `data/imports/run_lock_excel_closes.py` (lock only), `data/imports/verify_aug31_live.py` (September + Astromile check).

---

*End of report. Figures are from the live database after import on 7 September 2026 and from the two August 2026 Excel workbooks.*
