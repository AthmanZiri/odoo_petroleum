from odoo import models, fields, api


class TruckHistory(models.Model):
    _name = 'truck.history'
    _description = 'Truck Driver History'
    _order = 'date_start desc'
    
    truck_id = fields.Many2one('truck.management', string='Truck', required=True, ondelete='cascade')
    driver_id = fields.Many2one('res.partner', string='Driver', required=True, domain=[('is_driver', '=', True)], ondelete='cascade')
    date_start = fields.Date(string='Start Date', default=fields.Date.today)
    date_end = fields.Date(string='End Date')
    active = fields.Boolean(default=True)
    notes = fields.Text(string='Notes')