{
    'name': 'Petroleum Customer Statement Mailer',
    'version': '19.0.1.1.0',
    'category': 'Accounting',
    'summary': 'Wizard to email customers and vendors their statement of account',
    'description': """
Send partner statements on demand via a wizard.

* Reuses the OCA Activity Statement (invoices + payments + running balance,
  with the trip/truck/product columns from partner_statement_trip_enhancement).
* Open **Customer Statements** or **Vendor Statements**, review the partner list,
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
