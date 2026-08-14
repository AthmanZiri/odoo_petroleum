from odoo import _, api, fields, models
from odoo.exceptions import UserError


class PetroleumLoanIssued(models.Model):
    _name = 'petroleum.loan.issued'
    _description = 'Loan Issued'
    _inherit = ['petroleum.capital.mixin', 'mail.thread', 'mail.activity.mixin']
    _order = 'date desc, id desc'

    name = fields.Char(
        string='Reference', required=True, copy=False, default='New',
        tracking=True)
    partner_id = fields.Many2one(
        'res.partner', string='Borrower', required=True, tracking=True,
        help='Party to whom the loan was issued.')
    company_id = fields.Many2one(
        'res.company', required=True, default=lambda self: self.env.company,
        tracking=True)
    currency_id = fields.Many2one(related='company_id.currency_id')
    date = fields.Date(
        string='Opening Date', required=True,
        default=fields.Date.context_today, tracking=True)
    amount = fields.Monetary(
        string='Loan Amount', required=True, tracking=True)
    asset_account_id = fields.Many2one(
        'account.account', string='Loans Issued Account', required=True,
        domain="[('account_type', '=', 'asset_current'), "
               "('company_ids', 'in', company_id)]",
        tracking=True,
        help='Current Assets account for loans receivable / loans issued.')
    bank_journal_id = fields.Many2one(
        'account.journal', string='Contra Bank (optional)',
        domain="[('type', 'in', ('bank', 'cash')), ('company_id', '=', company_id)]",
        help='If set, opening credits this bank/cash account. '
             'Otherwise the Opening Balance clearing equity account is used.')
    capital_journal_id = fields.Many2one(
        'account.journal', string='Capital Journal', readonly=True)
    opening_move_id = fields.Many2one(
        'account.move', string='Opening Entry', readonly=True, copy=False)
    repayment_move_ids = fields.Many2many(
        'account.move', 'petroleum_loan_issued_repayment_rel',
        'loan_id', 'move_id', string='Repayment Entries',
        copy=False, readonly=True)
    amount_repaid = fields.Monetary(
        string='Repaid', compute='_compute_repayment_amounts', store=True)
    amount_outstanding = fields.Monetary(
        string='Outstanding', compute='_compute_repayment_amounts', store=True)
    repayment_count = fields.Integer(
        compute='_compute_repayment_count')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('posted', 'Posted'),
    ], default='draft', required=True, tracking=True, copy=False)
    note = fields.Text()

    @api.depends(
        'amount', 'asset_account_id',
        'repayment_move_ids.state',
        'repayment_move_ids.line_ids.debit',
        'repayment_move_ids.line_ids.credit',
        'repayment_move_ids.line_ids.account_id',
    )
    def _compute_repayment_amounts(self):
        for rec in self:
            currency = rec.currency_id
            repaid = 0.0
            moves = rec.repayment_move_ids.filtered(lambda m: m.state == 'posted')
            asset = rec.asset_account_id
            if asset:
                for line in moves.line_ids:
                    if line.account_id == asset:
                        repaid += line.credit - line.debit
            repaid = currency.round(repaid) if currency else repaid
            outstanding = (rec.amount or 0.0) - repaid
            if currency:
                outstanding = currency.round(outstanding)
                if currency.compare_amounts(outstanding, 0.0) < 0:
                    outstanding = 0.0
            rec.amount_repaid = repaid
            rec.amount_outstanding = outstanding

    @api.depends('repayment_move_ids')
    def _compute_repayment_count(self):
        for rec in self:
            rec.repayment_count = len(rec.repayment_move_ids)

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        company = self.env.company
        if 'asset_account_id' in fields_list and not res.get('asset_account_id'):
            res['asset_account_id'] = self._ensure_loans_issued_account(company).id
        if 'capital_journal_id' in fields_list and not res.get('capital_journal_id'):
            res['capital_journal_id'] = self._ensure_capital_journal(company).id
        if 'partner_id' in fields_list and not res.get('partner_id'):
            partner = self.env['res.partner'].search([
                ('name', 'ilike', 'Muhidin'),
            ], limit=1)
            if partner:
                res['partner_id'] = partner.id
        if 'amount' in fields_list and not res.get('amount'):
            res['amount'] = 9676340.17
        return res

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            company = self.env['res.company'].browse(
                vals.get('company_id') or self.env.company.id)
            if not vals.get('asset_account_id'):
                vals['asset_account_id'] = self._ensure_loans_issued_account(company).id
            if not vals.get('capital_journal_id'):
                vals['capital_journal_id'] = self._ensure_capital_journal(company).id
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'petroleum.loan.issued') or _('LOAN')
        return super().create(vals_list)

    def action_post_opening(self):
        for rec in self:
            if rec.state == 'posted':
                raise UserError(_('Opening already posted for %s.') % rec.display_name)
            if rec.amount <= 0:
                raise UserError(_('Loan amount must be positive.'))
            if rec.asset_account_id.account_type != 'asset_current':
                raise UserError(_(
                    'Loans Issued account "%s" must be a Current Assets type.'
                ) % rec.asset_account_id.display_name)

            journal = rec.capital_journal_id or rec._ensure_capital_journal(rec.company_id)
            contra = rec._contra_account_for_opening(
                rec.company_id, rec.bank_journal_id)
            # Asset increases (debit loans issued); contra is bank or opening clearing.
            move = rec._post_balanced_entry(
                company=rec.company_id,
                journal=journal,
                date=rec.date,
                ref=_('Loan issued opening — %s') % rec.partner_id.name,
                debit_account=rec.asset_account_id,
                credit_account=contra,
                amount=rec.amount,
                partner=rec.partner_id,
                line_name=_('Loan issued to %s') % rec.partner_id.name,
            )
            rec.write({
                'opening_move_id': move.id,
                'capital_journal_id': journal.id,
                'state': 'posted',
            })
        return True

    def action_receive_repayment(self):
        self.ensure_one()
        if self.state != 'posted':
            raise UserError(_('Post the loan opening before receiving a repayment.'))
        if self.currency_id.compare_amounts(self.amount_outstanding, 0.0) <= 0:
            raise UserError(_('This loan is already fully repaid.'))
        context = {
            'default_loan_issued_id': self.id,
            'default_partner_id': self.partner_id.id,
            'default_amount': self.amount_outstanding,
            'default_company_id': self.company_id.id,
        }
        if self.bank_journal_id:
            context['default_bank_journal_id'] = self.bank_journal_id.id
        return {
            'type': 'ir.actions.act_window',
            'name': _('Receive Loan Repayment'),
            'res_model': 'petroleum.loan.repayment',
            'view_mode': 'form',
            'target': 'new',
            'context': context,
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

    def action_open_repayment_moves(self):
        self.ensure_one()
        if not self.repayment_move_ids:
            raise UserError(_('No repayment entries yet.'))
        action = {
            'type': 'ir.actions.act_window',
            'name': _('Repayment Entries'),
            'res_model': 'account.move',
            'target': 'current',
        }
        if len(self.repayment_move_ids) == 1:
            action.update({
                'res_id': self.repayment_move_ids.id,
                'view_mode': 'form',
            })
        else:
            action.update({
                'view_mode': 'list,form',
                'domain': [('id', 'in', self.repayment_move_ids.ids)],
            })
        return action
