from odoo import models


class ResCompany(models.Model):
    _inherit = 'res.company'

    def _get_accounts_by_product(self, products=None):
        """Inventory closing values every storable product. Fuel stays off that closing."""
        accounts = super()._get_accounts_by_product(products)
        return {
            product: values
            for product, values in accounts.items()
            if not product.fuel_ok
        }
