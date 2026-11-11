from odoo import models


class StockRule(models.Model):
    _inherit = 'stock.rule'

    def _skip_procurement(self, procurement):
        product = procurement.product_id
        if product.fuel_ok:
            return True
        return super()._skip_procurement(procurement)
