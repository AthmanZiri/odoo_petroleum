# Jameel Petroleum Limited

**Management report: purchase orders vs supplier bills, and loan repayments**

| | |
|---|---|
| Date | 14 August 2026 |
| Prepared for | Directors, Finance, and Trading |
| Based on | Production copy taken 14 August 2026, 04:49 (books posted through 13 August) |

---

## 1. One-page summary

Two things were checked on the live system.

**Purchase orders vs supplier bills.** In August, Purchase showed **25 orders totalling KES 282,076,500**. Vendor bills for August showed **25 bills totalling KES 198,611,500**. The gap of about **KES 83.5 million** is not missing cash. Staff were adding two different lists: orders by the day they were placed, bills by bill date. Most of the gap is fuel still sitting on bulk orders waiting to be billed as loads go out. A large Vitalac order (P00159) is on the order list, but its replacement bill is still a draft with no bill date, so it does not appear in the August bill list. Price-change notes no longer pretend that litres were returned. Two Vitalac bills had extra litres linked to the order so they cannot be billed twice — but those extra litres are currently priced at **zero shillings** on the bill and must be corrected to what the supplier charged.

**Loans given out.** Eleven posted loans to **Muhidin**, totalling **KES 14,660,340.17**, are on the books. **Nothing has been received back yet.** The system can now record a repayment into bank or cash, reduce what is still owed, and treat optional interest as income. The loan principal must not be booked as a company expense or mixed with monthly investor ROI.

**What you need to do:** post or close P00159; put the correct price on the extra litres on P00152 and P00155; stop comparing the two list totals; do not raise new June supplier bills for the same fuel already in the June import; use **Receive Repayment** when Muhidin pays.

---

## 2. Purchase orders vs supplier bills

### What people saw

On the live books as at this copy:

- **Purchase** (order date in August, confirmed orders): **25 orders, KES 282,076,500**
- **Vendor bills** (bill date in August, posted or draft): **25 bills, KES 198,611,500**
- **Difference:** **KES 83,465,000**

Earlier in August the same two screens showed 17 orders vs 17 bills. The count matching was a coincidence then, and it is a coincidence again now. New orders P00164 to P00171 (11–12 August) are on both sides; they are not the problem.

### Why the totals are not supposed to match

**Wrong comparison.** Purchase adds by *order date*. Bills add by *bill date*. A cancelled bill drops off the bill list. A price-increase note (small extra charge from the supplier) sits on the bill list even though it is not a copy of the whole order. A draft bill with no bill date does not appear when you filter “August”.

**Bulk buys billed as loads go out.** Each purchase order is a morning bulk buy. The supplier bill is often only the litres already loaded. The rest stays on the order as still to bill. That is normal trading, not a system error.

As at this copy, August remaining stock still to bill is **KES 45,821,000** on five orders:

| Order | Supplier | Still to bill (KES) |
|---|---|---|
| P00163 | Vitalac | 21,028,000 |
| P00153 | Vitalac | 14,630,000 |
| P00171 | Vitalac | 5,985,000 |
| P00161 | Oil Hub | 3,980,000 |
| P00156 | Pinoil | 198,000 |

### What had gone wrong (and is now fixed)

**Cancelled Vitalac bill not replaced (P00159, KES 33,701,000).** The only bill was cancelled. A **draft replacement** now exists (origin P00159, same amount). It has **no bill number and no bill date**, so it does not show in the August bills list. The purchase order already looks fully billed because a draft counts. Finance must open that draft, set the bill date, check the lines, and **post** it — or cancel the order if this load will not be billed.

**Extra litres typed onto the bill (P00152 and P00155).** Remaining litres had been added as extra lines instead of against the order. The supplier was billed, but the order still looked open (risk of billing twice). Those litres are now linked to the order, so the order no longer shows them as open.

**Please check the prices.** On the live bills those extra litres are at **KES 0**:

- P00152 (BILL/2026/08/0006): 6,000 L petrol and 4,000 L diesel at zero — about **KES 1,980,000** missing versus the order if they should have been at KES 198.
- P00155 (BILL/2026/08/0010): 10,000 L diesel at zero — about **KES 2,000,000** missing versus the order if they should have been at KES 200. (This line previously also had no VAT.)

The double-bill trap is gone. The **amount on the bill** still needs to match what the supplier charged. Put the correct unit price (and VAT if it applies) back on those lines, or raise a small extra bill if the posted bill should not be edited.

**Supplier price-change notes treated as quantity returns.** A credit for “the price went down by a shilling” was reducing billed litres. P00107 no longer shows a large negative billed quantity. P00125 is fully billed again. Price-change notes now appear on the related purchase order (including the small Vitalac increase BILL/2026/08/0009, KES 27,000 on P00153).

**June history — do not bill again.** There are still **64 June purchase orders, KES 659,354,500**, that look unbilled. Those orders are the same **3,291,000 litres** as the **295 imported June supplier bills (KES 636,937,000)**. The fuel is already in the books. Raising new June bills would **double** purchase cost. Optionally mark those June orders as billed against the import so Purchases → To Invoice stops showing a false backlog. Do not create new vendor bills for them.

