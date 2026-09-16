# Bank Reconciliation Manual — Jameel Petroleum Limited

**Database:** `production_0910`  
**Audience:** Accountants reconciling bank statements in Odoo  
**Last verified against DB:** 15 Sep 2026  

This manual is the desk procedure: take a bank PDF/CSV, get every line into Odoo, match it to the books, and prove the GL equals the statement closing balance.

---

## 1. Purpose

Bank reconciliation proves that:

**Statement closing balance = GL bank account balance (after all matches and adjustments)**

You are not “making numbers equal.” You are:

1. Importing what the bank says happened  
2. Booking anything missing in Odoo (receipts, payments, transfers, fees)  
3. Matching statement lines to existing journal items  
4. Investigating and documenting anything that still does not match  

Until that proof is done and signed, the period is not closed for that bank.

---

## 2. What you need before starting

| Item | Where / notes |
|------|----------------|
| Bank PDF (or online statement) for the period | Source of truth for dates, amounts, closing balance |
| Prepared CSV for import | `date,payment_ref,partner,amount` — signed amounts: **+** in, **−** out |
| Cover sheet with opening/closing and line counts | Sign-off control; do not post until accountant signs |
| Access to Odoo company **Jameel Petroleum Limited** | DB `production_0910` |
| Accounting user rights | Bank journals, payments, reconciliation |
| Prior period reconciling items list | Outstanding unmatched items carried forward |

### One-time system check (ask IT if missing)

On `production_0910` as of verification:

- **Installed:** Accounting kit (`base_accounting_kit`), Trading Desk  
- **Not installed:** `bank_reconciliation` (enhanced Auto-reconcile / Suggest Partner / toolbar)  

**Recommended:** Apps → install/upgrade **Bank Reconciliation**. Without it you can still import and match via the Accounting Dashboard bank cards; with it you get the menus and tools described in §6.

Also confirm these **manual reconciliation models** exist (they do on this DB):

- **Bank Fees** — label contains `Bank Fees`  
- **Internal Transfers**  

---

## 3. Bank map (`production_0910`)

Use the correct journal. Wrong journal = wrong GL account = false reconciliation.

| Bank | Account no. (statements) | Odoo journal code | Journal name | GL account code |
|------|--------------------------|-------------------|--------------|-----------------|
| Absa Bank Kenya | 2045130536 | **ABSA** | ABSA Bank | BNKABSA |
| Equity Bank | 0460282055255 | **EQTY** | Equity Bank | BNKEQTY |
| KCB Bank | 1312387386 | **KCB** | KCB Bank | BNKKCB |
| Premier Bank Kenya | 0018867601 | **PREM** | Premier Bank | BNKPREM |
| Gulf African Bank | 0900441501 | **GULF** | Gulf African Bank | BNKGULF |
| M-Pesa | — | **MPSA** | M-Pesa | BNKMPSA |

Also present (use only if intentionally in scope):

| Code | Name | GL |
|------|------|-----|
| BNK1 | Bank | 120001 |
| BNK2 | Bank- ABSA Bank Acc.2 | BNKABSA.2 |
| BNKU | Bank - Unspecified | BNKBNKU |

**Do not confuse Gulf African Bank (GULF / 0900441501) with KCB.**

---

## 4. End-to-end sequence (one bank at a time)

Work **one journal per session**. Finish ABSA before starting KCB, etc.

```
PDF / bank download
    → Cover sheet (opening, closing, line count)
    → Clean CSV (import columns only)
    → Import into the matching bank journal
    → Book missing cash movements in Odoo
    → Match statement lines (Bank Reconciliation)
    → Clear exceptions / To Review
    → Prove: GL balance = statement closing
    → Sign cover sheet and file evidence
```

---

## 5. Step-by-step procedure

### Step A — Prepare the statement pack

