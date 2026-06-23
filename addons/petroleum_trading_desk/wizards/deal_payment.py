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

    def _payment_memo(self):
        self.ensure_one()
        bank = self.journal_id.name or ''
        for suffix in (' Bank', ' bank', ' BANK'):
            if bank.endswith(suffix):
                bank = bank[: -len(suffix)].strip()
                break
        base = self.memo or self.deal_id.name
        return _('Payment - %s - %s') % (bank or self.journal_id.display_name, base)

    def action_confirm(self):
        self.ensure_one()
        if self.amount <= 0:
            raise UserError(_('Amount must be positive.'))
        method_line = self.journal_id._get_available_payment_method_lines('inbound')[:1]
        if not method_line:
            raise UserError(_('No payment method configured on %s.') % self.journal_id.display_name)
        payment = self.env['account.payment'].create({
            'payment_type': 'inbound',
            'partner_type': 'customer',
            'partner_id': self.partner_id.id,
            'amount': self.amount,
            'date': self.payment_date,
            'journal_id': self.journal_id.id,
            'memo': self._payment_memo(),
            'payment_method_line_id': method_line.id,
        })
        payment.action_post()
        self.deal_id.payment_ids = [(4, payment.id)]
        return {'type': 'ir.actions.act_window_close'}
