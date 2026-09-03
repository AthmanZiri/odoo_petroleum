from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.fields import Command


_LOAN_CONTRA_TYPES = ('asset_cash', 'equity', 'equity_unaffected')


class AccountMove(models.Model):
    _inherit = 'account.move'

    petroleum_loan_opening_ids = fields.One2many(
        'petroleum.loan.issued', 'opening_move_id')
    petroleum_loan_allocation_ids = fields.One2many(
        'petroleum.loan.repayment.allocation', 'move_id')
    petroleum_loan_issue_unregistered = fields.Boolean(
        compute='_compute_petroleum_loan_flags')
    petroleum_loan_repay_unallocated = fields.Boolean(
        compute='_compute_petroleum_loan_flags')
    petroleum_loan_needs_double_entry = fields.Boolean(
        compute='_compute_petroleum_loan_flags')

    def _petroleum_loans_issued_accounts(self):
        self.ensure_one()
        company = self.company_id or self.env.company
        return self.env['petroleum.loan.issued']._loans_issued_accounts(company)

    def _petroleum_loan_issue_lines(self):
        self.ensure_one()
        accounts = self._petroleum_loans_issued_accounts()
        if not accounts:
            return self.env['account.move.line']
        return self.line_ids.filtered(
            lambda l: l.account_id in accounts and l.debit > 0)

    def _petroleum_loan_repay_lines(self):
        self.ensure_one()
        accounts = self._petroleum_loans_issued_accounts()
        if not accounts:
            return self.env['account.move.line']
        return self.line_ids.filtered(
            lambda l: l.account_id in accounts and l.credit > 0)

    def _petroleum_opening_loan(self):
        self.ensure_one()
        return self.env['petroleum.loan.issued'].search([
            ('opening_move_id', '=', self.id),
        ], limit=1)

    def _petroleum_unallocated_repay_amount(self):
        self.ensure_one()
        currency = self.company_currency_id or self.currency_id
        credited = sum(self._petroleum_loan_repay_lines().mapped('credit'))
        allocated = sum(
            self.env['petroleum.loan.repayment.allocation'].search([
                ('move_id', '=', self.id),
            ]).mapped('amount')
        )
        leftover = credited - allocated
        if currency:
            leftover = currency.round(leftover)
            if currency.compare_amounts(leftover, 0.0) <= 0:
                return 0.0
        return leftover if leftover > 0 else 0.0

    @api.depends(
        'state', 'move_type', 'line_ids.account_id',
        'line_ids.debit', 'line_ids.credit', 'line_ids.partner_id',
        'company_id',
        'petroleum_loan_opening_ids',
        'petroleum_loan_allocation_ids',
        'petroleum_loan_allocation_ids.amount',
    )
    def _compute_petroleum_loan_flags(self):
        for move in self:
            issue = False
            repay = False
            single = False
            if move.move_type == 'entry':
                debit_lines = move._petroleum_loan_issue_lines()
                credit_lines = move._petroleum_loan_repay_lines()
                has_contra = bool(move.line_ids.filtered(
                    lambda l: l.credit > 0
                    and l.account_id.account_type in _LOAN_CONTRA_TYPES
                ))
                if move.state != 'posted' and debit_lines and not has_contra:
                    single = True
                if (
                    move.state == 'posted'
                    and debit_lines
                    and has_contra
                    and not move._petroleum_opening_loan()
                ):
                    issue = True
                if (
                    move.state == 'posted'
                    and credit_lines
                    and move._petroleum_unallocated_repay_amount()
                ):
                    repay = True
            move.petroleum_loan_issue_unregistered = issue
            move.petroleum_loan_repay_unallocated = repay
            move.petroleum_loan_needs_double_entry = single

    def action_petroleum_register_loan_issue(self):
        self.ensure_one()
        if self.state != 'posted' or self.move_type != 'entry':
            raise UserError(_(
                'Post a balanced journal entry first. '
                'A loan issue must debit Loans Issued and credit Bank '
                '(or Opening Balance Equity). A single-sided entry cannot be posted.'
            ))
        debit_lines = self._petroleum_loan_issue_lines()
        if not debit_lines:
            raise UserError(_(
                'This entry does not debit a Loans Issued account.'
            ))
        if self._petroleum_opening_loan():
            raise UserError(_(
                'This entry is already the opening of %s.'
            ) % self._petroleum_opening_loan().display_name)
        has_contra = self.line_ids.filtered(
            lambda l: l.credit > 0
            and l.account_id.account_type in _LOAN_CONTRA_TYPES
        )
        if not has_contra:
            raise UserError(_(
                'A loan issue must debit Loans Issued and credit Bank '
                '(or Opening Balance Equity). A single-sided entry cannot be posted.'
            ))
        partner = debit_lines.mapped('partner_id')[:1]
        amount = sum(debit_lines.mapped('debit'))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Register Loan Issued'),
            'res_model': 'petroleum.loan.journal.issue',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_move_id': self.id,
                'default_partner_id': partner.id if partner else False,
                'default_amount': amount,
                'default_asset_account_id': debit_lines[0].account_id.id,
                'default_company_id': self.company_id.id,
            },
        }

    def action_petroleum_allocate_loan_repayment(self):
        self.ensure_one()
        if self.state != 'posted' or self.move_type != 'entry':
            raise UserError(_('Allocate only posted journal entries.'))
        leftover = self._petroleum_unallocated_repay_amount()
        if not leftover:
            raise UserError(_(
                'This entry has no unallocated credit on Loans Issued.'
            ))
        credit_lines = self._petroleum_loan_repay_lines()
        partner = credit_lines.mapped('partner_id')[:1]
        return {
            'type': 'ir.actions.act_window',
            'name': _('Allocate Loan Repayment'),
            'res_model': 'petroleum.loan.journal.repay',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_move_id': self.id,
                'default_partner_id': partner.id if partner else False,
                'default_company_id': self.company_id.id,
                'default_amount': leftover,
            },
        }

    def _petroleum_unlink_loan_links(self):
        """Clear loan register rows when the journal entry is drafted or reversed."""
        Allocation = self.env['petroleum.loan.repayment.allocation'].sudo()
        allocs = Allocation.search([('move_id', 'in', self.ids)])
        loans = allocs.mapped('loan_issued_id')
        allocs.unlink()
        for loan in loans:
            leftover = loan.repayment_move_ids & self
            if leftover:
                loan.repayment_move_ids = [Command.unlink(m.id) for m in leftover]
        openings = self.env['petroleum.loan.issued'].sudo().search([
            ('opening_move_id', 'in', self.ids),
        ])
        for loan in openings:
            if loan.repayment_allocation_ids or loan.repayment_move_ids:
                raise UserError(_(
                    'Cannot reset opening entry %s while repayments exist on loan %s.'
                ) % (loan.opening_move_id.display_name, loan.display_name))
        if openings:
            openings.write({'opening_move_id': False, 'state': 'draft'})

    def button_draft(self):
        self._petroleum_unlink_loan_links()
        return super().button_draft()

    def _reverse_moves(self, default_values_list=None, cancel=False):
        self._petroleum_unlink_loan_links()
        return super()._reverse_moves(
            default_values_list=default_values_list, cancel=cancel)
