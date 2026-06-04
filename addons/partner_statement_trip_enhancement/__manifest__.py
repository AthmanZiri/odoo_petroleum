{
    'name': 'Partner Statement Trip Enhancement',
    'version': '19.0.1.0.9',
    'category': 'Accounting',
    'summary': 'Fuel-aware partner statements: truck, product, debit/credit, landscape',
    'description': """
        Extends partner statements for petroleum trading:
        - Truck, product, volume and rate from trips, deals, or imported invoices
        - Separate Debit and Credit columns (replaces signed Agreed Amount)
        - Landscape PDF layout
    """,
    'author': 'Yunus Abdulaziz',
    'depends': [
        'partner_statement',
        'sale_order_trip_management',
    ],
    'data': [
        'data/report_paperformat.xml',
        'data/report_actions.xml',
        'views/statement_table_columns.xml',
        'views/statement_layout.xml',
        'views/detailed_activity_statement.xml',
        'views/activity_statement.xml',
        'views/outstanding_statement.xml',
        'views/statement_header.xml',
    ],
    'assets': {
        'web.report_assets_common': [
            (
                'partner_statement_trip_enhancement/static/src/scss/'
                'statement_landscape.scss'
            ),
        ],
        'web.report_assets_pdf': [
            (
                'partner_statement_trip_enhancement/static/src/scss/'
                'statement_landscape.scss'
            ),
        ],
    },
    'installable': True,
    'auto_install': False,
    'application': False,
}
