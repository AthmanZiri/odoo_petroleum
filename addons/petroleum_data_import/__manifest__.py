{
    'name': 'Petroleum Data Import',
    'version': '19.0.1.0.1',
    'category': 'Accounting',
    'summary': 'Import Jameel customer/supplier Excel ledgers: opening balances + transactions',
    'description': """
Petroleum Data Import
=====================
One-off, repeatable importer for the legacy Excel ledgers (one worksheet per
customer / supplier). For a chosen cut-over date it:

* creates / maps partners and the fuel products (PMS, AGO, IK),
* posts a single consolidated opening-balance journal entry per partner
  (receivable and/or payable) as of the day before cut-over,
* posts customer invoices, vendor bills and payments for every transaction
  dated on/after the cut-over (prices treated as tax-inclusive),
* produces a reconciliation report comparing the Odoo closing balance with the
  workbook BALANCE column for every partner.

The balance engine reproduces the workbook's own running-balance logic
(customers: +Debit-Credit, suppliers: +Credit-Debit) and handles text dates,
REFUND rows and multi-section (payable + receivable) tabs.
""",
    'author': 'Jameel Petroleum',
    'license': 'LGPL-3',
    'depends': [
        'account',
        'sale_management',
        'purchase',
        'sale_order_trip_management',
    ],
    'data': [
        'security/ir.model.access.csv',
        'data/data_import_cron.xml',
        'views/import_wizard_views.xml',
        'views/ledger_reconcile_views.xml',
    ],
    'installable': True,
    'application': False,
}
