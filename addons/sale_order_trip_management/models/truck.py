from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


class Truck(models.Model):
    _name = 'truck.management'
    _description = 'Truck Management'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _rec_name = 'name'
    
    name = fields.Char(string='Truck Number', required=True)
    company_id = fields.Many2one('res.partner', string='Transporter Company', domain=[('is_owner', '=', True)])
    driver_id = fields.Many2one('res.partner', string='Driver', domain=[('is_driver', '=', True)], tracking=True)
    capacity = fields.Float(string='Capacity (Litres)', required=True)
    loading_plan = fields.Text(string='Loading Plan')
    trip_ids = fields.One2many('trip.management', 'truck_id', string='Trips')
    driver_history_ids = fields.One2many('truck.history', 'truck_id', string='Driver History')
    active = fields.Boolean(default=True)
    notes = fields.Text(string='Notes')
    is_assigned = fields.Boolean(string='Assigned', compute='_compute_is_assigned', store=True)
    
    # Using api.constrains instead of SQL constraint to provide better error message
    
    @api.depends('trip_ids.state')
    def _compute_is_assigned(self):
        for truck in self:
            active_trips = truck.trip_ids.filtered(lambda t: t.state in ['confirmed', 'in_progress'])
            truck.is_assigned = bool(active_trips)
    
    @api.model_create_multi
    def create(self, vals_list):
        trucks = super(Truck, self).create(vals_list)
        for truck in trucks:
            if truck.driver_id:
                self.env['truck.history'].create({
                    'truck_id': truck.id,
                    'driver_id': truck.driver_id.id,
                    'date_start': fields.Date.today(),
                })
        return trucks
    
    @api.constrains('driver_id')
    def _check_driver_assignment(self):
        for truck in self:
            if truck.driver_id:
                other_truck = self.search([('driver_id', '=', truck.driver_id.id), ('id', '!=', truck.id)], limit=1)
                if other_truck:
                    raise ValidationError(_("Driver %s is already assigned to truck %s") % 
                                              (truck.driver_id.name, other_truck.name))
    
    def write(self, vals):
        if 'driver_id' in vals:
            # Close current driver assignment
            for truck in self:
                if truck.driver_id:
                    history = self.env['truck.history'].search([
                        ('truck_id', '=', truck.id),
                        ('driver_id', '=', truck.driver_id.id),
                        ('date_end', '=', False)
                    ], limit=1)
                    if history:
                        history.date_end = fields.Date.today()
            
            # Create new driver assignment if not empty
            if vals['driver_id']:
                result = super(Truck, self).write(vals)
                for truck in self:
                    self.env['truck.history'].create({
                        'truck_id': truck.id,
                        'driver_id': vals['driver_id'],
                        'date_start': fields.Date.today(),
                    })
                return result
        return super(Truck, self).write(vals)