from odoo import fields, models


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    depot_id = fields.Many2one('petroleum.depot', string='Loading Depot')
    epra_no = fields.Char(string='EPRA No.')
    compartment_plan = fields.Char(
        string='Compartment Plan',
        help='Tanker compartment split for loading, e.g. "2:3:2:3".')
