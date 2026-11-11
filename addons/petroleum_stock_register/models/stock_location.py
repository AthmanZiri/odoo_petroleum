from odoo import fields, models


class StockLocation(models.Model):
    _inherit = 'stock.location'

    petro_register = fields.Boolean(string='Petroleum Stock Register', copy=False)
    petro_depot_id = fields.Many2one(
        'petroleum.depot', string='Depot', copy=False, index=True, ondelete='set null',
    )
    petro_no_depot = fields.Boolean(string='No Depot Bucket', copy=False)

    def _petro_is_register(self):
        self.ensure_one()
        warehouse = self.warehouse_id
        return bool(self.petro_register or (warehouse and warehouse.petro_register))
