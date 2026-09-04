from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.fields import Command


class PetroleumDeskCustomerExpense(models.TransientModel):
    """Post Expense ↔ customer receivable without using a sales invoice."""

    _name = 'petroleum.desk.customer.expense'
    _description = 'Expense ↔ Customer'

    DIRECTION_ABSORB = 'absorb'
    DIRECTION_CHARGE = 'charge'

    company_id = fields.Many2one(
        'res.company', required=True, default=lambda self: self.env.company)
    currency_id = fields.Many2one(related='company_id.currency_id')
    partner_id = fields.Many2one(
        'res.partner', string='Customer', required=True,
        domain="['|', ('company_id', '=', False), ('company_id', '=', company_id)]")
    expense_account_id = fields.Many2one(
        'account.account', string='Expense Account', required=True,
        domain="[('account_type', 'in', ('expense', 'expense_direct_cost')), "
               "('company_ids', 'in', company_id)]")
    receivable_account_id = fields.Many2one(
        'account.account', string="Debtor's Account", required=True,
        domain="[('account_type', '=', 'asset_receivable'), "
               "('company_ids', 'in', company_id)]")
    journal_id = fields.Many2one(
        'account.journal', string='Journal', required=True,
        domain="[('type', '=', 'general'), ('company_id', '=', company_id)]")
    direction = fields.Selection([
        ('absorb', 'Dr Expense / Cr Debtor — reduce what the customer owes'),
        ('charge', 'Dr Debtor / Cr Expense — charge the customer for a cost'),
    ], required=True, default='absorb',
        help='Absorb: company cost that credits the customer (rebate, write-off, '
             'customer paid a cost for us). Charge: recover a cost on the '
             'customer statement. Taxable recoveries should be a customer invoice.')
    amount = fields.Monetary(required=True)
    entry_date = fields.Date(
        string='Date', required=True, default=fields.Date.context_today)
    memo = fields.Char(string='Reference')
    analytic_distribution = fields.Json(string='Analytic Distribution')
    analytic_precision = fields.Integer(
        default=lambda self: self.env['decimal.precision'].precision_get(
            'Percentage Analytic'))
    move_id = fields.Many2one('account.move', readonly=True, copy=False)

    def _default_general_journal(self, company):
        Journal = self.env['account.journal']
        return Journal.search([
            ('company_id', '=', company.id),
            ('type', '=', 'general'),
            ('code', '=', 'MISC'),
        ], limit=1) or Journal.search([
            ('company_id', '=', company.id),
            ('type', '=', 'general'),
        ], limit=1)

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        company = self.env.company
        if 'company_id' in fields_list and not res.get('company_id'):
            res['company_id'] = company.id
        if 'journal_id' in fields_list and not res.get('journal_id'):
            journal = self._default_general_journal(company)
            if journal:
                res['journal_id'] = journal.id
        partner = self.env['res.partner'].browse(res.get('partner_id'))
        if (
            'receivable_account_id' in fields_list
            and not res.get('receivable_account_id')
            and partner
        ):
            receivable = partner.with_company(company).property_account_receivable_id
            if receivable:
                res['receivable_account_id'] = receivable.id
        if (
            'analytic_distribution' in fields_list
            and not res.get('analytic_distribution')
            and res.get('expense_account_id')
        ):
            expense = self.env['account.account'].browse(res['expense_account_id'])
            res['analytic_distribution'] = self.env[
                'petroleum.capital.mixin'
            ]._analytic_distribution_for(expense, partner, company)
        return res

    @api.onchange('partner_id', 'company_id')
    def _onchange_partner(self):
        if self.partner_id:
            receivable = self.partner_id.with_company(
                self.company_id or self.env.company
            ).property_account_receivable_id
            if receivable:
                self.receivable_account_id = receivable
            self._sync_analytic()

    @api.onchange('expense_account_id')
    def _onchange_expense_account(self):
        self._sync_analytic()

    def _sync_analytic(self):
        self.analytic_distribution = self.env[
            'petroleum.capital.mixin'
        ]._analytic_distribution_for(
            self.expense_account_id,
            self.partner_id,
            self.company_id or self.env.company,
        )

    def action_confirm(self):
        self.ensure_one()
        if (self.amount or 0.0) <= 0:
            raise UserError(_('Amount must be positive.'))
        if not self.partner_id:
            raise UserError(_('Select the customer whose debtor account is affected.'))
        if not self.expense_account_id:
            raise UserError(_('Select the expense account.'))
        if self.expense_account_id.account_type not in (
                'expense', 'expense_direct_cost'):
            raise UserError(_(
                'Use a P&L Expense account, not equity or a balance-sheet asset.'
            ))
        receivable = self.receivable_account_id or self.partner_id.with_company(
            self.company_id
        ).property_account_receivable_id
        if not receivable or receivable.account_type != 'asset_receivable':
            raise UserError(_(
                "Set the customer's receivable (debtor) account."
            ))
        journal = self.journal_id or self._default_general_journal(self.company_id)
        if not journal or journal.type != 'general':
            raise UserError(_(
                'Use a Miscellaneous / general journal. Do not post this as a '
                'customer invoice — that path requires eTIMS products and VAT.'
            ))

        absorb = self.direction != self.DIRECTION_CHARGE
        label = self.memo or (
            _('Expense credited to %s') % self.partner_id.name
            if absorb else
            _('Expense charged to %s') % self.partner_id.name
        )
        analytic = self.analytic_distribution or False
        expense_vals = {
            'name': label,
            'account_id': self.expense_account_id.id,
            'partner_id': self.partner_id.id,
            'debit': self.amount if absorb else 0.0,
            'credit': 0.0 if absorb else self.amount,
            'analytic_distribution': analytic,
        }
        debtor_vals = {
            'name': label,
            'account_id': receivable.id,
            'partner_id': self.partner_id.id,
            'debit': 0.0 if absorb else self.amount,
            'credit': self.amount if absorb else 0.0,
        }
        move = self.env['account.move'].with_context(skip_invoice_sync=True).create({
            'move_type': 'entry',
            'journal_id': journal.id,
            'date': self.entry_date,
            'ref': label,
            'company_id': self.company_id.id,
            'partner_id': self.partner_id.id,
            'line_ids': [Command.create(expense_vals), Command.create(debtor_vals)],
        })
        try:
            move.action_post()
        except (UserError, ValidationError) as err:
            if 'analytic' in str(err).lower():
                raise UserError(_(
                    'This expense account requires a 100%% analytic distribution. '
                    'Set Analytic on this wizard, then post again.'
                )) from err
            raise
        self.move_id = move.id
        return {
            'type': 'ir.actions.act_window',
            'name': _('Expense ↔ Customer'),
            'res_model': 'account.move',
            'res_id': move.id,
            'view_mode': 'form',
            'target': 'current',
        }
