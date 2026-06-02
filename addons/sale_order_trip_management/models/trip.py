from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


class Trip(models.Model):
    _name = 'trip.management'
    _description = 'Trip Management'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _rec_name = 'name'
    _order = 'date desc'

    name = fields.Char(string='Trip Reference', required=True, copy=False, 
                      readonly=True, default=lambda self: _('New'))
    date = fields.Date(string='Date', default=fields.Date.context_today)
    truck_id = fields.Many2one('truck.management', string='Truck', required=True)
    purchase_order_id = fields.Many2one('purchase.order', string='Purchase Order')
    sale_order_ids = fields.One2many('trip.sale', 'trip_id', string='Sale Orders')
    total_quantity = fields.Float(string='Total Quantity', compute='_compute_total_quantity', store=True)
    expense_ids = fields.One2many('hr.expense', 'trip_id', string='Expenses')
    sale_order_expense_ids = fields.One2many('trip.sale.expense', 'trip_id', string='Sale Order Expenses')
    invoice_ids = fields.Many2many('account.move', compute='_compute_invoice_ids', string='Invoices')
    bill_ids = fields.Many2many('account.move', compute='_compute_bill_ids', string='Vendor Bills')
    invoice_status = fields.Selection([
        ('no', 'Nothing to Invoice'),
        ('to invoice', 'To Invoice'),
        ('invoiced', 'Fully Invoiced')
    ], string='Invoice Status', compute='_compute_invoice_status', store=True)
    payment_status = fields.Selection([
        ('not_paid', 'Not Paid'),
        ('in_payment', 'In Payment'),
        ('paid', 'Paid')
    ], string='Payment Status', compute='_compute_payment_status', store=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('confirmed', 'Confirmed'),
        ('in_progress', 'In Progress'),
        ('done', 'Done'),
        ('cancelled', 'Cancelled')
    ], string='Status', default='draft', tracking=True)
    notes = fields.Text(string='Notes')
    loading_plan = fields.Text(string='Loading Plan', related='truck_id.loading_plan', readonly=True)
    driver_name = fields.Char(string='Driver', related='truck_id.driver_id.name', readonly=True)
    driver_id_no = fields.Char(string='Driver ID', related='truck_id.driver_id.id_no', readonly=True)
    assigned_sale_order_ids = fields.Many2many('sale.order', compute='_compute_assigned_sale_orders')
    trip_sale_order_ids = fields.Many2many('sale.order', compute='_compute_trip_sale_orders')
    
    @api.depends('sale_order_ids.sale_order_id.order_line.product_uom_qty')
    def _compute_total_quantity(self):
        for trip in self:
            total = 0
            for sale_line in trip.sale_order_ids:
                for line in sale_line.sale_order_id.order_line:
                    if line.product_id and line.product_id.fuel_ok:
                        total += line.product_uom_qty
            trip.total_quantity = total
    
    @api.depends('sale_order_ids.sale_order_id.invoice_status')
    def _compute_invoice_status(self):
        for trip in self:
            if not trip.sale_order_ids:
                trip.invoice_status = 'no'
                continue
            
            statuses = trip.sale_order_ids.mapped('sale_order_id.invoice_status')
            if all(status == 'invoiced' for status in statuses):
                trip.invoice_status = 'invoiced'
            elif any(status in ['to invoice', 'upselling'] for status in statuses):
                trip.invoice_status = 'to invoice'
            else:
                trip.invoice_status = 'no'
    
    @api.depends('sale_order_ids.sale_order_id.invoice_ids')
    def _compute_invoice_ids(self):
        for trip in self:
            invoices = trip.sale_order_ids.mapped('sale_order_id.invoice_ids').filtered(lambda inv: inv.move_type == 'out_invoice')
            trip.invoice_ids = invoices
    
    @api.depends('purchase_order_id.invoice_ids')
    def _compute_bill_ids(self):
        for trip in self:
            bills = trip.purchase_order_id.invoice_ids.filtered(lambda bill: bill.move_type == 'in_invoice') if trip.purchase_order_id else self.env['account.move']
            trip.bill_ids = bills
    
    @api.depends('sale_order_ids.sale_order_id.invoice_ids.payment_state')
    def _compute_payment_status(self):
        for trip in self:
            if not trip.sale_order_ids:
                trip.payment_status = 'not_paid'
                continue
            
            all_invoices = trip.invoice_ids
            if not all_invoices:
                trip.payment_status = 'not_paid'
                continue
            
            payment_states = all_invoices.mapped('payment_state')
            if all(state == 'paid' for state in payment_states):
                trip.payment_status = 'paid'
            elif any(state == 'partial' for state in payment_states):
                trip.payment_status = 'in_payment'
            else:
                trip.payment_status = 'not_paid'
    
    def _compute_assigned_sale_orders(self):
        for trip in self:
            all_assigned = self.env['trip.sale'].search([('trip_id', '!=', trip.id)]).mapped('sale_order_id')
            trip.assigned_sale_order_ids = all_assigned
    
    def _compute_trip_sale_orders(self):
        for trip in self:
            trip.trip_sale_order_ids = trip.sale_order_ids.mapped('sale_order_id')
    
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('trip.management') or _('New')
        return super(Trip, self).create(vals_list)
    
    @api.onchange('truck_id')
    def _check_truck_availability(self):
        """Check if the selected truck is already allocated to another active trip"""
        if self.truck_id:
            active_trips = self.search([
                ('state', 'in', ['confirmed', 'in_progress']),
                ('truck_id', '=', self.truck_id.id),
                ('id', '!=', self._origin.id)
            ])
            if active_trips:
                return {
                    'warning': {
                        'title': 'Warning',
                        'message': f"This truck is already allocated to trip {active_trips[0].name}."
                    }
                }
    
    @api.constrains('truck_id', 'state')
    def _check_truck_not_allocated(self):
        """Prevent confirming a trip with a truck already allocated to another active trip"""
        for trip in self:
            if trip.state == 'confirmed' and trip.truck_id:
                active_trips = self.search([
                    ('state', 'in', ['confirmed', 'in_progress']),
                    ('truck_id', '=', trip.truck_id.id),
                    ('id', '!=', trip.id)
                ])
                if active_trips:
                    raise ValidationError(
                        f"Cannot confirm trip: truck {trip.truck_id.name} is already allocated to trip {active_trips[0].name}."
                    )
            
    def action_confirm(self):
        if not self.truck_id:
            raise ValidationError("Cannot confirm trip: No truck selected.")
        if self.total_quantity > self.truck_id.capacity:
            raise ValidationError(
                f"Cannot confirm trip: Total quantity ({self.total_quantity}) exceeds truck capacity ({self.truck_id.capacity})."
            )
        
        self.write({'state': 'confirmed'})
        
        # Link trip to purchase order
        if self.purchase_order_id:
            self.purchase_order_id.write({'trip_id': self.id})
        
        # Trip is linked through trip.sale relationship
        
        if self.total_quantity < self.truck_id.capacity:
            self.message_post(
                body=f"Warning: Trip confirmed with quantity ({self.total_quantity}) less than truck capacity ({self.truck_id.capacity}). Trip is not fully loaded.",
                message_type='comment'
            )
        
    def action_start(self):
        self.write({'state': 'in_progress'})
        
    def action_done(self):
        self.write({'state': 'done'})
        
    def action_cancel(self):
        self.write({'state': 'cancelled'})
        
    def action_draft(self):
        self.write({'state': 'draft'})
        
    @api.model
    def get_available_trucks(self):
        """Return trucks that are not allocated to active trips"""
        active_trips = self.search([('state', 'in', ['confirmed', 'in_progress'])])
        allocated_truck_ids = active_trips.mapped('truck_id').ids
        return self.env['truck.management'].search([('id', 'not in', allocated_truck_ids)])
        
    def action_view_available_trucks(self):
        """Open a window with only available trucks"""
        active_trips = self.search([('state', 'in', ['confirmed', 'in_progress']), ('id', '!=', self.id)])
        allocated_truck_ids = active_trips.mapped('truck_id').ids
        
        return {
            'name': 'Available Trucks',
            'type': 'ir.actions.act_window',
            'res_model': 'truck.management',
            'view_mode': 'kanban,list,form',
            'domain': [('id', 'not in', allocated_truck_ids)],
            'target': 'new',
            'context': {'create': False}
        }