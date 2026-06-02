from odoo import api, fields, models, _
from odoo.exceptions import UserError


class PetroleumDealPayment(models.TransientModel):
    _name = 'petroleum.deal.payment'
    _description = 'Register Deal Payment'

    deal_id = fields.Many2one('petroleum.deal', required=True)
    company_id = fields.Many2one(related='deal_id.company_id')
    currency_id = fields.Many2one(related='deal_id.currency_id')
    partner_id = fields.Many2one(related='deal_id.partner_id')
    amount = fields.Monetary(required=True)
    payment_date = fields.Date(default=fields.Date.context_today, required=True)
    journal_id = fields.Many2one(
        'account.journal', string='Bank', required=True,
        domain="[('type', 'in', ('bank', 'cash')), ('company_id', '=', company_id)]")
    memo = fields.Char(string='Reference')

    def action_confirm(self):
        self.ensure_one()
        if self.amount <= 0:
            raise UserError(_('Amount must be positive.'))
        payment = self.env['account.payment'].create({
            'payment_type': 'inbound',
            'partner_type': 'customer',
            'partner_id': self.partner_id.id,
            'amount': self.amount,
            'date': self.payment_date,
            'journal_id': self.journal_id.id,
            'memo': self.memo or self.deal_id.name,
        })
        payment.action_post()
        self.deal_id.payment_ids = [(4, payment.id)]
        return {'type': 'ir.actions.act_window_close'}
