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
        'sale_line_ids.petro_margin',
    )
    def _compute_petro_margin(self):
        for line in self:
            if line.display_type in _SKIP_INVOICE_LINE_DISPLAY:
                line.petro_margin = 0
                continue
            margin = sum(line.sale_line_ids.mapped('petro_margin'))
            if not margin and line.petro_buy_price:
                margin = (line.price_unit - line.petro_buy_price) * line.quantity
            line.petro_margin = margin
