from odoo import _, api, fields, models
from odoo.exceptions import UserError


class PetroleumDeskBankTransfer(models.TransientModel):
    _name = 'petroleum.desk.bank.transfer'
    _description = 'Inter-Bank Transfer'

    company_id = fields.Many2one(
        'res.company', required=True, default=lambda self: self.env.company)
    currency_id = fields.Many2one(related='company_id.currency_id')
    journal_from_id = fields.Many2one(
        'account.journal', string='From Bank / Cash', required=True,
        domain="[('type', 'in', ('bank', 'cash')), ('company_id', '=', company_id)]")
    journal_to_id = fields.Many2one(
        'account.journal', string='To Bank / Cash', required=True,
        domain="[('type', 'in', ('bank', 'cash')), ('company_id', '=', company_id)]")
    amount = fields.Monetary(required=True)
    transfer_date = fields.Date(
        string='Date', required=True, default=fields.Date.context_today)
    memo = fields.Char(string='Reference')
    move_id = fields.Many2one('account.move', readonly=True, copy=False)

    @api.constrains('journal_from_id', 'journal_to_id')
    def _check_distinct_journals(self):
        for wiz in self:
            if wiz.journal_from_id and wiz.journal_to_id:
                if wiz.journal_from_id == wiz.journal_to_id:
                    raise UserError(_('Choose two different bank or cash journals.'))

    def _journal_bank_label(self, journal):
        name = journal.name or ''
        for suffix in (' Bank', ' bank', ' BANK'):
            if name.endswith(suffix):
                return name[: -len(suffix)].strip()
        return name.strip()

    def action_confirm(self):
        self.ensure_one()
        if self.amount <= 0:
            raise UserError(_('Amount must be positive.'))
        if self.journal_from_id == self.journal_to_id:
            raise UserError(_('Choose two different bank or cash journals.'))

        src_account = self.journal_from_id.default_account_id
        dest_account = self.journal_to_id.default_account_id
        if not src_account or not dest_account:
            raise UserError(_(
                'Both journals need a default bank/cash account configured.'))

        from_label = self._journal_bank_label(self.journal_from_id)
        to_label = self._journal_bank_label(self.journal_to_id)
        ref = self.memo or _('Transfer %s → %s') % (from_label, to_label)
        line_name = _('Inter-bank transfer: %s → %s') % (from_label, to_label)

        move = self.env['account.move'].create({
            'move_type': 'entry',
            'date': self.transfer_date,
            'ref': ref,
            'journal_id': self.journal_from_id.id,
            'line_ids': [
                (0, 0, {
                    'name': line_name,
                    'account_id': dest_account.id,
                    'debit': self.amount,
                    'credit': 0.0,
                }),
                (0, 0, {
                    'name': line_name,
                    'account_id': src_account.id,
                    'debit': 0.0,
                    'credit': self.amount,
                }),
            ],
        })
        move.action_post()
        self.move_id = move.id
        return {
            'type': 'ir.actions.act_window',
            'name': _('Inter-Bank Transfer'),
            'res_model': 'account.move',
            'res_id': move.id,
            'view_mode': 'form',
            'target': 'current',
        }
