from odoo import _, fields, models
from odoo.exceptions import UserError
from odoo.fields import Command


class PetroleumRoiPayment(models.TransientModel):
    """Pay monthly investor ROI as an expense — never reduces equity capital."""

    _name = 'petroleum.roi.payment'
    _description = 'Pay Investor ROI'
    _inherit = 'petroleum.capital.mixin'

    investor_capital_id = fields.Many2one(
        'petroleum.investor.capital', string='Investor Capital', required=True)
    partner_id = fields.Many2one(
        'res.partner', string='Investor', required=True)
    company_id = fields.Many2one(
        'res.company', required=True, default=lambda self: self.env.company)
    currency_id = fields.Many2one(related='company_id.currency_id')
    payment_date = fields.Date(
        string='Payment Date', required=True,
        default=fields.Date.context_today)
    amount = fields.Monetary(
        string='ROI Amount', required=True,
        help='Debited to ROI Expense and credited to Bank. '
             'Does not reduce the invested capital balance.')
    expense_account_id = fields.Many2one(
        'account.account', string='ROI Expense Account', required=True,
        domain="[('account_type', 'in', ('expense', 'expense_direct_cost')), "
               "('company_ids', 'in', company_id)]")
    bank_journal_id = fields.Many2one(
        'account.journal', string='Pay From', required=True,
        domain="[('type', 'in', ('bank', 'cash')), ('company_id', '=', company_id)]")
    memo = fields.Char(string='Reference')
    move_id = fields.Many2one('account.move', readonly=True, copy=False)

    @api.onchange('investor_capital_id')
    def _onchange_investor_capital(self):
        if self.investor_capital_id:
            self.partner_id = self.investor_capital_id.partner_id
            self.company_id = self.investor_capital_id.company_id
            self.amount = self.investor_capital_id.monthly_roi_amount
            self.expense_account_id = self.investor_capital_id.roi_expense_account_id

    def action_confirm(self):
        self.ensure_one()
        if self.amount <= 0:
            raise UserError(_('ROI amount must be positive.'))
        if self.expense_account_id.account_type not in (
                'expense', 'expense_direct_cost'):
            raise UserError(_(
                'ROI must post to an Expense account so invested capital is not reduced.'
            ))
        bank_account = self.bank_journal_id.default_account_id
        if not bank_account:
            raise UserError(_(
                'Bank journal "%s" has no default account configured.'
            ) % self.bank_journal_id.display_name)

        equity_account = self.investor_capital_id.equity_account_id
        if self.expense_account_id == equity_account:
            raise UserError(_(
                'ROI expense account cannot be the investor equity account. '
                'Paying ROI must not reduce the amount invested.'
            ))

        ref = self.memo or _(
            'ROI payment — %s') % self.partner_id.name
        line_name = _('Monthly ROI %s') % self.partner_id.name

        # Dr Expense / Cr Bank — equity capital untouched.
        move = self.env['account.move'].create({
            'move_type': 'entry',
            'journal_id': self.bank_journal_id.id,
            'date': self.payment_date,
            'ref': ref,
            'company_id': self.company_id.id,
            'line_ids': [
                Command.create({
                    'name': line_name,
                    'account_id': self.expense_account_id.id,
                    'partner_id': self.partner_id.id,
                    'debit': self.amount,
                    'credit': 0.0,
                }),
                Command.create({
                    'name': line_name,
                    'account_id': bank_account.id,
                    'partner_id': self.partner_id.id,
                    'debit': 0.0,
                    'credit': self.amount,
                }),
            ],
        })
        move.action_post()
        self.move_id = move.id
        return {
            'type': 'ir.actions.act_window',
            'name': _('ROI Payment'),
            'res_model': 'account.move',
            'res_id': move.id,
            'view_mode': 'form',
            'target': 'current',
        }
