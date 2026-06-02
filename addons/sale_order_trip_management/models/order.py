from odoo import models, fields, api


class SaleOrder(models.Model):
    _inherit = 'sale.order'
    
    purchase_count = fields.Integer(compute='_compute_purchase_count', string='Purchase Orders')
    
    def name_get(self):
        result = []
        for order in self:
            name = order.name
            if self.env.context.get('show_partner') and order.partner_id:
                name = f"{order.name} - {order.partner_id.name}"
            result.append((order.id, name))
        return result
    

    def _compute_purchase_count(self):
        for order in self:
            purchases = self.env['purchase.order'].search([('origin', '=', order.name)])
            order.purchase_count = len(purchases)
    

    def action_view_purchase(self):
        self.ensure_one()
        purchases = self.env['purchase.order'].search([('origin', '=', self.name)])
        action = {
            'name': 'Purchase Orders',
            'type': 'ir.actions.act_window',
            'res_model': 'purchase.order',
            'view_mode': 'list,form',
            'domain': [('id', 'in', purchases.ids)],
        }
        return action
        
    def action_confirm(self):
        res = super(SaleOrder, self).action_confirm()
        self._create_purchase_orders()
        return res
        
    def _create_purchase_orders(self):
        for order in self:
            # Check if purchase orders already exist
            existing_pos = self.env['purchase.order'].search([('origin', '=', order.name)])
            if existing_pos:
                continue
                
            suppliers = {}
            for line in order.order_line:
                if line.product_id and line.product_id.fuel_ok and line.product_id.seller_ids:
                    seller = line.product_id.seller_ids[0]
                    supplier = seller.partner_id
                    if supplier not in suppliers:
                        suppliers[supplier] = []
                    suppliers[supplier].append((line, seller))
            
            for supplier, lines in suppliers.items():
                po_vals = {
                    'partner_id': supplier.id,
                    'origin': order.name,
                    'date_order': fields.Datetime.now(),
                }
                po = self.env['purchase.order'].create(po_vals)
                
                for line, seller in lines:
                    self.env['purchase.order.line'].create({
                        'order_id': po.id,
                        'name': line.name,
                        'product_id': line.product_id.id,
                        'product_qty': line.product_uom_qty,
                        'product_uom_id': line.product_id.uom_id.id,
                        'price_unit': seller.price,
                        'date_planned': fields.Datetime.now(),
                    })
        return True