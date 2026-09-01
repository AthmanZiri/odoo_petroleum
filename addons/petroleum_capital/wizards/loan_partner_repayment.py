from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.fields import Command


class PetroleumLoanPartnerRepayment(models.TransientModel):
    """Receive one lump principal (and optional interest) for a borrower.

    Principal is allocated FIFO across that partner's outstanding loans
    (opening date, then id). Interest is one credit and does not reduce
    outstanding.
    """

    _name = 'petroleum.loan.partner.repayment'
    _description = 'Receive Partner Loan Repayment'
    _inherit = 'petroleum.capital.mixin'

    partner_id = fields.Many2one(
        'res.partner', string='Borrower', required=True)
    company_id = fields.Many2one(
        'res.company', required=True, default=lambda self: self.env.company)
    currency_id = fields.Many2one(related='company_id.currency_id')
    payment_date = fields.Date(
        string='Payment Date', required=True,
        default=fields.Date.context_today)
    amount_outstanding_total = fields.Monetary(
        string='Total Outstanding', compute='_compute_outstanding_total')
    amount = fields.Monetary(
        string='Principal Received', required=True,
        help='Allocated oldest loan first. Cannot exceed total outstanding.')
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
    allocation_ids = fields.One2many(
        'petroleum.loan.partner.repayment.line', 'wizard_id',
        string='Allocation')
    amount_unallocated = fields.Monetary(
        string='Unallocated', compute='_compute_unallocated')
    allocation_balanced = fields.Boolean(
        compute='_compute_unallocated')
    move_id = fields.Many2one('account.move', readonly=True, copy=False)

    def _eligible_loans(self):
        self.ensure_one()
        if not self.partner_id:
            return self.env['petroleum.loan.issued']
        company = self.company_id or self.env.company
        return self.env['petroleum.loan.issued']._search_outstanding_fifo(
            self.partner_id, company)

    def _fifo_commands(self, partner, company, amount):
        loans = self.env['petroleum.loan.issued']._search_outstanding_fifo(
            partner, company)
        currency = company.currency_id
        remaining = amount or 0.0
        cmds = []
        for loan in loans:
            outstanding = loan.amount_outstanding
            take = 0.0
            if currency:
                if currency.compare_amounts(remaining, 0.0) > 0:
                    if currency.compare_amounts(remaining, outstanding) >= 0:
                        take = outstanding
                    else:
                        take = remaining
                    take = currency.round(take)
                    remaining = currency.round(remaining - take)
            else:
                take = min(remaining, outstanding) if remaining > 0 else 0.0
                remaining -= take
            cmds.append(Command.create({
                'loan_issued_id': loan.id,
                'amount_allocated': take,
            }))
        return cmds

    def _apply_fifo(self):
        self.ensure_one()
        cmds = [Command.clear()]
        if self.partner_id:
            company = self.company_id or self.env.company
            cmds += self._fifo_commands(self.partner_id, company, self.amount)
        self.allocation_ids = cmds

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        partner = self.env['res.partner'].browse(res.get('partner_id'))
        company = self.env['res.company'].browse(
            res.get('company_id') or self.env.company.id)
        if not partner:
            return res
        loans = self.env['petroleum.loan.issued']._search_outstanding_fifo(
            partner, company)
        total = sum(loans.mapped('amount_outstanding'))
        currency = company.currency_id
        if 'amount' in fields_list and not res.get('amount'):
            res['amount'] = currency.round(total) if currency else total
        if 'allocation_ids' in fields_list and not res.get('allocation_ids'):
            res['allocation_ids'] = self._fifo_commands(
                partner, company, res.get('amount') or 0.0)
        if not res.get('bank_journal_id'):
            journal = next(
                (loan.bank_journal_id for loan in loans if loan.bank_journal_id),
                False,
            )
            if journal:
                res['bank_journal_id'] = journal.id
        return res

    @api.onchange('partner_id', 'company_id')
    def _onchange_partner(self):
        loans = self._eligible_loans()
        total = sum(loans.mapped('amount_outstanding'))
        currency = self.currency_id
        self.amount = currency.round(total) if currency else total
        journal = next(
            (loan.bank_journal_id for loan in loans if loan.bank_journal_id),
            False,
        )
        if journal:
            self.bank_journal_id = journal
        self._apply_fifo()

    @api.onchange('amount')
    def _onchange_amount(self):
        self._apply_fifo()

    @api.onchange('interest_amount', 'company_id')
    def _onchange_interest_amount(self):
        if self.interest_amount and self.interest_amount > 0 and not self.interest_account_id:
            company = self.company_id or self.env.company
            self.interest_account_id = self._ensure_loan_interest_account(company)

    @api.depends('partner_id', 'company_id', 'allocation_ids.amount_outstanding')
    def _compute_outstanding_total(self):
        for wiz in self:
            if wiz.allocation_ids:
                total = sum(wiz.allocation_ids.mapped('amount_outstanding'))
            else:
                total = sum(wiz._eligible_loans().mapped('amount_outstanding'))
            currency = wiz.currency_id
            wiz.amount_outstanding_total = (
                currency.round(total) if currency else total
            )

    @api.depends('amount', 'allocation_ids.amount_allocated', 'currency_id')
    def _compute_unallocated(self):
        for wiz in self:
            currency = wiz.currency_id
            allocated = sum(wiz.allocation_ids.mapped('amount_allocated'))
            unallocated = (wiz.amount or 0.0) - allocated
            if currency:
                wiz.amount_unallocated = currency.round(unallocated)
                wiz.allocation_balanced = currency.compare_amounts(
                    unallocated, 0.0) == 0
            else:
                wiz.amount_unallocated = unallocated
                wiz.allocation_balanced = unallocated == 0.0

    def action_reset_fifo(self):
        self.ensure_one()
        self._apply_fifo()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Receive Partner Repayment'),
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
            'context': self.env.context,
        }

    def _check_interest(self, currency, loans_issued_accounts):
        self.ensure_one()
        interest = self.interest_amount or 0.0
        if currency.compare_amounts(interest, 0.0) < 0:
            raise UserError(_('Interest received cannot be negative.'))
        if currency.compare_amounts(interest, 0.0) <= 0:
            return 0.0
        if not self.interest_account_id:
            raise UserError(_(
                'Set an Interest Income account when interest is received.'
            ))
        if self.interest_account_id.account_type not in ('income', 'income_other'):
            raise UserError(_(
                'Interest must post to an Income account, not to Loans Issued.'
            ))
        if self.interest_account_id in loans_issued_accounts:
            raise UserError(_(
                'Interest income account cannot be the Loans Issued account.'
            ))
        return interest

    def action_confirm(self):
        self.ensure_one()
        currency = self.currency_id
        if currency.compare_amounts(self.amount or 0.0, 0.0) <= 0:
            raise UserError(_('Principal received must be positive.'))

        loans = self._eligible_loans()
        if not loans:
            raise UserError(_(
                'No posted outstanding loans for %s.'
            ) % self.partner_id.display_name)

        total_outstanding = sum(loans.mapped('amount_outstanding'))
        if currency.compare_amounts(self.amount, total_outstanding) > 0:
            raise UserError(_(
                'Principal received (%(received)s) cannot exceed outstanding '
                '(%(outstanding)s).'
            ) % {
                'received': self.amount,
                'outstanding': total_outstanding,
            })

        lines = self.allocation_ids.filtered(
            lambda l: currency.compare_amounts(l.amount_allocated or 0.0, 0.0) > 0
        )
        if not lines:
            raise UserError(_('Allocate principal to at least one loan.'))

        allocated = sum(lines.mapped('amount_allocated'))
        if currency.compare_amounts(allocated, self.amount) != 0:
            raise UserError(_(
                'Allocated principal (%(allocated)s) must equal the amount '
                'received (%(received)s). Reset to FIFO or adjust the lines.'
            ) % {
                'allocated': allocated,
                'received': self.amount,
            })

        for line in lines:
            loan = line.loan_issued_id
            if loan.partner_id != self.partner_id:
                raise UserError(_(
                    'Loan %s does not belong to this borrower.'
                ) % loan.display_name)
            if loan not in loans:
                raise UserError(_(
                    'Loan %s is not posted with an outstanding balance.'
                ) % loan.display_name)
            if currency.compare_amounts(
                    line.amount_allocated, line.amount_outstanding) > 0:
                raise UserError(_(
                    'Allocation for %(loan)s (%(allocated)s) cannot exceed '
                    'outstanding (%(outstanding)s).'
                ) % {
                    'loan': loan.display_name,
                    'allocated': line.amount_allocated,
                    'outstanding': line.amount_outstanding,
                })

        bank_account = self.bank_journal_id.default_account_id
        if not bank_account:
            raise UserError(_(
                'Bank journal "%s" has no default account configured.'
            ) % self.bank_journal_id.display_name)

        interest = self._check_interest(currency, loans.asset_account_id)
        cash_in = currency.round(self.amount + interest)
        ref = self.memo or _('Loan repayment — %s') % self.partner_id.name
        line_name = _('Loan repayment %s') % self.partner_id.name

        move_line_ids = [
            Command.create({
                'name': line_name,
                'account_id': bank_account.id,
                'partner_id': self.partner_id.id,
                'debit': cash_in,
                'credit': 0.0,
            }),
        ]
        for line in lines:
            loan = line.loan_issued_id
            move_line_ids.append(Command.create({
                'name': _('Loan repayment %s — %s') % (
                    self.partner_id.name, loan.name),
                'account_id': loan.asset_account_id.id,
                'partner_id': self.partner_id.id,
                'debit': 0.0,
                'credit': line.amount_allocated,
            }))
        if currency.compare_amounts(interest, 0.0) > 0:
            move_line_ids.append(Command.create({
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
            'line_ids': move_line_ids,
        })
        move.action_post()
        self.move_id = move.id
        for line in lines:
            line.loan_issued_id._register_repayment(move, line.amount_allocated)
        return {
            'type': 'ir.actions.act_window',
            'name': _('Loan Repayment'),
            'res_model': 'account.move',
            'res_id': move.id,
            'view_mode': 'form',
            'target': 'current',
        }


class PetroleumLoanPartnerRepaymentLine(models.TransientModel):
    _name = 'petroleum.loan.partner.repayment.line'
    _description = 'Partner Loan Repayment Allocation Line'

    wizard_id = fields.Many2one(
        'petroleum.loan.partner.repayment', required=True, ondelete='cascade')
    loan_issued_id = fields.Many2one(
        'petroleum.loan.issued', string='Loan', required=True)
    loan_date = fields.Date(
        related='loan_issued_id.date', string='Opening Date')
    amount_outstanding = fields.Monetary(
        related='loan_issued_id.amount_outstanding', string='Outstanding')
    amount_allocated = fields.Monetary(string='Allocated')
    amount_remaining = fields.Monetary(
        string='Remaining', compute='_compute_remaining')
    currency_id = fields.Many2one(related='wizard_id.currency_id')
    company_id = fields.Many2one(related='wizard_id.company_id')

    @api.depends('amount_outstanding', 'amount_allocated', 'currency_id')
    def _compute_remaining(self):
        for line in self:
            remaining = (
                (line.amount_outstanding or 0.0)
                - (line.amount_allocated or 0.0)
            )
            currency = line.currency_id
            line.amount_remaining = (
                currency.round(remaining) if currency else remaining
            )

    @api.onchange('amount_allocated')
    def _onchange_amount_allocated(self):
        currency = self.currency_id
        allocated = self.amount_allocated or 0.0
        if currency and currency.compare_amounts(allocated, 0.0) < 0:
            self.amount_allocated = 0.0
        elif (
            currency
            and self.amount_outstanding
            and currency.compare_amounts(allocated, self.amount_outstanding) > 0
        ):
            self.amount_allocated = self.amount_outstanding
