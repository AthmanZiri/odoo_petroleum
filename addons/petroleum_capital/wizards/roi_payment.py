from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.fields import Command


class PetroleumRoiPayment(models.TransientModel):
    """Pay monthly investor ROI as an expense — never reduces equity capital."""

    _name = 'petroleum.roi.payment'
    _description = 'Pay Investor ROI'
    _inherit = 'petroleum.capital.mixin'

    investor_capital_id = fields.Many2one(
        'petroleum.investor.capital', string='Investor Capital', required=True,
        domain="[('state', '=', 'posted'), ('company_id', '=', company_id)]")
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
        domain="[('type', 'in', ('bank', 'cash')), "
               "('company_id', '=', company_id), "
               "('default_account_id', '!=', False)]")
    memo = fields.Char(string='Reference')
    move_id = fields.Many2one('account.move', readonly=True, copy=False)

    def _default_pay_from_journal(self, company):
        return self.env['account.journal'].search([
            ('type', 'in', ('bank', 'cash')),
            ('company_id', '=', company.id),
            ('default_account_id', '!=', False),
        ], limit=1)

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        company = self.env.company
        if 'bank_journal_id' in fields_list and not res.get('bank_journal_id'):
            journal = self._default_pay_from_journal(company)
            if journal:
                res['bank_journal_id'] = journal.id
        if 'investor_capital_id' in fields_list and not res.get('investor_capital_id'):
            capitals = self.env['petroleum.investor.capital'].search([
                ('state', '=', 'posted'),
                ('company_id', '=', company.id),
            ], limit=2)
            if len(capitals) == 1:
                res['investor_capital_id'] = capitals.id
                if 'partner_id' in fields_list:
                    res['partner_id'] = capitals.partner_id.id
                if 'amount' in fields_list and not res.get('amount'):
                    res['amount'] = capitals.monthly_roi_amount
                if 'expense_account_id' in fields_list and not res.get('expense_account_id'):
                    res['expense_account_id'] = capitals.roi_expense_account_id.id
                if (
                    'bank_journal_id' in fields_list
                    and capitals.bank_journal_id
                    and capitals.bank_journal_id.default_account_id
                ):
                    res['bank_journal_id'] = capitals.bank_journal_id.id
        if (
            'expense_account_id' in fields_list
            and not res.get('expense_account_id')
        ):
            res['expense_account_id'] = self._ensure_roi_expense_account(company).id
        return res

    @api.onchange('investor_capital_id')
    def _onchange_investor_capital(self):
        if self.investor_capital_id:
            capital = self.investor_capital_id
            self.partner_id = capital.partner_id
            self.company_id = capital.company_id
            self.amount = capital.monthly_roi_amount
            self.expense_account_id = capital.roi_expense_account_id
            if capital.bank_journal_id and capital.bank_journal_id.default_account_id:
                self.bank_journal_id = capital.bank_journal_id
            elif not self.bank_journal_id:
                self.bank_journal_id = self._default_pay_from_journal(
                    capital.company_id or self.env.company)

    def action_confirm(self):
        self.ensure_one()
        if not self.investor_capital_id:
            raise UserError(_(
                'Select the investor capital record to pay ROI against.'
            ))
        if self.investor_capital_id.state != 'posted':
            raise UserError(_(
                'Post the capital opening for %s before paying ROI.'
            ) % self.investor_capital_id.display_name)
        if not self.partner_id:
            raise UserError(_('Investor is required.'))
        if (self.amount or 0.0) <= 0:
            raise UserError(_(
                'ROI amount must be positive. Set Monthly ROI on the investor '
                'capital record or enter the amount to pay.'
            ))
        if not self.expense_account_id:
            raise UserError(_('Set the ROI Expense account (P&L), not equity.'))
        if self.expense_account_id.account_type not in (
                'expense', 'expense_direct_cost'):
            raise UserError(_(
                'ROI must post to an Expense account so invested capital is not reduced. '
                '"%s" is type %s.'
            ) % (
                self.expense_account_id.display_name,
                self.expense_account_id.account_type,
            ))
        if not self.bank_journal_id:
            raise UserError(_(
                'Select the bank or cash journal to pay from. '
                'A Chart of Accounts bank line is not enough — open the cash book '
                '(Bank/Cash journal) first.'
            ))
        bank_account = self.bank_journal_id.default_account_id
        if not bank_account:
            raise UserError(_(
                'Bank journal "%s" has no default account. '
                'Open Accounting → Configuration → Journals and set Default Account.'
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
