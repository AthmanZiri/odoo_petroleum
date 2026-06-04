{
    'name': 'Petroleum Customer Statement Mailer',
    'version': '19.0.1.0.0',
    'category': 'Accounting',
    'summary': 'Wizard to email customers their statement of account (invoices, payments, balance)',
    'description': """
Send customer statements on demand via a wizard.

* Reuses the OCA Activity Statement (invoices + payments + running balance,
  with the trip/truck/product columns from partner_statement_trip_enhancement).
* Open **Send Customer Statements** each morning, review the customer list,
  adjust the statement period if needed, and click Send.
* Also available from the Trading Desk Overview dashboard.
""",
    'author': 'Jameel Petroleum',
    'license': 'LGPL-3',
    'depends': [
        'partner_statement_trip_enhancement',
        'mail',
    ],
    'data': [
        'security/ir.model.access.csv',
        'data/mail_template.xml',
        'wizards/statement_send_views.xml',
    ],
    'post_init_hook': 'post_init_hook',
    'installable': True,
    'application': False,
}
