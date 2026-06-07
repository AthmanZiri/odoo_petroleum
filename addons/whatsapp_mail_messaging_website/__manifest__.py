# -*- coding: utf-8 -*-
{
    'name': 'Odoo Whatsapp Connector Website',
    'version': '19.0.1.0.0',
    'category': 'Website',
    'summary': 'Website chat widget for Odoo Whatsapp Connector',
    'description': """Optional website integration for Odoo Whatsapp Connector.
Adds website footer WhatsApp chat, website mobile number configuration, and
website message templates.""",
    'author': 'Cybrosys Techno Solutions',
    'company': 'Cybrosys Techno Solutions',
    'maintainer': 'Cybrosys Techno Solutions',
    'website': 'https://www.cybrosys.com',
    'depends': ['whatsapp_mail_messaging', 'website'],
    'data': [
        'security/ir.model.access.csv',
        'views/website_templates.xml',
        'views/website_views.xml',
        'views/selection_message_views.xml',
    ],
    'assets': {
        'web.assets_frontend': [
            "whatsapp_mail_messaging_website/static/src/css/whatsapp_icon_website.css",
            "whatsapp_mail_messaging_website/static/src/js/whatsapp_web_icon.js",
            "whatsapp_mail_messaging_website/static/src/js/whatsapp_modal.js",
        ],
    },
    'license': 'LGPL-3',
    'installable': True,
    'auto_install': False,
    'application': False,
}
