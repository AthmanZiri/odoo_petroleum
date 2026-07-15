# -*- coding: utf-8 -*-
from datetime import date

from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError


class AccountBankRecAutoReconcileWizard(models.TransientModel):
    """Close open receivable/payable items automatically (Perfect Match / Clear Account)."""

    _name = 'bank.rec.auto.reconcile.wizard'
    _description = 'Auto-reconcile journal items'
    _check_company_auto = True

    company_id = fields.Many2one(
        'res.company', required=True, readonly=True,
        default=lambda self: self.env.company,
    )
    from_date = fields.Date(string='From')
    to_date = fields.Date(string='To', default=fields.Date.context_today, required=True)
    account_ids = fields.Many2many(
        'account.account', string='Accounts', check_company=True,
        domain="[('reconcile', '=', True), ('account_type', '!=', 'off_balance')]",
    )
    partner_ids = fields.Many2many('res.partner', string='Partners', check_company=True)
    search_mode = fields.Selection(
        [
            ('one_to_one', 'Perfect Match'),
            ('zero_balance', 'Clear Account'),
        ],
        string='Reconcile', required=True, default='one_to_one',
        help='Perfect Match: pair opposite residual lines of the same amount.\n'
             'Clear Account: reconcile all lines in a group whose residuals sum to zero.',
    )

    def _get_amls_domain(self):
        self.ensure_one()
        domain = [
            ('company_id', '=', self.company_id.id),
            ('parent_state', '=', 'posted'),
            ('display_type', 'not in', ('line_section', 'line_subsection', 'line_note')),
            ('date', '>=', self.from_date or date.min),
            ('date', '<=', self.to_date),
            ('reconciled', '=', False),
            ('account_id.reconcile', '=', True),
            ('amount_residual', '!=', 0.0),
        ]
        if self.account_ids:
            domain.append(('account_id', 'in', self.account_ids.ids))
        if self.partner_ids:
            domain.append(('partner_id', 'in', self.partner_ids.ids))
        return domain

    def _auto_reconcile_one_to_one(self):
        grouped = self.env['account.move.line']._read_group(
            self._get_amls_domain(),
            ['account_id', 'partner_id', 'currency_id', 'amount_residual_currency:abs_rounded'],
            ['id:recordset'],
        )
        all_reconciled = self.env['account.move.line']
        plan = []
        for *__, grouped_amls in grouped:
            positive = grouped_amls.filtered(lambda a: a.amount_residual_currency >= 0).sorted('date')
            negative = (grouped_amls - positive).sorted('date')
            n = min(len(positive), len(negative))
            positive, negative = positive[:n], negative[:n]
            all_reconciled |= positive | negative
            plan += [pos + neg for pos, neg in zip(positive, negative)]
        if plan:
            self.env['account.move.line']._reconcile_plan(plan)
        return all_reconciled

    def _auto_reconcile_zero_balance(self):
        grouped = self.env['account.move.line']._read_group(
            self._get_amls_domain(),
            groupby=['account_id', 'partner_id', 'currency_id'],
            aggregates=['id:recordset'],
            having=[('amount_residual_currency:sum_rounded', '=', 0)],
        )
        all_reconciled = self.env['account.move.line']
        plan = []
        for row in grouped:
            amls = row[-1]
            all_reconciled |= amls
            plan.append(amls)
        if plan:
            self.env['account.move.line']._reconcile_plan(plan)
        return all_reconciled

    def action_auto_reconcile(self):
        self.ensure_one()
        if self.search_mode == 'zero_balance':
            reconciled = self._auto_reconcile_zero_balance()
        else:
            reconciled = self._auto_reconcile_one_to_one()
        related = self.env['account.move.line'].search([
            ('full_reconcile_id', 'in', reconciled.full_reconcile_id.ids),
        ]) if reconciled else reconciled
        if not related:
            raise UserError(_("Nothing to reconcile."))
        return {
            'name': _('Automatically Reconciled Entries'),
            'type': 'ir.actions.act_window',
            'res_model': 'account.move.line',
            'view_mode': 'list',
            'domain': [('id', 'in', related.ids)],
            'context': {'search_default_group_by_matching': True},
        }


class AccountBankRecReconcileWizard(models.TransientModel):
    """Reconcile selected journal items (with optional write-off for the difference)."""

    _name = 'bank.rec.reconcile.wizard'
    _description = 'Reconcile journal items'
    _check_company_auto = True

    company_id = fields.Many2one(
        'res.company', required=True, readonly=True,
        default=lambda self: self.env.company,
    )
    move_line_ids = fields.Many2many(
        'account.move.line', string='Journal Items', required=True,
    )
    company_currency_id = fields.Many2one(related='company_id.currency_id')
    residual = fields.Monetary(
        string='Residual', currency_field='company_currency_id',
        compute='_compute_residual',
    )
    allow_write_off = fields.Boolean(string='Write-off difference')
    write_off_account_id = fields.Many2one(
        'account.account', string='Write-off Account', check_company=True,
        domain="[('account_type', '!=', 'off_balance')]",
    )
    write_off_journal_id = fields.Many2one(
        'account.journal', string='Write-off Journal', check_company=True,
        domain="[('type', '=', 'general')]",
        default=lambda self: self.env['account.journal'].search([
            *self.env['account.journal']._check_company_domain(self.env.company),
            ('type', '=', 'general'),
        ], limit=1),
    )
    label = fields.Char(string='Label', default=lambda self: _('Write-off'))

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        if self.env.context.get('active_model') == 'account.move.line':
            lines = self.env['account.move.line'].browse(self.env.context.get('active_ids', []))
            lines = lines.filtered(lambda l: not l.reconciled and l.account_id.reconcile)
            if not lines:
                raise UserError(_("Select open reconciliable journal items."))
            res['move_line_ids'] = [Command.set(lines.ids)]
        return res

    @api.depends('move_line_ids.amount_residual')
    def _compute_residual(self):
        for wiz in self:
            wiz.residual = sum(wiz.move_line_ids.mapped('amount_residual'))

    def action_reconcile(self):
        self.ensure_one()
        lines = self.move_line_ids.filtered(lambda l: not l.reconciled)
        if len(lines) < 2 and not self.allow_write_off:
            raise UserError(_("Select at least two open journal items to reconcile."))
        currency = self.company_currency_id
        residual = sum(lines.mapped('amount_residual'))
        if not currency.is_zero(residual):
            if not self.allow_write_off or not self.write_off_account_id or not self.write_off_journal_id:
                raise UserError(_(
                    "Lines do not balance (residual %s). "
                    "Enable write-off and choose an account/journal, or select balancing lines."
                ) % residual)
            move = self.env['account.move'].create({
                'journal_id': self.write_off_journal_id.id,
                'date': fields.Date.context_today(self),
                'ref': self.label,
                'line_ids': [
                    Command.create({
                        'name': self.label,
                        'account_id': lines[0].account_id.id,
                        'partner_id': lines[0].partner_id.id,
                        'debit': -residual if residual < 0 else 0.0,
                        'credit': residual if residual > 0 else 0.0,
                    }),
                    Command.create({
                        'name': self.label,
                        'account_id': self.write_off_account_id.id,
                        'partner_id': lines[0].partner_id.id,
                        'debit': residual if residual > 0 else 0.0,
                        'credit': -residual if residual < 0 else 0.0,
                    }),
                ],
            })
            move.action_post()
            write_line = move.line_ids.filtered(
                lambda l: l.account_id == lines[0].account_id
            )
            lines |= write_line
        lines.reconcile()
        return {'type': 'ir.actions.act_window_close'}
