from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.fields import Command


class PetroleumLoanRepayment(models.TransientModel):
    """Receive loan principal (and optional interest) against a posted loan issued."""

    _name = 'petroleum.loan.repayment'
    _description = 'Receive Loan Repayment'
    _inherit = 'petroleum.capital.mixin'

    loan_issued_id = fields.Many2one(
        'petroleum.loan.issued', string='Loan Issued', required=True,
        domain="[('state', '=', 'posted'), ('amount_outstanding', '>', 0), "
               "('company_id', '=', company_id)]")
    partner_id = fields.Many2one(
        'res.partner', string='Borrower', required=True)
    company_id = fields.Many2one(
        'res.company', required=True, default=lambda self: self.env.company)
    currency_id = fields.Many2one(related='company_id.currency_id')
    payment_date = fields.Date(
        string='Payment Date', required=True,
        default=fields.Date.context_today)
    amount_outstanding = fields.Monetary(
        string='Outstanding', related='loan_issued_id.amount_outstanding')
    amount = fields.Monetary(
        string='Principal Received', required=True,
        help='Credited to Loans Issued (reduces the receivable). '
             'Cannot exceed the outstanding principal.')
    interest_amount = fields.Monetary(
        string='Interest Received',
        help='Optional. Credited to interest income; does not reduce principal.')
    interest_account_id = fields.Many2one(
        'account.account', string='Interest Income Account',
        domain="[('account_type', 'in', ('income', 'income_other')), "
               "('company_ids', 'in', company_id)]")
    bank_journal_id = fields.Many2one(
        'account.journal', string='Receive In', required=True,
        domain="[('type', 'in', ('bank', 'cash')), ('company_id', '=', company_id)]")
    memo = fields.Char(string='Reference')
    move_id = fields.Many2one('account.move', readonly=True, copy=False)

    @api.onchange('loan_issued_id')
    def _onchange_loan_issued(self):
        if self.loan_issued_id:
            loan = self.loan_issued_id
            self.partner_id = loan.partner_id
            self.company_id = loan.company_id
            self.amount = loan.amount_outstanding
            if loan.bank_journal_id:
                self.bank_journal_id = loan.bank_journal_id

    @api.onchange('interest_amount', 'company_id')
    def _onchange_interest_amount(self):
        if self.interest_amount and self.interest_amount > 0 and not self.interest_account_id:
            company = self.company_id or self.env.company
            self.interest_account_id = self._ensure_loan_interest_account(company)

    def action_confirm(self):
        self.ensure_one()
        loan = self.loan_issued_id
        currency = self.currency_id
        if loan.state != 'posted':
            raise UserError(_('Post the loan opening before receiving a repayment.'))
        if currency.compare_amounts(self.amount, 0.0) <= 0:
            raise UserError(_('Principal received must be positive.'))
        if currency.compare_amounts(self.amount, loan.amount_outstanding) > 0:
            raise UserError(_(
                'Principal received (%(received)s) cannot exceed outstanding '
                '(%(outstanding)s).'
            ) % {
                'received': self.amount,
                'outstanding': loan.amount_outstanding,
            })
        interest = self.interest_amount or 0.0
        if currency.compare_amounts(interest, 0.0) < 0:
            raise UserError(_('Interest received cannot be negative.'))
        if currency.compare_amounts(interest, 0.0) > 0:
            if not self.interest_account_id:
                raise UserError(_(
                    'Set an Interest Income account when interest is received.'
                ))
            if self.interest_account_id.account_type not in ('income', 'income_other'):
                raise UserError(_(
                    'Interest must post to an Income account, not to Loans Issued.'
                ))
            if self.interest_account_id == loan.asset_account_id:
                raise UserError(_(
                    'Interest income account cannot be the Loans Issued account.'
                ))

        bank_account = self.bank_journal_id.default_account_id
        if not bank_account:
            raise UserError(_(
                'Bank journal "%s" has no default account configured.'
            ) % self.bank_journal_id.display_name)

        cash_in = currency.round(self.amount + interest)
        ref = self.memo or _('Loan repayment — %s') % self.partner_id.name
        line_name = _('Loan repayment %s') % self.partner_id.name

        # Dr Bank (principal + interest) / Cr Loans Issued (principal)
        # optional Cr Interest Income.
        line_ids = [
            Command.create({
                'name': line_name,
                'account_id': bank_account.id,
                'partner_id': self.partner_id.id,
                'debit': cash_in,
                'credit': 0.0,
            }),
            Command.create({
                'name': line_name,
                'account_id': loan.asset_account_id.id,
                'partner_id': self.partner_id.id,
                'debit': 0.0,
                'credit': self.amount,
            }),
        ]
        if currency.compare_amounts(interest, 0.0) > 0:
            line_ids.append(Command.create({
                'name': _('Loan interest %s') % self.partner_id.name,
                'account_id': self.interest_account_id.id,
                'partner_id': self.partner_id.id,
                'debit': 0.0,
                'credit': interest,
            }))

        move = self.env['account.move'].create({
            'move_type': 'entry',
            'journal_id': self.bank_journal_id.id,
            'date': self.payment_date,
            'ref': ref,
            'company_id': self.company_id.id,
            'line_ids': line_ids,
        })
        move.action_post()
        self.move_id = move.id
        loan._register_repayment(move, self.amount)
        return {
            'type': 'ir.actions.act_window',
            'name': _('Loan Repayment'),
            'res_model': 'account.move',
            'res_id': move.id,
            'view_mode': 'form',
            'target': 'current',
        }
