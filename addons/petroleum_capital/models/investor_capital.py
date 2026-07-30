from odoo import _, api, fields, models
from odoo.exceptions import UserError


class PetroleumInvestorCapital(models.Model):
    _name = 'petroleum.investor.capital'
    _description = 'Investor Capital'
    _inherit = ['petroleum.capital.mixin', 'mail.thread', 'mail.activity.mixin']
    _order = 'date desc, id desc'

    name = fields.Char(
        string='Reference', required=True, copy=False, default='New',
        tracking=True)
    partner_id = fields.Many2one(
        'res.partner', string='Investor', required=True, tracking=True,
        help='Investor whose capital is recorded under Equity.')
    company_id = fields.Many2one(
        'res.company', required=True, default=lambda self: self.env.company,
        tracking=True)
    currency_id = fields.Many2one(related='company_id.currency_id')
    date = fields.Date(
        string='Opening Date', required=True,
        default=fields.Date.context_today, tracking=True)
    amount = fields.Monetary(
        string='Investment Amount', required=True, tracking=True,
        help='Opening equity capital. ROI payments never reduce this balance.')
    monthly_roi_amount = fields.Monetary(
        string='Monthly ROI', tracking=True,
        help='Default monthly return paid as an Expense (not a capital withdrawal).')
    equity_account_id = fields.Many2one(
        'account.account', string='Equity Account', required=True,
        domain="[('account_type', '=', 'equity'), ('company_ids', 'in', company_id)]",
        tracking=True)
    roi_expense_account_id = fields.Many2one(
        'account.account', string='ROI Expense Account', required=True,
        domain="[('account_type', 'in', ('expense', 'expense_direct_cost')), "
               "('company_ids', 'in', company_id)]",
        tracking=True,
        help='Expense account debited when paying ROI. Equity is never touched.')
    bank_journal_id = fields.Many2one(
        'account.journal', string='Contra Bank (optional)',
        domain="[('type', 'in', ('bank', 'cash')), ('company_id', '=', company_id)]",
        help='If set, opening debits this bank/cash account. '
             'Otherwise the Opening Balance clearing equity account is used.')
    capital_journal_id = fields.Many2one(
        'account.journal', string='Capital Journal', readonly=True,
        help='Dedicated Capital & Loans journal (not Miscellaneous Operations).')
    opening_move_id = fields.Many2one(
        'account.move', string='Opening Entry', readonly=True, copy=False)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('posted', 'Posted'),
    ], default='draft', required=True, tracking=True, copy=False)
    note = fields.Text()

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        company = self.env.company
        if 'equity_account_id' in fields_list and not res.get('equity_account_id'):
            res['equity_account_id'] = self._ensure_investor_equity_account(company).id
        if 'roi_expense_account_id' in fields_list and not res.get('roi_expense_account_id'):
            res['roi_expense_account_id'] = self._ensure_roi_expense_account(company).id
        if 'capital_journal_id' in fields_list and not res.get('capital_journal_id'):
            res['capital_journal_id'] = self._ensure_capital_journal(company).id
        if 'partner_id' in fields_list and not res.get('partner_id'):
            partner = self.env['res.partner'].search([
                ('name', 'ilike', 'Zaynu'),
            ], limit=1)
            if partner:
                res['partner_id'] = partner.id
        if 'amount' in fields_list and not res.get('amount'):
            res['amount'] = 7000000.0
        if 'monthly_roi_amount' in fields_list and not res.get('monthly_roi_amount'):
            res['monthly_roi_amount'] = 250000.0
        return res

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            company = self.env['res.company'].browse(
                vals.get('company_id') or self.env.company.id)
            if not vals.get('equity_account_id'):
                vals['equity_account_id'] = self._ensure_investor_equity_account(company).id
            if not vals.get('roi_expense_account_id'):
                vals['roi_expense_account_id'] = self._ensure_roi_expense_account(company).id
            if not vals.get('capital_journal_id'):
                vals['capital_journal_id'] = self._ensure_capital_journal(company).id
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'petroleum.investor.capital') or _('INV-CAP')
        return super().create(vals_list)

    def action_post_opening(self):
        for rec in self:
            if rec.state == 'posted':
                raise UserError(_('Opening already posted for %s.') % rec.display_name)
            if rec.amount <= 0:
                raise UserError(_('Investment amount must be positive.'))
            if rec.equity_account_id.account_type != 'equity':
                raise UserError(_(
                    'Equity account "%s" must be an Equity chart-of-accounts type.'
                ) % rec.equity_account_id.display_name)

            journal = rec.capital_journal_id or rec._ensure_capital_journal(rec.company_id)
            contra = rec._contra_account_for_opening(
                rec.company_id, rec.bank_journal_id)
            # Investor capital increases on the credit side; equity stays intact
            # when ROI is later paid (ROI uses expense + bank only).
            move = rec._post_balanced_entry(
                company=rec.company_id,
                journal=journal,
                date=rec.date,
                ref=_('Investor capital opening — %s') % rec.partner_id.name,
                debit_account=contra,
                credit_account=rec.equity_account_id,
                amount=rec.amount,
                partner=rec.partner_id,
                line_name=_('Opening investment %s') % rec.partner_id.name,
            )
            rec.write({
                'opening_move_id': move.id,
                'capital_journal_id': journal.id,
                'state': 'posted',
            })
        return True

    def action_pay_roi(self):
        self.ensure_one()
        if self.state != 'posted':
            raise UserError(_('Post the capital opening before paying ROI.'))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Pay Investor ROI'),
            'res_model': 'petroleum.roi.payment',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_investor_capital_id': self.id,
                'default_partner_id': self.partner_id.id,
                'default_amount': self.monthly_roi_amount,
                'default_expense_account_id': self.roi_expense_account_id.id,
                'default_company_id': self.company_id.id,
            },
        }

    def action_open_opening_move(self):
        self.ensure_one()
        if not self.opening_move_id:
            raise UserError(_('No opening entry yet.'))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Opening Entry'),
            'res_model': 'account.move',
            'res_id': self.opening_move_id.id,
            'view_mode': 'form',
            'target': 'current',
        }
