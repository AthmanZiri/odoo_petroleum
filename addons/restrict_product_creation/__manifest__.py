{
    'name': 'Restrict Product Creation',
    'version': '19.0.1.0.0',
    'category': 'Sales',
    'author': 'Yunus Abdulaziz',
    'summary': 'Restrict users from creating products',
    'depends': ['product'],
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
    ],
    'installable': True,
    'auto_install': False,
}