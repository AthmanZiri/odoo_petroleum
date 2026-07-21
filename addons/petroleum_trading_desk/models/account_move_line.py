from odoo import api, models

_SKIP_INVOICE_LINE_DISPLAY = ('line_section', 'line_subsection', 'line_note')


class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    @api.depends(
        'quantity', 'price_unit', 'petro_buy_price', 'product_id', 'display_type',
        'sale_line_ids.petro_margin', 'move_id.move_type',
        'move_id.petro_price_adjustment',
    )
    def _compute_petro_margin(self):
        for line in self:
            if line.display_type in _SKIP_INVOICE_LINE_DISPLAY or not line.product_id:
                line.petro_margin = 0
                continue
            move = line.move_id
            if move.petro_price_adjustment == 'customer_sell':
                # A price-only customer adjustment changes revenue, not cost.
                margin = line.price_unit * line.quantity
            else:
                sale_lines = line.sale_line_ids
                sale_qty = sum(sale_lines.mapped('product_uom_qty'))
                margin = (
                    sum(sale_lines.mapped('petro_margin')) / sale_qty * line.quantity
                    if sale_qty else 0.0)
                if not margin and line.petro_buy_price:
                    margin = (line.price_unit - line.petro_buy_price) * line.quantity
                if not margin and move.move_type == 'out_refund':
                    original = move.petro_original_move_id or move.reversed_entry_id
                    original_lines = original.invoice_line_ids.filtered(
                        lambda original_line:
                        original_line.product_id == line.product_id
                        and original_line.quantity)
                    original_qty = sum(original_lines.mapped('quantity'))
                    if original_qty:
                        margin = sum(
                            original_lines.mapped('petro_margin')
                        ) / original_qty * line.quantity
            # Odoo stores refund invoice-line quantities as positive values.
            # Show and aggregate their economic effect as a reversal.
            if move.move_type == 'out_refund':
                margin = -margin
            line.petro_margin = margin
