from odoo import models


class PetroleumDeal(models.Model):
    _inherit = 'petroleum.deal'

    def _prepare_products(self):
        """Keep ordered-quantity invoicing. Track litres only once the register is armed."""
        super()._prepare_products()
        if self.env.company.petro_stock_register_mode not in ('armed', 'live'):
            return
        templates = self.line_ids.mapped('product_id').product_tmpl_id.filtered(
            lambda template: template.fuel_ok and not template.is_storable)
        if templates:
            templates.write({'is_storable': True})
