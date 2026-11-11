{
    'name': 'Petroleum Stock Register',
    'version': '19.0.1.0.5',
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
    'uninstall_hook': 'uninstall_hook',
    'data': [
        'security/ir.model.access.csv',
        'views/res_company_views.xml',
        'views/register_wizard_views.xml',
        'views/register_report_views.xml',
        'data/register_cron.xml',
    ],
    'installable': True,
    'application': False,
}