1. Open the bank PDF. Write on the cover sheet (or use the team cover CSV):  
   - Bank name and account number  
   - Period (from / to)  
   - Opening balance  
   - Closing balance  
   - Number of transactions  
   - Target Odoo journal code (ABSA, KCB, …)  
2. Recheck opening → running balance → closing. If the PDF header does not math (seen on Premier and Gulf), reconstruct from the ledger lines and **note the reconstruction on the cover sheet**.  
3. Build the import CSV. Minimum columns:

   ```text
   date,payment_ref,partner,amount
   ```

   - `date` = transaction date (`YYYY-MM-DD` preferred)  
   - `payment_ref` = bank narration / reference (keep bank ref numbers)  
   - `partner` = customer/supplier name if known; leave blank if unknown  
   - `amount` = signed; money in positive, money out negative  

4. **Stop conditions before import**  
   - Line already exists for same journal / date / amount / ref → skip (duplicate)  
   - Unknown large RTGS / unclear beneficiary → leave on an exception list; do **not** invent a partner  
   - Full multi-week KCB file while cut-over is incomplete → import the agreed slice only (e.g. Aug 31-only) until prior payments are reconciled  

5. Accountant signs the cover sheet **before** anyone posts matching journals for unclear lines. Import of the statement itself may proceed once the CSV is approved; posting of guesswork partners must not.

### Step B — Import into Odoo

1. Open **Accounting** dashboard.  
2. Find the bank card for the journal (e.g. **ABSA Bank**).  
3. Use **Import statement** / import wizard on that journal.  
4. Upload a clean CSV (`date,payment_ref,partner,amount` only).  
   - Download template: **Accounting → Accounting → Bank CSV Template**, or **Download template** on the Import wizard.  
   - Optional Absa draft: **Accounting → Accounting → Bank PDF → CSV**, then review the file before import.  
5. Confirm the notification: **Created** / **Skipped duplicates**.  
6. Spot-check 3–5 lines against the PDF (date, amount, narration).  

If validation fails, the **whole file is rejected** (bad date, empty payment_ref, missing amount, or working-sheet headers without `payment_ref`). Fix the CSV and re-import — duplicates already in Odoo are skipped safely.

If import fails on encoding: use UTF-8 and the 4-column contract above.

### Step C — Book what is missing in the books (before or during matching)

Statement lines sit in suspense until matched. If Odoo has no payment/invoice residual to match, create the books first:

| What the bank line is | What to do in Odoo |
|----------------------|--------------------|
| Customer receipt not yet registered | **Trading Desk → Register Payments** (or payment on the invoice) for the correct bank journal |
| Supplier payment not yet registered | Pay supplier bill / register payment on **PREM / ABSA / …** as appropriate |
| Move between our own banks | **Trading Desk → Inter-Bank Transfer** (From bank → To bank, amount, date, memo) |
| Bank fee / excise / levy | Match with model **Bank Fees**, or Manual Operations → expense account |
| Internal float / same-bank internal | Model **Internal Transfers** or Inter-Bank Transfer — do not call it a customer receipt |
| Unidentified inflow/outflow | Exception list → investigate with operations; do **not** force a wrong partner |

Always use the **same journal** as the statement bank.

### Step D — Reconcile (match) statement lines

1. From the bank card, open reconciliation (**N to reconcile** / Bank Reconciliation).  
   - With **Bank Reconciliation** installed: also **Accounting → Accounting → Bank Reconciliation** (defaults to unmatched).  
2. Filter to the journal you are working.  
3. For each unmatched line, in order of ease:

   **D1. Exact match to existing entry**  
   - Open the line.  
   - Under **Match Existing Entries**, select the open payment / journal item with the same amount (and preferably same partner/ref).  
   - Click **Validate**.  

   **D2. Suggest / set partner** (if module installed)  
   - **Suggest Partner** if blank.  
   - Confirm partner before validating.  

   **D3. Auto-reconcile** (if module installed)  
   - Try **Auto-reconcile** on clear fee/ref matches.  
   - Review anything it leaves unmatched; do not assume auto is always correct.  

   **D4. Reconciliation models**  
   - **Bank Fees** for fee/excise lines.  
   - **Internal Transfers** for true internal moves.  

   **D5. Manual Operations**  
   - Set a proper **Account** (not suspense) for the remainder (fee expense, clearing, etc.).  
   - **Validate**.  

   **D6. Reset**  
   - If you matched wrong: **Reset**, then rematch. Never leave a known wrong match.  

