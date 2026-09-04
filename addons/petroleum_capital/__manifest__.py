{
    'name': 'Petroleum Capital & Loans',
    'version': '19.0.1.4.0',
    'category': 'Accounting',
    'summary': 'Investor equity openings, monthly ROI expense, loans issued, and loan repayments',
    'description': """
Petroleum Capital & Loans
=========================
Tracks investor capital and loans issued with correct chart-of-accounts mapping:

* **Investor capital** (Equity) — e.g. Zaynu KES 7,000,000 opening.
* **Monthly ROI** (Expense) — paid from bank/cash without reducing invested capital.
* **Loans issued** (Current Assets) — e.g. Muhidin KES 9,676,340.17 opening.
* **Loan repayment** — Dr Bank / Cr Loans Issued (optional Cr Interest Income).
  Principal reduces the receivable; it is not an expense.
  Single-loan and partner bulk (FIFO, oldest loan first) receipts.

Opening entries post through a dedicated **Capital & Loans** journal (not
Miscellaneous Operations). ROI payments and loan repayments post through the
selected bank/cash journal.
""",
    'author': 'Jameel Petroleum',
    'license': 'LGPL-3',
    'depends': [
        'account',
        'mail',
    ],
    'data': [
        'security/ir.model.access.csv',
        'data/sequence.xml',
        'views/investor_capital_views.xml',
        'views/loan_issued_views.xml',
        'views/account_move_views.xml',
        'wizards/roi_payment_views.xml',
        'wizards/loan_repayment_views.xml',
        'wizards/loan_partner_repayment_views.xml',
        'wizards/loan_journal_issue_views.xml',
        'wizards/loan_journal_repay_views.xml',
        'views/menus.xml',
    ],
    'installable': True,
    'application': False,
}
