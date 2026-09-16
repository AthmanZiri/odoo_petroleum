# Bank statement update — operator checklist

Source PDFs: `~/Documents/Petroleum/Bank Statements/` (1 Sep 2026 downloads).  
Working files: this folder. **Do not post until an accountant signs the cover sheet.**

## Cover sheet (verified from PDF headers)

| PDF | Bank | Account | Opening | Closing | Lines | Odoo journal |
|-----|------|---------|--------:|--------:|------:|--------------|
| 1788237847633.pdf | Absa | 2045130536 | 7,030,219.95 | 9,153,439.65 | 40 | ABSA |
| Account_statementTB26090100210205.pdf | Equity | 0460282055255 | 370.17 | 755.17 | 11 | EQTY |
| accountTransactionHistory - ….pdf | KCB | 1312387386 | 115,368.29 | 2,188,492.04 | 279 | KCB |
| GetBankAccountStatementReport (58).pdf | Premier | 0018867601 | 113,975.19* | 2,000.00* | 10 | PREM |
| SOA- 0900441501-….pdf | **Gulf African** (not KCB) | 0900441501 | 717.63† | −1,488.97 DR | 13 | GULF |

\* Premier PDF summary shows 0/0 — reconstructed from ledger balances.  
† Gulf labels opening as DR; running-balance math only closes if opening is **+**717.63 — confirm before import.

## Sequence

1. Confirm journals ABSA, KCB, EQTY, PREM, GULF exist with default accounts.
2. Import **31 Aug slices only** first (skip full KCB August until matched).
3. For each CSV: Accounting dashboard → bank journal → Import statement.
4. Record missing receipts/payments (Trading Desk Register Payment), interbank transfers, fees.
5. Accounting → Bank Reconciliation → auto-match → clear exceptions.
6. Prove: GL balance = statement closing per account.

## CSV columns

`date,payment_ref,partner,amount`  
Amount is signed: positive = money in, negative = money out.

Download the template from **Accounting → Accounting → Bank CSV Template**, or the **Download template** button on the Import wizard.

**Do not import `*_working.csv` analysis sheets** (columns like `proposed_action` / `confidence`) unless they also include `payment_ref`. Prefer the clean 4-column CSV.

### Import behaviour (`petroleum_bank_import`)

- Validation **fails the whole file** if any row has a bad date, missing amount, or empty `payment_ref` (nothing is created).
- Re-importing the same journal/date/amount/`payment_ref` **skips duplicates** and reports `Created` / `Skipped duplicates`.
- Optional: **Accounting → Accounting → Bank PDF → CSV** (Absa MVP) to draft a CSV from PDF/text — always review before import.

## Stop conditions

- Same line already on `account.bank.statement.line` for that journal/date/amount/`payment_ref` → skipped automatically.
- Unknown RTGS beneficiary (Premier 786,000) → exception list, do not guess.
- Full KCB August file → do not import until Aug cut-over payments are reconciled.
- Scanned/image-only PDF → do not use PDF→CSV; prepare CSV manually.
