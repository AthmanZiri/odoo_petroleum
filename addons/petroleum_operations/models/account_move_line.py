from odoo import api, fields, models

_SKIP_INVOICE_LINE_DISPLAY = ('line_section', 'line_subsection', 'line_note')


class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    petro_buy_price = fields.Float(
        string='Buy Price', digits='Product Price', copy=False,
        help='Supplier cost per unit for this fuel line (from the trading deal).')
    petro_margin = fields.Monetary(
        string='Margin', compute='_compute_petro_margin', store=True,
        currency_field='currency_id')

    @api.depends(
        'quantity', 'price_unit', 'petro_buy_price', 'product_id', 'display_type',
        'sale_line_ids.petro_margin', 'move_id.move_type',
    )
    def _compute_petro_margin(self):
        for line in self:
            if line.display_type in _SKIP_INVOICE_LINE_DISPLAY:
                line.petro_margin = 0
                continue
            sale_lines = line.sale_line_ids
            sale_qty = sum(sale_lines.mapped('product_uom_qty'))
            margin = (
                sum(sale_lines.mapped('petro_margin')) / sale_qty * line.quantity
                if sale_qty else 0.0)
            if not margin and line.petro_buy_price:
                margin = (line.price_unit - line.petro_buy_price) * line.quantity
            if not margin and line.move_id.move_type == 'out_refund':
                original_lines = line.move_id.reversed_entry_id.invoice_line_ids.filtered(
                    lambda original_line:
                    original_line.product_id == line.product_id
                    and original_line.quantity)
                original_qty = sum(original_lines.mapped('quantity'))
                if original_qty:
                    margin = sum(
                        original_lines.mapped('petro_margin')
                    ) / original_qty * line.quantity
            if line.move_id.move_type == 'out_refund':
                margin = -margin
            line.petro_margin = margin
