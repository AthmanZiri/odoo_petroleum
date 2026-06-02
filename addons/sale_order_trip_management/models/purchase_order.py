from odoo import models, fields, api


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'
    
    truck_id = fields.Many2one('truck.management', string='Truck')
    driver_id = fields.Many2one('res.partner', string='Driver', domain=[('is_driver', '=', True)])
    driver_name = fields.Char(string='Driver Name', compute='_compute_driver_details', store=True, readonly=True)
    driver_id_no = fields.Char(string='Driver ID', compute='_compute_driver_details', store=True, readonly=True)
    transporter_name = fields.Char(string='Transporter', readonly=True)
    trip_id = fields.Many2one('trip.management', string='Trip', readonly=True)
    available_truck_ids = fields.Many2many('truck.management', compute='_compute_available_trucks')
    
    @api.depends('driver_id', 'driver_id.name', 'driver_id.id_no')
    def _compute_driver_details(self):
        """Compute driver name and ID from driver_id"""
        for record in self:
            if record.driver_id:
                record.driver_name = record.driver_id.name
                record.driver_id_no = record.driver_id.id_no
            else:
                record.driver_name = False
                record.driver_id_no = False
    
    @api.depends()
    def _compute_available_trucks(self):
        for record in self:
            active_trips = self.env['trip.management'].search([('state', 'in', ['confirmed', 'in_progress'])])
            assigned_truck_ids = active_trips.mapped('truck_id').ids
            available_trucks = self.env['truck.management'].search([('id', 'not in', assigned_truck_ids)])
            record.available_truck_ids = available_trucks
    
    @api.onchange('truck_id')
    def _onchange_truck_id(self):
        """Auto-populate driver and transporter from truck"""
        if self.truck_id:
            # Auto-populate driver from truck
            self.driver_id = self.truck_id.driver_id if self.truck_id.driver_id else False
            self.transporter_name = self.truck_id.company_id.name if self.truck_id.company_id else False
        else:
            self.driver_id = False
            self.transporter_name = False
        
        # Return domain for available trucks
        active_trips = self.env['trip.management'].search([('state', 'in', ['confirmed', 'in_progress'])])
        assigned_truck_ids = active_trips.mapped('truck_id').ids
        return {
            'domain': {
                'truck_id': [('id', 'not in', assigned_truck_ids)]
            }
        }
    
    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        return records
    
    def write(self, vals):
        result = super().write(vals)
        # If driver changed, update related vendor bills
        if 'driver_id' in vals or 'driver_name' in vals or 'driver_id_no' in vals:
            for record in self:
                record._update_related_bills()
        return result
    
    def _update_related_bills(self):
        """Update driver information on related vendor bills"""
        self.ensure_one()
        # Find related vendor bills
        bills = self.env['account.move'].search([
            ('purchase_id', '=', self.id),
            ('move_type', '=', 'in_invoice')
        ])
        for bill in bills:
            bill.write({
                'driver_id': self.driver_id.id if self.driver_id else False,
                'driver_name': self.driver_name,
                'driver_id_no': self.driver_id_no,
            })
    
    def action_create_trip(self):
        if not self.truck_id:
            return
        
        sale_order = self.env['sale.order'].search([('name', '=', self.origin)], limit=1)
        
        trip = self.env['trip.management'].create({
            'purchase_order_id': self.id,
            'truck_id': self.truck_id.id,

            'date': fields.Date.today(),
        })
        
        if sale_order:
            self.env['trip.sale'].create({
                'trip_id': trip.id,
                'sale_order_id': sale_order.id,
            })
        
        self.trip_id = trip.id
        
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'trip.management',
            'res_id': trip.id,
            'view_mode': 'form',
            'target': 'current',
        }
    
