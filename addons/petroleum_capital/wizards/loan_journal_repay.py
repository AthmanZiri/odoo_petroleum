from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.fields import Command


class PetroleumLoanJournalRepay(models.TransientModel):
    """Allocate a posted journal credit on Loans Issued to the loan register."""

    _name = 'petroleum.loan.journal.repay'
    _description = 'Allocate Journal Loan Repayment'
    _inherit = 'petroleum.capital.mixin'

    move_id = fields.Many2one(
        'account.move', string='Journal Entry', required=True,
        domain="[('move_type', '=', 'entry'), ('state', '=', 'posted'), "
               "('company_id', '=', company_id)]")
    loan_issued_id = fields.Many2one(
        'petroleum.loan.issued', string='Prefer This Loan',
        domain="[('state', '=', 'posted'), ('amount_outstanding', '>', 0), "
               "('company_id', '=', company_id)]")
    partner_id = fields.Many2one(
        'res.partner', string='Borrower', required=True)
    company_id = fields.Many2one(
        'res.company', required=True, default=lambda self: self.env.company)
    currency_id = fields.Many2one(related='company_id.currency_id')
    amount = fields.Monetary(
        string='Principal to Allocate', required=True,
        help='Credit on Loans Issued that is not yet on the loan register.')
    allocation_ids = fields.One2many(
        'petroleum.loan.journal.repay.line', 'wizard_id',
        string='Allocation')

    @api.onchange('move_id')
    def _onchange_move_id(self):
        move = self.move_id
        if not move:
            return
        self.company_id = move.company_id
        leftover = move._petroleum_unallocated_repay_amount()
        if leftover:
            self.amount = leftover
        credit_lines = move._petroleum_loan_repay_lines()
        partner = credit_lines.mapped('partner_id')[:1]
        if partner:
            self.partner_id = partner
        self._apply_fifo()

    @api.onchange('partner_id', 'amount', 'loan_issued_id', 'company_id')
    def _onchange_fifo(self):
        if self.partner_id and self.amount:
            self._apply_fifo()

    def _apply_fifo(self):
        self.ensure_one()
        if not self.partner_id:
            self.allocation_ids = [Command.clear()]
            return
        company = self.company_id or self.env.company
        loans = self.env['petroleum.loan.issued']._search_outstanding_fifo(
            self.partner_id, company)
        if self.loan_issued_id and self.loan_issued_id in loans:
            loans = self.loan_issued_id | (loans - self.loan_issued_id)
        currency = company.currency_id
        remaining = self.amount or 0.0
        cmds = [Command.clear()]
        for loan in loans:
            take = 0.0
            outstanding = loan.amount_outstanding
            if currency:
                if currency.compare_amounts(remaining, 0.0) > 0:
                    take = (
                        outstanding
                        if currency.compare_amounts(remaining, outstanding) >= 0
                        else remaining
                    )
                    take = currency.round(take)
                    remaining = currency.round(remaining - take)
            else:
                take = min(remaining, outstanding) if remaining > 0 else 0.0
                remaining -= take
            if take:
                cmds.append(Command.create({
                    'loan_issued_id': loan.id,
                    'amount_allocated': take,
                    'amount_outstanding': outstanding,
                }))
        self.allocation_ids = cmds

    def action_confirm(self):
        self.ensure_one()
        move = self.move_id
        currency = self.currency_id
        if move.state != 'posted' or move.move_type != 'entry':
            raise UserError(_('Allocate only posted journal entries.'))
        leftover = move._petroleum_unallocated_repay_amount()
        if currency.compare_amounts(self.amount or 0.0, 0.0) <= 0:
            raise UserError(_('Principal to allocate must be positive.'))
        if currency.compare_amounts(self.amount, leftover) > 0:
            raise UserError(_(
                'Principal to allocate (%(amount)s) cannot exceed the unallocated '
                'credit on Loans Issued (%(leftover)s).'
            ) % {'amount': self.amount, 'leftover': leftover})
        lines = self.allocation_ids.filtered(
            lambda l: currency.compare_amounts(l.amount_allocated or 0.0, 0.0) > 0
        )
        if not lines:
            raise UserError(_('Allocate principal to at least one loan.'))
        allocated = sum(lines.mapped('amount_allocated'))
        if currency.compare_amounts(allocated, self.amount) != 0:
            raise UserError(_(
                'Allocated principal (%(allocated)s) must equal the amount '
                'to allocate (%(amount)s).'
            ) % {'allocated': allocated, 'amount': self.amount})
        for line in lines:
            loan = line.loan_issued_id
            if loan.partner_id != self.partner_id:
                raise UserError(_(
                    'Loan %s does not belong to this borrower.'
                ) % loan.display_name)
            if loan.state != 'posted':
                raise UserError(_(
                    'Loan %s is not posted.'
                ) % loan.display_name)
            if currency.compare_amounts(
                    line.amount_allocated, loan.amount_outstanding) > 0:
                raise UserError(_(
                    'Allocation for %(loan)s (%(allocated)s) cannot exceed '
                    'outstanding (%(outstanding)s).'
                ) % {
                    'loan': loan.display_name,
                    'allocated': line.amount_allocated,
                    'outstanding': loan.amount_outstanding,
                })
            loan._register_repayment(move, line.amount_allocated)
        return {
            'type': 'ir.actions.act_window',
            'name': _('Journal Entry'),
            'res_model': 'account.move',
            'res_id': move.id,
            'view_mode': 'form',
            'target': 'current',
        }


class PetroleumLoanJournalRepayLine(models.TransientModel):
    _name = 'petroleum.loan.journal.repay.line'
    _description = 'Journal Loan Repayment Allocation Line'

    wizard_id = fields.Many2one(
        'petroleum.loan.journal.repay', required=True, ondelete='cascade')
    loan_issued_id = fields.Many2one(
        'petroleum.loan.issued', string='Loan', required=True)
    amount_outstanding = fields.Monetary(string='Outstanding')
    amount_allocated = fields.Monetary(string='Allocate')
    currency_id = fields.Many2one(related='wizard_id.currency_id')
