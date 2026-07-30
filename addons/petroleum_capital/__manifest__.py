{
    'name': 'Petroleum Capital & Loans',
    'version': '19.0.1.0.0',
    'category': 'Accounting',
    'summary': 'Investor equity openings, monthly ROI expense payments, and loans issued',
    'description': """
Petroleum Capital & Loans
=========================
Tracks investor capital and loans issued with correct chart-of-accounts mapping:

* **Investor capital** (Equity) — e.g. Zaynu KES 7,000,000 opening.
* **Monthly ROI** (Expense) — paid from bank/cash without reducing invested capital.
* **Loans issued** (Current Assets) — e.g. Muhidin KES 9,676,340.17 opening.

Opening entries post through a dedicated **Capital & Loans** journal (not
Miscellaneous Operations). ROI payments post through the selected bank/cash
journal as Dr Expense / Cr Bank.
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
        'wizards/roi_payment_views.xml',
        'views/menus.xml',
    ],
    'installable': True,
    'application': False,
}
