from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
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
        'res.partner', string='Investor',
        related='investor_capital_id.partner_id', readonly=True)
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
    analytic_distribution = fields.Json(string='Analytic Distribution')
    analytic_precision = fields.Integer(
        default=lambda self: self.env['decimal.precision'].precision_get(
            'Percentage Analytic'))
    setup_warning = fields.Char(compute='_compute_setup_warning')
    move_id = fields.Many2one('account.move', readonly=True, copy=False)

    def _default_pay_from_journal(self, company):
        return self.env['account.journal'].search([
            ('type', 'in', ('bank', 'cash')),
            ('company_id', '=', company.id),
            ('default_account_id', '!=', False),
        ], limit=1)

    @api.depends('company_id')
    def _compute_setup_warning(self):
        for wiz in self:
            company = wiz.company_id or self.env.company
            posted = self.env['petroleum.investor.capital'].search_count([
                ('state', '=', 'posted'),
                ('company_id', '=', company.id),
            ])
            if posted:
                wiz.setup_warning = False
            else:
                wiz.setup_warning = _(
                    'No posted investor capital. Open Investor Capital, '
                    'set Monthly ROI, click Post Opening, then pay ROI here.'
                )

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        company = self.env.company
        if 'company_id' in fields_list and not res.get('company_id'):
            res['company_id'] = company.id
        if 'bank_journal_id' in fields_list and not res.get('bank_journal_id'):
            journal = self._default_pay_from_journal(company)
            if journal:
                res['bank_journal_id'] = journal.id
        capital = False
        if 'investor_capital_id' in fields_list and not res.get('investor_capital_id'):
            capitals = self.env['petroleum.investor.capital'].search([
                ('state', '=', 'posted'),
                ('company_id', '=', company.id),
            ], limit=2)
            if len(capitals) == 1:
                capital = capitals
                res['investor_capital_id'] = capitals.id
        else:
            capital = self.env['petroleum.investor.capital'].browse(
                res.get('investor_capital_id'))
        if capital:
            if 'amount' in fields_list and not res.get('amount'):
                res['amount'] = capital.monthly_roi_amount
            if 'expense_account_id' in fields_list and not res.get('expense_account_id'):
                res['expense_account_id'] = capital.roi_expense_account_id.id
            if (
                'bank_journal_id' in fields_list
                and capital.bank_journal_id
                and capital.bank_journal_id.default_account_id
            ):
                res['bank_journal_id'] = capital.bank_journal_id.id
        if (
            'expense_account_id' in fields_list
            and not res.get('expense_account_id')
        ):
            res['expense_account_id'] = self._ensure_roi_expense_account(company).id
        expense = self.env['account.account'].browse(res.get('expense_account_id'))
        partner = capital.partner_id if capital else self.env['res.partner']
        if 'analytic_distribution' in fields_list and not res.get('analytic_distribution'):
            res['analytic_distribution'] = self._analytic_distribution_for(
                expense, partner, company)
        return res

    def _sync_analytic(self):
        self.analytic_distribution = self._analytic_distribution_for(
            self.expense_account_id,
            self.partner_id,
            self.company_id or self.env.company,
        )

    @api.onchange('investor_capital_id')
    def _onchange_investor_capital(self):
        if self.investor_capital_id:
            capital = self.investor_capital_id
            self.company_id = capital.company_id
            self.amount = capital.monthly_roi_amount
            self.expense_account_id = capital.roi_expense_account_id
            if capital.bank_journal_id and capital.bank_journal_id.default_account_id:
                self.bank_journal_id = capital.bank_journal_id
            elif not self.bank_journal_id:
                self.bank_journal_id = self._default_pay_from_journal(
                    capital.company_id or self.env.company)
            self._sync_analytic()

    @api.onchange('expense_account_id', 'partner_id', 'company_id')
    def _onchange_analytic_source(self):
        self._sync_analytic()

    def action_confirm(self):
        self.ensure_one()
        if not self.investor_capital_id:
            raise UserError(_(
                'Select a posted investor capital. If the list is empty, open '
                'Investor Capital and click Post Opening first.'
            ))
        if self.investor_capital_id.state != 'posted':
            raise UserError(_(
                'Post the capital opening for %s before paying ROI.'
            ) % self.investor_capital_id.display_name)
        partner = self.partner_id or self.investor_capital_id.partner_id
        if not partner:
            raise UserError(_('Investor is required on the capital record.'))
        amount = self.amount or self.investor_capital_id.monthly_roi_amount
        if (amount or 0.0) <= 0:
            raise UserError(_(
                'ROI amount must be positive. Set Monthly ROI on the investor '
                'capital record or enter the amount to pay.'
            ))
        expense_account = (
            self.expense_account_id
            or self.investor_capital_id.roi_expense_account_id
            or self._ensure_roi_expense_account(self.company_id)
        )
        if expense_account.account_type not in ('expense', 'expense_direct_cost'):
            raise UserError(_(
                'ROI must post to an Expense account so invested capital is not reduced. '
                '"%s" is type %s.'
            ) % (
                expense_account.display_name,
                expense_account.account_type,
            ))
        bank_journal = self.bank_journal_id
        if not bank_journal:
            bank_journal = (
                self.investor_capital_id.bank_journal_id
                or self._default_pay_from_journal(self.company_id)
            )
        if not bank_journal:
            raise UserError(_(
                'Select the bank or cash journal to pay from. '
                'A Chart of Accounts bank line is not enough — open the cash book '
                '(Bank/Cash journal) first.'
            ))
        bank_account = bank_journal.default_account_id
        if not bank_account:
            raise UserError(_(
                'Bank journal "%s" has no default account. '
                'Open Accounting → Configuration → Journals and set Default Account.'
            ) % bank_journal.display_name)

        equity_account = self.investor_capital_id.equity_account_id
        if expense_account == equity_account:
            raise UserError(_(
                'ROI expense account cannot be the investor equity account. '
                'Paying ROI must not reduce the amount invested.'
            ))

        analytic = self.analytic_distribution or self._analytic_distribution_for(
            expense_account, partner, self.company_id)
        ref = self.memo or _('ROI payment — %s') % partner.name
        line_name = _('Monthly ROI %s') % partner.name

        # Dr Expense / Cr Bank — equity capital untouched.
        move = self.env['account.move'].with_context(skip_invoice_sync=True).create({
            'move_type': 'entry',
            'journal_id': bank_journal.id,
            'date': self.payment_date,
            'ref': ref,
            'company_id': self.company_id.id,
            'line_ids': [
                Command.create({
                    'name': line_name,
                    'account_id': expense_account.id,
                    'partner_id': partner.id,
                    'debit': amount,
                    'credit': 0.0,
                    'analytic_distribution': analytic or False,
                }),
                Command.create({
                    'name': line_name,
                    'account_id': bank_account.id,
                    'partner_id': partner.id,
                    'debit': 0.0,
                    'credit': amount,
                }),
            ],
        })
        try:
            move.action_post()
        except (UserError, ValidationError) as err:
            if 'analytic' in str(err).lower():
                raise UserError(_(
                    'ROI expense requires a 100%% analytic distribution. '
                    'Set Analytic on this wizard (or a distribution model for %s), '
                    'then pay ROI again.'
                ) % expense_account.display_name) from err
            raise
        self.move_id = move.id
        return {
            'type': 'ir.actions.act_window',
            'name': _('ROI Payment'),
            'res_model': 'account.move',
            'res_id': move.id,
            'view_mode': 'form',
            'target': 'current',
        }
