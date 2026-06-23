{
    'name': 'Petroleum Trading Desk',
    'version': '19.0.1.0.18',
    'category': 'Sales',
    'summary': 'Single-screen trading desk: one Deal per truck load drives sale, purchase, trip, invoice and payment',
    'description': """
Petroleum Trading Desk
======================
A single place for the trader to run the whole buy-and-sell flow.

* **Deal** document = one truck loading (mirrors a row in the old Excel ledger).
  Enter client, product(s), sell & buy price, supplier, depot, truck, driver,
  EPRA and compartment plan once.
* One click orchestrates everything behind the scenes: the back-to-back
  sale order + purchase order, the trip / loading instruction, the customer
  invoice + vendor bill, and the customer payment to the right bank.
* **Daily Prices** board to capture each morning's supplier buy prices and your
  sell prices; deals default their prices from it.
* **Daily Position** board for the morning bulk buy: record litres purchased,
  roll unsold volume forward, sync one purchase order per supplier per day,
  and allocate litres to deals as they load.
* A **Trading Desk** kanban pipeline (Quotation -> Proforma -> Confirmed ->
  Loaded -> Settled) as the home screen.
""",
    'author': 'Jameel Petroleum',
    'license': 'LGPL-3',
    'depends': [
        'petroleum_operations',
        'petroleum_data_import',
        'petroleum_statement_mailer',
        'account',
    ],
    'data': [
        'security/ir.model.access.csv',
        'data/sequence.xml',
        'data/loadings_import_cron.xml',
        'data/deal_server_actions.xml',
        'views/daily_price_views.xml',
        'views/daily_position_views.xml',
        'views/deal_views.xml',
        'views/dashboard_views.xml',
        'views/ledger_partner_alias_views.xml',
        'wizards/deal_payment_views.xml',
        'wizards/desk_bulk_payment_views.xml',
        'wizards/desk_bank_transfer_views.xml',
        'wizards/loadings_import_views.xml',
        'wizards/deal_ledger_link_views.xml',
        'views/account_move_views.xml',
        'views/partner_views.xml',
        'reports/proforma_report.xml',
        'views/menus.xml',
    ],
    'assets': {
        'web.assets_backend': [
            ('include', 'web.chartjs_lib'),
            'petroleum_trading_desk/static/src/dashboard/dashboard.xml',
            'petroleum_trading_desk/static/src/dashboard/dashboard.scss',
            'petroleum_trading_desk/static/src/dashboard/dashboard.js',
            'petroleum_trading_desk/static/src/dashboard/dashboard_action.js',
        ],
    },
    'installable': True,
    'application': True,
}
