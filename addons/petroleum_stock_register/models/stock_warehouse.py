from odoo import fields, models


class StockWarehouse(models.Model):
    _inherit = 'stock.warehouse'

    petro_register = fields.Boolean(
        string='Petroleum Stock Register',
        copy=False,
        help='Litres copied from Daily Position. Sales and purchases do not use this warehouse.',
    )
