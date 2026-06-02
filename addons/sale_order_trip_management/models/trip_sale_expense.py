from odoo import models, fields, api


class TripSaleExpense(models.Model):
    _name = 'trip.sale.expense'
    _description = 'Trip Sale Order Expense'
    
    trip_id = fields.Many2one('trip.management', string='Trip', required=True)
    sale_order_id = fields.Many2one('sale.order', string='Sale Order', required=True)
    expense_id = fields.Many2one('hr.expense', string='Expense', required=True)
    amount = fields.Monetary(string='Amount', related='expense_id.total_amount', readonly=True)
    currency_id = fields.Many2one('res.currency', related='expense_id.currency_id', readonly=True)
    description = fields.Char(string='Description', related='expense_id.name', readonly=True)