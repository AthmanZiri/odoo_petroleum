from odoo import models, fields


class ProductTemplate(models.Model):
    _inherit = 'product.template'
    
    fuel_ok = fields.Boolean(string='Is Fuel', default=False)