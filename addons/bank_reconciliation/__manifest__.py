# -*- coding: utf-8 -*-
{
    'name': 'Bank Reconciliation',
    'version': '19.0.1.2.0',
    'category': 'Accounting/Accounting',
    'summary': 'Bank recon + Closing reconcile wizards (FX, EPD, models, UX)',
    'description': """
Bank Reconciliation — Phase A/B
===============================
* Hardened auto-match (partner / payment ref / amount / subset sums)
* Partner auto-retrieve + Suggest Partner
* Closing → Reconcile and Auto-Reconcile wizards
* FX / EPD / payment tolerance
* Dashboard To Review + Invalid Statements
* OWL toolbar: search entries, summary, quick create
* Reconciliation model buttons
""",
    'author': 'Jameel Petroleum',
    'license': 'LGPL-3',
    'depends': [
        'account',
        'base_accounting_kit',
    ],
    'data': [
        'security/ir.model.access.csv',
        'data/bank_reconciliation_data.xml',
        'wizards/reconcile_wizards_views.xml',
        'views/account_journal_dashboard_views.xml',
        'views/account_bank_statement_line_views.xml',
        'views/bank_reconciliation_menus.xml',
        'views/res_config_settings_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'bank_reconciliation/static/src/components/bank_rec_model_buttons/bank_rec_model_buttons.js',
            'bank_reconciliation/static/src/components/bank_rec_model_buttons/bank_rec_model_buttons.xml',
            'bank_reconciliation/static/src/components/bank_rec_toolbar/bank_rec_toolbar.js',
            'bank_reconciliation/static/src/components/bank_rec_toolbar/bank_rec_toolbar.xml',
        ],
    },
    'installable': True,
    'application': False,
    'auto_install': False,
}
