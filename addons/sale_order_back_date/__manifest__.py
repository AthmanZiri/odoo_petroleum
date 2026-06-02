{
    'name': 'Sale Order Back Date',
    'version': '19.0.1.0.0',
    'category': 'Sales',
    'author': 'Yunus Abdulaziz',
    'summary': 'Allow users to back date sale orders with proper access rights',
    'depends': ['sale'],
    'data': [
        'security/security.xml',
        'views/sale_order_views.xml',
    ],
    'installable': True,
    'auto_install': False,
}