from odoo import models

from odoo.addons.petroleum_trading_desk.models.loadings_import_job import IMPORT_CTX


class PetroleumLoadingsImport(models.TransientModel):
    _inherit = 'petroleum.loadings.import'

    def _prepare_fuel_products_once(self, state):
        super()._prepare_fuel_products_once(state)
        if self.env.company.petro_stock_register_mode not in ('armed', 'live'):
            return
        products = self.env['product.product'].concat(*state['product_cache'].values())
        templates = products.product_tmpl_id.filtered(
            lambda template: template.fuel_ok and not template.is_storable)
        if templates:
            templates.with_context(**IMPORT_CTX).write({'is_storable': True})
