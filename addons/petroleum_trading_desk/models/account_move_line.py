from odoo import api, models

_SKIP_INVOICE_LINE_DISPLAY = ('line_section', 'line_subsection', 'line_note')


class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    @api.depends(
        'quantity', 'price_unit', 'petro_buy_price', 'product_id', 'display_type',
        'sale_line_ids.petro_margin',
        'move_id.deal_id', 'move_id.deal_id.line_ids.margin',
        'move_id.deal_id.line_ids.product_id',
    )
    def _compute_petro_margin(self):
        for line in self:
            if line.display_type in _SKIP_INVOICE_LINE_DISPLAY or not line.product_id:
                line.petro_margin = 0
                continue
            margin = sum(line.sale_line_ids.mapped('petro_margin'))
            if not margin and line.petro_buy_price:
                margin = (line.price_unit - line.petro_buy_price) * line.quantity
            if not margin and line.move_id.deal_id:
                deal_lines = line.move_id.deal_id.line_ids.filtered(
                    lambda dl, prod=line.product_id: dl.product_id == prod)
                margin = sum(deal_lines.mapped('margin'))
            line.petro_margin = margin
