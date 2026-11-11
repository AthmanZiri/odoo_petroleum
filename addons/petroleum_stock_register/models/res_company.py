from odoo import fields, models


class ResCompany(models.Model):
    _inherit = 'res.company'

    petro_stock_register_mode = fields.Selection(
        [
            ('firewall', 'Firewall'),
            ('armed', 'Armed'),
            ('live', 'Live'),
        ],
        string='Stock Register',
        default='firewall',
        required=True,
        help='Firewall blocks fuel pickings. Armed tracks litres with on-hand '
             'still at zero. Live copies Daily Position into depot locations.',
    )
