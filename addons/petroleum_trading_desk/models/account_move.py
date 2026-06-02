from odoo import fields, models


class AccountMove(models.Model):
    _inherit = 'account.move'

    deal_id = fields.Many2one(
        'petroleum.deal', string='Trading Deal', index=True, copy=False, ondelete='set null',
        help='Links this imported ledger invoice or bill to the matching Trading Desk deal.')
