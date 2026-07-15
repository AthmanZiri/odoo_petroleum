from odoo import fields, models


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    is_daily_position_po = fields.Boolean(
        string='Daily Position PO', default=False, index=True,
        help='Bulk purchase order created from the morning position board.')
    daily_position_date = fields.Date(string='Position Date', index=True)

    def _should_auto_validate_receipt(self):
        # Bulk position volumes change during the day; receipt later.
        self.ensure_one()
        if self.is_daily_position_po:
            return False
        return super()._should_auto_validate_receipt()

    def _should_auto_create_vendor_bill(self):
        # Bulk position POs are billed once from the Daily Position board.
        self.ensure_one()
        if self.is_daily_position_po:
            return False
        return super()._should_auto_create_vendor_bill()


class PurchaseOrderLine(models.Model):
    _inherit = 'purchase.order.line'

    petroleum_position_line_id = fields.Many2one(
        'petroleum.daily.position.line', string='Position Line', index=True, copy=False)
