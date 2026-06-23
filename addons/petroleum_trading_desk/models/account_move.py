from odoo import api, fields, models

_SKIP_INVOICE_LINE_DISPLAY = ('line_section', 'line_subsection', 'line_note')


class AccountMove(models.Model):
    _inherit = 'account.move'

    deal_id = fields.Many2one(
        'petroleum.deal', string='Trading Deal', index=True, copy=False, ondelete='set null',
        help='Links this imported ledger invoice or bill to the matching Trading Desk deal.')
    petro_margin_total = fields.Monetary(
        string='Margin', compute='_compute_petro_margin_total', store=True,
        currency_field='currency_id')

    @api.depends(
        'invoice_line_ids.petro_margin',
        'invoice_line_ids.display_type',
        'invoice_line_ids.product_id',
        'invoice_line_ids.quantity',
        'invoice_line_ids.price_unit',
    )
    def _compute_petro_margin_total(self):
        for move in self:
            lines = move.invoice_line_ids.filtered(
                lambda l: l.display_type not in _SKIP_INVOICE_LINE_DISPLAY
                and l.product_id)
            move.petro_margin_total = sum(lines.mapped('petro_margin'))

    def write(self, vals):
        res = super().write(vals)
        if 'deal_id' in vals:
            self.filtered(
                lambda m: m.move_type in ('out_invoice', 'out_refund')
            )._compute_petro_margin_total()
            self.mapped('invoice_line_ids')._compute_petro_margin()
        return res