4. Dashboard **To Review** / **Invalid Statements** (when available): clear these before sign-off.

### Step E — Prove the reconciliation

For each bank, after all lines for the period are matched (or explicitly listed as outstanding):

1. Note **statement closing balance** from the PDF/cover sheet.  
2. Open the GL for that bank account (e.g. **BNKABSA**) as of the statement end date (**Accounting → Reporting → Bank Book** / General Ledger).  
3. Compute:

   ```text
   Statement closing
   − Outstanding deposits in transit (in books, not yet on statement)   [if any]
   + Outstanding withdrawals (on statement? adjust per your worksheet)
   ± Timing items documented on the recon worksheet
   = Book (GL) balance
   ```

   Practical Odoo rule for this stack: after every statement line is validated and all missing books entries are posted, **GL balance for that bank account must equal the statement closing balance** for that date. Any difference must be listed as a named reconciling item or fixed.

4. Difference ≠ 0 → go back to unmatched lines, duplicate imports, wrong journal, or unposted fees. **Do not post a balancing “plug” to hide the difference.**

### Step F — File and sign off

1. Attach: PDF, final CSV, cover sheet, list of exceptions (cleared or open).  
2. Accountant signs cover sheet.  
3. Mark period done for that journal. Move to the next bank.

---

## 6. Menus cheat sheet (Odoo)

| Task | Menu / place |
|------|----------------|
| Import statement | Accounting dashboard → bank journal → Import |
| Match bank lines | Bank card → reconcile / **Accounting → Accounting → Bank Reconciliation** |
| Register customer/supplier cash | **Trading Desk → Register Payments** |
| Move cash between banks | **Trading Desk → Inter-Bank Transfer** |
| Partner ledger clean-up (not bank) | **Accounting → Closing → Reconcile / Auto-Reconcile** |
| Payment tolerance | **Accounting → Configuration → Settings → Bank Reconciliation** (when module installed) |

**False friends — do not use these for bank recon:**

- Trading Desk **Auto-Offset Invoices & Payments** = partner FIFO offset, not bank matching  
- Partner **Send Statements** = customer/vendor SoA PDFs  

---

## 7. Common differences and how to handle them

| Situation | Likely cause | Action |
|-----------|--------------|--------|
| Bank fee / excise on statement, nothing in books | Expected | Model **Bank Fees** or Manual Ops → bank charges expense |
| Customer paid, no invoice payment in Odoo | Missing receipt | Register Payment, then match |
| Payment in Odoo, not yet on statement | Timing | Leave as outstanding book item until next statement |
| Statement line, no books entry | Timing or omission | Investigate; book if real; exception if unknown |
| Same amount twice | Duplicate import or bank reverse | Skip duplicate; match reversal carefully |
| Interbank ABSA → PREM etc. | Own transfer | Inter-Bank Transfer + match both sides over time |
| “JAMEEL VITALAC …” large outflows | Related entity / other books | Confirm with operations; do not treat as random supplier |
| Cheque / vague narration inflow | Identity unknown | Exception list; trace from remittance advice |
| Amount off by cents | Tolerance / rounding | Use configured payment tolerance only if approved; else investigate |
| Wrong bank journal | User error | Reset, reverse/repost on correct journal |

---

## 8. Worked example (Absa — cover sheet figures)

**Source pack example (Aug/Sep 2026 statements folder):**

