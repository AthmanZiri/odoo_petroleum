# Bank Reconciliation

Community bank reconciliation for the petroleum stack (LGPL-3).

Extends the Cybrosys kit with real matching and Phase A/B accountant workflows.

## Install / upgrade

1. Update Apps list → **Upgrade Bank Reconciliation** (`19.0.1.2.0`)
2. Hard-refresh the browser (OWL assets)

## Menus

| Menu | Purpose |
|------|---------|
| **Accounting → Accounting → Bank Reconciliation** | Bank statement matching |
| **Accounting → Accounting → Closing → Reconcile** | Open AR/AP journal items |
| **Accounting → Accounting → Closing → Auto-Reconcile** | Perfect Match / Clear Account |
| Journal items list → **Action → Reconcile** | Manual AML reconcile + optional write-off |

## Bank matching tools

On a statement line:

* **Search entries** — find / select open journal items
* **Suggest partner** — from IBAN / partner name / history
* **Quick create** — add a bank transaction
* **Auto-reconcile** — run hardened rules on this line
* Reconciliation **model buttons**
* **Validate** / **Reset**

Dashboard bank cards: **N to reconcile**, **To Review**, gear **Invalid Statements**.

## Settings

**Accounting → Configuration → Settings → Bank Reconciliation → Payment Tolerance**

## Phase coverage

| Phase A | Status |
|---------|--------|
| Harden auto-match (ref / amount / partner / sums) | Done |
| Closing Reconcile + Auto-Reconcile | Done |
| FX / EPD / tolerance | Done (prior + kept) |

| Phase B | Status |
|---------|--------|
| OWL toolbar (search / summary / quick create) | Done |
| Dashboard To Review / invalid statements | Done |
| Partner auto-retrieve | Done |
| Full Enterprise OWL kanban rewrite | Deferred (Phase C) |

## False friends

* Trading Desk **Reconcile Imported Ledgers** = partner ledger FIFO, not bank recon
* Partner **Send Statements** = SoA PDFs
