{
    'name': "Kenya eTIMS Integration",
    'summary': """
            Kenya eTIMS / OSCU EDI integration with UNSPSC product codes
        """,
    'description': """
       This module integrates with the Kenyan OSCU eTIMS device.
       It includes UNSPSC product codes required for eTIMS reporting.
    """,
    'author': 'Your Company',
    'category': 'Accounting/Localizations/EDI',
    'version': '1.0',
    'license': 'OEEL-1',
    'depends': ['l10n_ke', 'account'],
    'data': [
        'data/ke_etims_integration.code.csv',
        'data/ir_cron_data.xml',
        'data/uom.uom.csv',
        'views/account_tax_views.xml',
        'views/product_views.xml',
        'views/account_move_views.xml',
        'views/report_invoice.xml',
        'views/res_company_views.xml',
        'views/res_config_settings_views.xml',
        'views/res_users_views.xml',
        'views/res_partner_views.xml',
        'views/uom_uom_views.xml',
        'views/ke_etims_code_views.xml',
        'views/ke_etims_notice_views.xml',
        'views/menuitems.xml',
        'security/ir.model.access.csv',
        'wizard/account_move_reversal_view.xml',
    ],
    'demo': [
        'demo/demo_company.xml',
        'demo/demo_product.xml',
    ],
    'post_init_hook': '_post_init_hook',
}
