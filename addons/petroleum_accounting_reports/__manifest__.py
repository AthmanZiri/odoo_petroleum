{
    'name': 'Petroleum Accounting Reports',
    'version': '19.0.1.0.1',
    'category': 'Accounting',
    'summary': 'Petroleum P&L: Revenue, Cost of Sales (purchases), Gross, Expenses, Net',
    'description': """
Petroleum Accounting Reports
============================
Aligns the Profit & Loss report with trading economics:

* **Revenue** = total sales (income accounts)
* **Cost of Sales** = purchases / direct cost (expense_direct_cost)
* **Gross Profit** = Revenue − Cost of Sales (system margin)
* **Expenses** = all other posted expenses
* **Net Profit** = Gross Profit − Expenses

Also reclassifies the purchase posting account (DIRECT EXPENSE / 500100)
from Operating Expense to Cost of Sales so totals add up.
""",
    'author': 'Jameel Petroleum',
    'license': 'LGPL-3',
    'depends': [
        'account_reports',
    ],
    'data': [
        'data/profit_and_loss_override.xml',
    ],
    'post_init_hook': 'post_init_hook',
    'installable': True,
    'application': False,
}