| Field | Value |
|-------|------:|
| Bank | Absa 2045130536 |
| Odoo journal | ABSA |
| Opening | 7,030,219.95 |
| Closing | 9,153,439.65 |
| Lines (PDF) | 40 |

**Accountant walk-through:**

1. Confirm cover sheet math and journal **ABSA** / GL **BNKABSA**.  
2. Import approved Absa CSV into **ABSA**.  
3. Sort unmatched lines:  
   - Fees (`ABSA FEE`, `EXCISE DUTY…`) → **Bank Fees** / Manual Ops → Validate  
   - Clear customer names (e.g. PETRONET, REEM) → Register Payment if missing → Match Existing Entries → Validate  
   - Large `JAMEEL VITALAC` / interbank-looking lines → confirm nature → Inter-Bank Transfer or correct partner → Match  
   - Vague `CHEQUE` / numeric-only narrations → exception list  
4. When unmatched count for the period is 0 (except documented carry-forwards), check GL **BNKABSA** vs closing **9,153,439.65**.  
5. Sign cover sheet; file PDF + CSV + exception log.

Repeat the same pattern for EQTY, KCB (agreed date slice), PREM, GULF, MPSA.

---

## 9. Daily / period checklist

**Before import**

- [ ] Correct bank PDF and account number  
- [ ] Opening / closing / line count on cover sheet  
- [ ] CSV columns and signed amounts checked  
- [ ] Duplicates and stop-conditions reviewed  
- [ ] Accountant sign-off for unclear lines  

**In Odoo**

- [ ] Imported into correct journal (ABSA / KCB / EQTY / PREM / GULF / MPSA)  
- [ ] Spot-check vs PDF  
- [ ] Missing receipts/payments posted  
- [ ] Interbank transfers posted where needed  
- [ ] Fees booked via model or Manual Operations  
- [ ] All period lines Validated or listed as outstanding  
- [ ] To Review / Invalid Statements cleared  

**Sign-off**

- [ ] GL bank balance = statement closing (or worksheet explains the difference)  
- [ ] Exception list owned (who investigates, by when)  
- [ ] Cover sheet signed and pack filed  

---

## 10. Bank reconciliation worksheet (one page)

Copy per bank per period:

```text
Company: Jameel Petroleum Limited          Period: ____________
Bank / account: _________________________  Journal: ____________

A. Statement closing balance                         ____________
B. Deposits in transit (in books, not on statement)  + __________
C. Outstanding payments (on books, not on statement) − __________
D. Other reconciling items (list below)              ± __________
E. Adjusted statement balance (A+B−C±D)              ____________

F. GL balance (bank account) at period end           ____________

Difference (E − F) — must be 0                       ____________

Outstanding / exception items:
1. ____________________________________________________________
2. ____________________________________________________________

Prepared by: _____________  Date: _______
Reviewed by: _____________  Date: _______
```

---

## 11. Current DB notes (`production_0910`)

Snapshot at manual verification (useful context, not a substitute for reconciling):

- Company: **Jameel Petroleum Limited**  
- Bank statement lines imported: **none yet** — procedure starts at first import  
- Posted payments already exist on ABSA, EQTY, KCB, PREM, MPSA (match targets once statements are imported)  
- Open AR/AP residuals exist (~320 lines) — clear via payments/closing reconcile as needed; that is **partner** reconciliation, separate from bank matching  
- Install **Bank Reconciliation** before heavy matching if Auto-reconcile / Suggest Partner / unified menu are required  

---

## 12. Golden rules

1. **One bank, one journal, one period** at a time.  
2. **Bank PDF wins** on what cleared the bank; books win on what we intended — differences must be explained, not forced.  
3. **Never invent a partner** for an unknown RTGS or vague cheque.  
4. **Never plug** a suspense or misc account just to zero a difference.  
5. **Fees and transfers** are first-class transactions — book them, do not ignore them.  
6. **Sign the cover sheet** only when GL = statement (or the worksheet fully explains the gap).  
