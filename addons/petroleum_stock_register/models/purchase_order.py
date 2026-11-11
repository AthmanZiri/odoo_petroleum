from odoo import models


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    def _create_picking(self):
        """Fuel loads are not warehouse receipts.

        A purchase that is only fuel gets no picking. A mixed purchase still
        receives the non-fuel lines.
        """
        fuel_only = self.browse()
        rest = self.browse()
        for order in self:
            products = order.order_line.filtered(
                lambda line: not line.display_type and line.product_id
            ).mapped('product_id')
            if products and all(product.fuel_ok for product in products):
                fuel_only |= order
            else:
                rest |= order
        if rest:
            super(PurchaseOrder, rest)._create_picking()
        return True


class PurchaseOrderLine(models.Model):
    _inherit = 'purchase.order.line'

    def _create_stock_moves(self, picking):
        lines = self.filtered(lambda line: not line.product_id.fuel_ok)
        if not lines:
            return self.env['stock.move']
        return super(PurchaseOrderLine, lines)._create_stock_moves(picking)
