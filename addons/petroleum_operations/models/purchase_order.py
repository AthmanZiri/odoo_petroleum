from odoo import fields, models


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    depot_id = fields.Many2one('petroleum.depot', string='Loading Depot')
    epra_no = fields.Char(string='EPRA No.')
    compartment_plan = fields.Char(
        string='Compartment Plan',
        help='Tanker compartment split for loading, e.g. "2:3:2:3".')

    def button_approve(self, force=False):
        res = super().button_approve(force=force)
        orders = self.filtered(lambda order: order.state == 'purchase')
        orders._auto_validate_receipt()
        orders._auto_create_vendor_bill()
        return res

    def _should_auto_validate_receipt(self):
        """Hook for other modules to skip auto-receipt on confirm."""
        self.ensure_one()
        return True

    def _should_auto_create_vendor_bill(self):
        """Hook for other modules to skip auto-billing on confirm."""
        self.ensure_one()
        return True

    def _auto_validate_receipt(self):
        """Receive the full ordered quantity on the incoming picking."""
        for order in self:
            if not order._should_auto_validate_receipt():
                continue
            pickings = order.picking_ids.filtered(
                lambda picking: picking.state not in ('done', 'cancel'))
            if not pickings:
                continue
            for move in pickings.move_ids.filtered(
                    lambda move: move.state not in ('done', 'cancel')):
                if move.product_uom.is_zero(move.quantity) and not move.product_uom.is_zero(
                        move.product_uom_qty):
                    move.quantity = move.product_uom_qty
            # skip_backorder avoids the backorder wizard when demand is fully done.
            pickings.with_context(skip_backorder=True, skip_sms=True).button_validate()

    def _auto_create_vendor_bill(self):
        """Create a draft vendor bill from ordered quantities after confirmation."""
        for order in self:
            if not order._should_auto_create_vendor_bill():
                continue
            if order.invoice_ids.filtered(lambda move: move.state != 'cancel'):
                continue
            product_lines = order.order_line.filtered(
                lambda line: not line.display_type
                and not line.is_downpayment
                and line.product_qty)
            if not product_lines:
                continue
            # Ignore the returned form action so Confirm stays on the PO.
            order.with_context(auto_bill_on_confirm=True).action_create_invoice()


class PurchaseOrderLine(models.Model):
    _inherit = 'purchase.order.line'

    def _prepare_account_move_line(self, move=False):
        vals = super()._prepare_account_move_line(move=move)
        # Bill on ordered qty even if the product control policy is "received".
        if self.env.context.get('auto_bill_on_confirm') and not self.display_type:
            qty = self.product_qty - self.qty_invoiced
            if move and move.move_type == 'in_refund':
                qty = -qty
            vals['quantity'] = qty
        return vals
