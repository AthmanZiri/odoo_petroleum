{
    'name': 'Petroleum Stock Register',
    'version': '19.0.1.0.3',
    'category': 'Inventory/Inventory',
    'summary': 'Depot litre register beside the trading desk, without sale or purchase pickings',
    'description': """
Petroleum Stock Register
========================
Keeps a quantity copy of Daily Position for depot compliance.

Fuel sales and fuel purchases do not create pickings. The trading desk
stays the source of truth for litres, invoices, and margin.
""",
    'author': 'Jameel Petroleum',
    'license': 'LGPL-3',
    'depends': [
        'petroleum_trading_desk',
        'sale_stock',
        'purchase_stock',
        'sale_order_automation',
        'stock_account',
    ],
    'post_init_hook': 'post_init_hook',
    'data': [
        'views/res_company_views.xml',
    ],
    'installable': True,
    'application': False,
}
