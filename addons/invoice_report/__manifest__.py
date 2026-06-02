{
    'name': 'Invoice and Bill Analysis',
    'version': '19.0.1.0.0',
    'category': 'Accounting',
    'summary': 'Analysis of invoices and bills per partner, product, qty and rate',
    'depends': ['account'],
    'author': 'Yunus Abdulaziz',
    'data': [
        'security/ir.model.access.csv',
        'views/invoice_analysis_views.xml',
        'views/menu_views.xml',
    ],
    'installable': True,
    'auto_install': False,
    'license': 'LGPL-3',
}