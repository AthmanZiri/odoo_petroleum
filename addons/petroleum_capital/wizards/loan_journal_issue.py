from odoo import _, api, fields, models
from odoo.exceptions import UserError


_LOAN_CONTRA_TYPES = ('asset_cash', 'equity', 'equity_unaffected')


class PetroleumLoanJournalIssue(models.TransientModel):
    """Register a posted double-entry as a loan issued (no second posting)."""

    _name = 'petroleum.loan.journal.issue'
    _description = 'Register Loan Issued from Journal Entry'
    _inherit = 'petroleum.capital.mixin'

    move_id = fields.Many2one(
        'account.move', string='Journal Entry', required=True,
        domain="[('move_type', '=', 'entry'), ('state', '=', 'posted'), "
               "('company_id', '=', company_id)]")
    loan_issued_id = fields.Many2one(
        'petroleum.loan.issued', string='Existing Draft Loan',
        domain="[('state', '=', 'draft'), ('company_id', '=', company_id)]")
    partner_id = fields.Many2one(
        'res.partner', string='Borrower', required=True)
    company_id = fields.Many2one(
        'res.company', required=True, default=lambda self: self.env.company)
    currency_id = fields.Many2one(related='company_id.currency_id')
    amount = fields.Monetary(string='Loan Amount', required=True)
    asset_account_id = fields.Many2one(
        'account.account', string='Loans Issued Account', required=True,
        domain="[('account_type', '=', 'asset_current'), "
               "('company_ids', 'in', company_id)]")
    note = fields.Text()

    @api.onchange('move_id')
    def _onchange_move_id(self):
        move = self.move_id
        if not move:
            return
        self.company_id = move.company_id
        debit_lines = move._petroleum_loan_issue_lines()
        if debit_lines:
            self.amount = sum(debit_lines.mapped('debit'))
            self.asset_account_id = debit_lines[0].account_id
            partner = debit_lines.mapped('partner_id')[:1]
            if partner:
                self.partner_id = partner
        elif not self.asset_account_id:
            self.asset_account_id = self._ensure_loans_issued_account(
                move.company_id)

    def _validate_move(self):
        self.ensure_one()
        move = self.move_id
        if move.state != 'posted' or move.move_type != 'entry':
            raise UserError(_(
                'Post a balanced journal entry first. '
                'A loan issue must debit Loans Issued and credit Bank '
                '(or Opening Balance Equity). A single-sided entry cannot be posted.'
            ))
        if len(move.line_ids) < 2:
            raise UserError(_(
                'A loan issue must debit Loans Issued and credit Bank '
                '(or Opening Balance Equity). A single-sided entry cannot be posted.'
            ))
        existing = self.env['petroleum.loan.issued'].search([
            ('opening_move_id', '=', move.id),
        ], limit=1)
        if existing:
            raise UserError(_(
                'Journal entry %s is already the opening of %s.'
            ) % (move.display_name, existing.display_name))
        debit_lines = move.line_ids.filtered(
            lambda l: l.account_id == self.asset_account_id and l.debit > 0)
        if not debit_lines:
            raise UserError(_(
                'Entry %s does not debit Loans Issued account "%s".'
            ) % (move.display_name, self.asset_account_id.display_name))
        currency = self.currency_id
        debit_total = sum(debit_lines.mapped('debit'))
        if currency and currency.compare_amounts(self.amount, debit_total) != 0:
            raise UserError(_(
                'Loan amount (%(amount)s) must equal the debit on Loans Issued '
                '(%(debit)s).'
            ) % {'amount': self.amount, 'debit': debit_total})
        has_contra = move.line_ids.filtered(
            lambda l: l.credit > 0
            and l.account_id.account_type in _LOAN_CONTRA_TYPES
        )
        if not has_contra:
            raise UserError(_(
                'A loan issue must debit Loans Issued and credit Bank '
                '(or Opening Balance Equity). A single-sided entry cannot be posted.'
            ))
        if (self.amount or 0.0) <= 0:
            raise UserError(_('Loan amount must be positive.'))

    def action_confirm(self):
        self.ensure_one()
        self._validate_move()
        move = self.move_id
        bank_journal = False
        if move.journal_id.type in ('bank', 'cash'):
            bank_journal = move.journal_id
        else:
            cash_line = move.line_ids.filtered(
                lambda l: l.credit > 0 and l.account_id.account_type == 'asset_cash'
            )[:1]
            if cash_line:
                bank_journal = self.env['account.journal'].search([
                    ('default_account_id', '=', cash_line.account_id.id),
                    ('company_id', '=', move.company_id.id),
                ], limit=1)

        capital_journal = move.journal_id if move.journal_id.type == 'general' else (
            self._ensure_capital_journal(move.company_id)
        )
        note = self.note or _('Registered from journal entry %s') % move.name
        vals = {
            'partner_id': self.partner_id.id,
            'company_id': self.company_id.id,
            'date': move.date,
            'amount': self.amount,
            'asset_account_id': self.asset_account_id.id,
            'bank_journal_id': bank_journal.id if bank_journal else False,
            'capital_journal_id': capital_journal.id,
            'opening_move_id': move.id,
            'state': 'posted',
            'note': note,
        }
        if self.loan_issued_id:
            if self.loan_issued_id.state == 'posted':
                raise UserError(_(
                    'Loan %s is already posted.'
                ) % self.loan_issued_id.display_name)
            self.loan_issued_id.write(vals)
            loan = self.loan_issued_id
        else:
            loan = self.env['petroleum.loan.issued'].create(vals)
        return {
            'type': 'ir.actions.act_window',
            'name': _('Loan Issued'),
            'res_model': 'petroleum.loan.issued',
            'res_id': loan.id,
            'view_mode': 'form',
            'target': 'current',
        }
