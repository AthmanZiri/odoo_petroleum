from odoo import models, fields, api


class Partner(models.Model):
    _inherit = 'res.partner'
    
    is_driver = fields.Boolean(string='Is Driver')
    is_owner = fields.Boolean(string='Is Transporter')
    id_no = fields.Char(string='ID Number')
    truck_ids = fields.One2many('truck.management', 'company_id', string='Trucks')
    truck_history_ids = fields.One2many('truck.history', 'driver_id', string='Truck History')