### How the August gap adds up (this copy)

| What | KES |
|---|---|
| Remaining stock on five August orders | 45,821,000 |
| P00159 on the order list; replacement bill has no August bill date | 33,701,000 |
| Extra litres on P00152 now at zero on the bill | 1,980,000 |
| Extra litres on P00155 now at zero on the bill | 2,000,000 |
| Less: P00148 bill KES 10,000 above the order (197.00 → 197.50) | (10,000) |
| Less: supplier price-increase note BILL/2026/08/0009 | (27,000) |
| **Equals the list-view gap** | **83,465,000** |

Nothing in that gap is money missing from the bank. It is timing, remaining stock, one unposted replacement bill, and two bills whose extra litres need their real prices put back.

---

## 3. Loan repayments

### The challenge

Jameel records **loans given out** as money the company is owed (an asset), not as a cost. There are **11 posted loans**, all to **Muhidin**:

| Loan | Date | Amount (KES) | Outstanding (KES) |
|---|---|---|---|
| LOAN/0001 | 30 June 2026 | 9,676,340.17 | 9,676,340.17 |
| LOAN/0009 | 1 July 2026 | 367,000.00 | 367,000.00 |
| LOAN/0002 | 4 July 2026 | 200,000.00 | 200,000.00 |
| LOAN/0005 | 4 July 2026 | 57,000.00 | 57,000.00 |
| LOAN/0010 | 7 July 2026 | 103,000.00 | 103,000.00 |
| LOAN/0008 | 8 July 2026 | 600,000.00 | 600,000.00 |
| LOAN/0004 | 13 July 2026 | 150,000.00 | 150,000.00 |
| LOAN/0006 | 31 July 2026 | 595,000.00 | 595,000.00 |
| LOAN/0007 | 3 August 2026 | 312,000.00 | 312,000.00 |
| LOAN/0011 | 4 August 2026 | 600,000.00 | 600,000.00 |
| LOAN/0012 | 11 August 2026 | 2,000,000.00 | 2,000,000.00 |
| **Total** | | **14,660,340.17** | **14,660,340.17** |

**Repaid: KES 0.** No repayment entries have been recorded yet. The tool is live; collections have not been entered.

If a repayment were booked like a bill, a cost, or monthly investor ROI, the **principal** (the loan itself) would look like a company **expense**. It is not an expense. It is the borrower paying back what they owe. Monthly **investor ROI** (for example on investor capital) *is* an expense and must stay separate. Loan principal coming back must not reduce invested capital.

### What you can do now

On a **posted** loan, use **Receive Repayment**:

1. Open **Capital & Loans → Loans Issued**.
2. Open the loan (e.g. Muhidin LOAN/0001).
3. Click **Receive Repayment**.
4. Choose the **bank or cash** account the money landed in.
5. Enter **principal received** (cannot be more than outstanding).
6. If they paid interest, enter **interest received**. Interest is **income**. It does not reduce the loan balance.
7. Confirm. Outstanding should fall. Use **Repayments** on the loan if you need the accounting entry.

You cannot receive repayment on a draft (unposted) loan, and you cannot receive more principal than is still outstanding. Money in the bank goes up; the amount still owed goes down. Principal does **not** appear in expenses.

---

## 4. Actions still waiting on people

| Priority | Who | Action |
|---|---|---|
| 1 | Finance | Open the **draft P00159** replacement bill, set the bill date, check the lines, and **post** it — or cancel the purchase order if Vitalac will not bill this load. |
| 2 | Finance | On **BILL/2026/08/0006** (P00152) and **BILL/2026/08/0010** (P00155), put the **correct unit price** (and VAT if due) on the extra litres that are currently at zero, so the bill matches the supplier. |
| 3 | Finance / Trading | Do **not** compare Purchase list total vs Bills list total. Open the purchase order and check billed vs remaining. |
| 4 | Trading | Bill remaining August stock (the five orders above) **against the order lines** as loads go out. Do not add free-text extra lines at a new price. Use the supplier price-change action for price increases or decreases. |
| 5 | Finance | Do **not** raise new vendor bills for the 64 June bulk orders. Those litres are already in the imported June bills. |
| 6 | Finance | When Muhidin pays, record it with **Receive Repayment**. Do not book principal as an expense or as monthly ROI. |

---

## 5. How to check next month

**Purchase orders**

1. Open the purchase order (not the list grand total).
2. Check billed litres vs remaining litres on that order.
3. Open the bills from that order, including any small price-change note.
4. Remaining stock on a bulk buy is expected until those litres are loaded and billed.

**Loans**

1. Open the loan.
2. Read **Outstanding** and **Repaid**.
3. Do not look for loan principal on the profit-and-loss expense list. If interest was received, that interest is income.

---

## 6. How this was checked

The live production copy of 14 August 2026, 04:49 was restored to a separate local database (not overwriting production). Posted documents run through **13 August 2026**. The purchase-order billing behaviour and the loan repayment screens are present on that copy. Figures in this report are from that copy, not from earlier backups or from the August Excel loading-sheet file.
