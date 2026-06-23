{
    'name': 'Sale Order Trip Management',
    'version': '19.0.0.0.1',
    'category': 'Sales/Transportation',
    'author': 'Yunus Abdulaziz',
    'summary': 'Manage trips and fuel for sales orders',
    'description': """
        This module allows you to manage trips related to sale orders,
        tripstracking, customer management, truck management, and reporting.
    """,
    'depends': ['base', 'sale_management', 'purchase', 'crm', 'hr_expense'],
    'data': [
        'data/trip_sequence.xml',
        'security/ir.model.access.csv',
        'views/menu_views.xml',

        'views/trip_views.xml',
        'views/truck_views.xml',
        'views/truck_kanban_view.xml',
        'views/customer_views.xml',
        'views/transporter_views.xml',
        'views/order_views.xml',

        'views/truck_history_views.xml',
        'views/purchase_order_views.xml',
        'views/account_move_views.xml',
        'views/product_views.xml',

        'views/product_profitability_views.xml',
        'reports/purchase_order_report.xml',
        'reports/trip_report_views.xml',


    ],
    'demo': [],

    'installable': True,
    'application': True,
    'auto_install': False,
    'license': 'LGPL-3',
}