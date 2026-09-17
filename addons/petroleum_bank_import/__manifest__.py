# -*- coding: utf-8 -*-
{
    'name': 'Petroleum Bank Statement Import',
    'version': '19.0.1.2.0',
    'category': 'Accounting/Accounting',
    'summary': 'Duplicate-safe bank CSV import, validation, PDF→CSV for all five banks',
    'description': """
Hardens Community bank statement import for Jameel Petroleum:

* CSV import with fail-whole-file validation
* Duplicate skip by journal/date/amount/payment_ref fingerprint
* Import summary (created / skipped)
* Downloadable CSV template
* PDF/text → CSV wizard for Absa, KCB, Gulf African, Premier and Equity,
  with the bank detected from the file and every amount reconciled against
  the statement's running balance
    """,
    'author': 'Jameel Petroleum',
    'license': 'LGPL-3',
    'depends': [
        'base_accounting_kit',
        'bank_reconciliation',
    ],
    'data': [
        'security/ir.model.access.csv',
        'wizards/pdf_to_csv_views.xml',
        'views/import_bank_statement_views.xml',
        'views/bank_import_menus.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
