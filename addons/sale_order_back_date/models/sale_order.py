from odoo import models, fields

class SaleOrder(models.Model):
    _inherit = 'sale.order'

    allow_backdate = fields.Boolean('Allow Backdate', groups='sale_order_back_date.group_sale_order_back_date')

    def action_confirm(self):
        backdated_orders = {}
        for order in self:
            if order.allow_backdate and order.date_order:
                backdated_orders[order.id] = order.date_order
        result = super().action_confirm()
        for order_id, date_order in backdated_orders.items():
            self.browse(order_id).write({'date_order': date_order})
        return result

    def fields_get(self, allfields=None, attributes=None):
        res = super().fields_get(allfields, attributes)
        if 'date_order' in res:
            res['date_order']['readonly'] = not self.env.user.has_group('sale_order_back_date.group_sale_order_back_date')
        return res