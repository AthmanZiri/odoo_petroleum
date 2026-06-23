from odoo import models


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    def _create_purchase_orders(self):
        if self.env.context.get('petro_skip_back_to_back_po'):
            return True
        return super()._create_purchase_orders()
