from odoo import models, fields, api


class TripSale(models.Model):
    _name = 'trip.sale'
    _description = 'Trip Sale Order Relation'
    
    trip_id = fields.Many2one('trip.management', string='Trip', required=True, ondelete='cascade')
    sale_order_id = fields.Many2one('sale.order', string='Sale Order', required=True, ondelete='cascade')
    customer_name = fields.Char(related='sale_order_id.partner_id.name', string='Customer', readonly=True)
    tag_ids = fields.Many2many(related='sale_order_id.tag_ids', string='Tags', readonly=True)
    amount_total = fields.Monetary(related='sale_order_id.amount_total', string='Total Amount', readonly=True)
    currency_id = fields.Many2one(related='sale_order_id.currency_id', readonly=True)
    order_line_ids = fields.One2many(related='sale_order_id.order_line', string='Order Lines', readonly=True)
    total_qty = fields.Float(string='Total Qty', compute='_compute_total_qty')
    
    @api.depends('sale_order_id.order_line.product_uom_qty')
    def _compute_total_qty(self):
        for record in self:
            total = sum(line.product_uom_qty for line in record.sale_order_id.order_line if line.product_id and line.product_id.fuel_ok)
            record.total_qty = total