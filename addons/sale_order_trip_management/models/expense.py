from odoo import models, fields


class HrExpense(models.Model):
    _inherit = 'hr.expense'
    
    trip_id = fields.Many2one('trip.management', string='Trip')