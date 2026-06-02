{
    'name': 'Partner Statement Trip Enhancement',
    'version': '19.0.1.0.0',
    'category': 'Accounting',
    'summary': 'Adds trip-related fields to partner statements',
    'description': """
        This module extends the partner_statement module to include:
        - Trip Reference
        - Truck Number
        - Product Names
        - Quantity
        - Unit Price
    """,
    'author': 'Yunus Abdulaziz',
    'depends': ['partner_statement'],
    'data': [
        'views/activity_statement.xml',
        'views/outstanding_statement.xml',
        'views/detailed_activity_statement.xml',
    ],
    'installable': True,
    'auto_install': False,
    'application': False,
}