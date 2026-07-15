from odoo import fields, models


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    is_daily_position_po = fields.Boolean(
        string='Daily Position PO', default=False, index=True,
        help='Bulk purchase order created from the morning position board.')
    daily_position_date = fields.Date(string='Position Date', index=True)


class PurchaseOrderLine(models.Model):
    _inherit = 'purchase.order.line'

    petroleum_position_line_id = fields.Many2one(
        'petroleum.daily.position.line', string='Position Line', index=True, copy=False)
