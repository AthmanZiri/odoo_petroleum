# -*- coding: utf-8 -*-
import json
import logging

from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools.float_utils import float_is_zero

_logger = logging.getLogger(__name__)

TOLERANCE_PARAM = 'bank_reconciliation.payment_tolerance'


class AccountBankStatementLine(models.Model):
    _inherit = 'account.bank.statement.line'

    matching_aml_ids = fields.Json(default=lambda self: [], copy=False)
    bank_rec_toolbar = fields.Char(compute='_compute_bank_rec_toolbar')
    available_reconcile_model_ids = fields.Many2many(
        comodel_name='account.reconcile.model',
        compute='_compute_available_reconcile_model_ids',
        string='Available Reconciliation Models',
    )

    def _compute_bank_rec_toolbar(self):
        for line in self:
            line.bank_rec_toolbar = False

    def write(self, vals):
        """Keep matching_aml_ids in sync with kit match-list clicks."""
        if 'lines_widget_json' in vals:
            raw = vals.get('lines_widget_json')
            if not raw:
                vals = dict(vals, matching_aml_ids=[])
            else:
                try:
                    data = json.loads(raw) if isinstance(raw, str) else raw
                except (TypeError, ValueError, json.JSONDecodeError):
                    data = {}
                aml_id = data.get('id') if isinstance(data, dict) else None
                if aml_id:
                    matching_vals = dict(vals)
                    del matching_vals['lines_widget_json']
                    for line in self:
                        selected = list(line.matching_aml_ids or [])
                        aml_int = int(aml_id)
                        if aml_int in selected:
                            selected.remove(aml_int)
                        else:
                            selected.append(aml_int)
                        super(AccountBankStatementLine, line).write(dict(
                            matching_vals,
                            matching_aml_ids=selected,
                            lines_widget_json=raw,
                        ))
                    return True
        return super().write(vals)

    @api.depends('journal_id', 'payment_ref', 'narration', 'amount', 'partner_id', 'company_id')
    def _compute_available_reconcile_model_ids(self):
        Model = self.env['account.reconcile.model']
        for st_line in self:
            models = Model.search([
                ('company_id', '=', st_line.company_id.id),
                ('trigger', '=', 'manual'),
                ('line_ids.account_id', '!=', False),
            ])
            st_line.available_reconcile_model_ids = models.filtered(
                lambda m: m._bank_rec_is_applicable_to_statement_line(st_line)
            )

    # -------------------------------------------------------------------------
    # Validate / Reset
    # -------------------------------------------------------------------------

    def button_validation(self, async_action=False):
        self.ensure_one()
        if self.is_reconciled:
            raise UserError(_("This transaction is already matched."))

        aml_ids = [int(x) for x in (self.matching_aml_ids or []) if x]
        manual_account = self._bank_rec_get_manual_account()
        has_manual = bool(manual_account)

        if aml_ids:
            self._bank_rec_match_move_lines(aml_ids, manual_account=manual_account)
        elif has_manual:
            self._bank_rec_apply_manual_counterpart()
        else:
            raise UserError(_(
                "Select journal items under Match Existing Entries, "
                "or set a non-suspense Account under Manual Operations, then Validate."
            ))

        if not self.is_reconciled:
            if has_manual:
                _liquidity, suspense_lines, _other = self._seek_for_lines()
                if suspense_lines:
                    self._bank_rec_apply_manual_counterpart()
            if not self.is_reconciled:
                raise UserError(_(
                    "Could not fully match this transaction. "
                    "Check the amounts, or book the remainder under Manual Operations."
                ))

        self.matching_aml_ids = []
        self.lines_widget_json = False
        return {'type': 'ir.actions.client', 'tag': 'reload'}

    def button_reset(self):
        self.ensure_one()
        result = super().button_reset()
        self.matching_aml_ids = []
        self.lines_widget_json = False
        return result

    def action_apply_reconcile_model(self, reconcile_model_id):
        """Apply a reconciliation model write-off to this statement line."""
        self.ensure_one()
        model = self.env['account.reconcile.model'].browse(reconcile_model_id).exists()
        if not model:
            raise UserError(_("Reconciliation model not found."))
        model._bank_rec_apply_to_statement_line(self)
        return {'type': 'ir.actions.client', 'tag': 'reload'}

    def action_auto_reconcile(self):
        """Try automatic matching for the selected statement lines."""
        self._bank_rec_try_auto_reconcile()
        return {'type': 'ir.actions.client', 'tag': 'reload'}

    @api.model
    def _cron_bank_rec_auto_reconcile(self, batch_size=50):
        domain = [
            ('is_reconciled', '=', False),
            ('state', '!=', 'cancel'),
            ('journal_id.type', 'in', ('bank', 'cash')),
        ]
        lines = self.search(domain, limit=batch_size, order='date, id')
        lines._bank_rec_try_auto_reconcile()
        return True

    # -------------------------------------------------------------------------
    # Tolerance / helpers
    # -------------------------------------------------------------------------

    @api.model
    def _bank_rec_get_payment_tolerance(self):
        if self.env.context.get('skip_payment_tolerance'):
            return 0.0
        try:
            return float(self.env['ir.config_parameter'].sudo().get_param(TOLERANCE_PARAM, '0.0'))
        except (TypeError, ValueError):
            return 0.0

    def _bank_rec_excluded_accounts(self):
        self.ensure_one()
        return self.journal_id.suspense_account_id | self.journal_id.default_account_id

    def _bank_rec_get_manual_account(self):
        self.ensure_one()
        if not self.account_id or self.account_id in self._bank_rec_excluded_accounts():
            return self.env['account.account']
        return self.account_id

    def _bank_rec_exchange_diff(self, currency, amount, amount_currency):
        """Difference between residual company balance and statement-line rate."""
        self.ensure_one()
        amounts = self._prepare_counterpart_amounts_using_st_line_rate(
            currency, amount, amount_currency,
        )
        origin_balance = amounts['balance']
        if currency.is_zero(origin_balance - amount):
            return 0.0
        return self.company_currency_id.round(origin_balance - amount)

    # -------------------------------------------------------------------------
    # Matching (FX + tolerance + EPD)
    # -------------------------------------------------------------------------

    def _bank_rec_match_move_lines(self, move_line_ids, manual_account=False):
        self.ensure_one()
        move_lines = self.env['account.move.line'].browse(move_line_ids).exists().filtered(
            lambda l: not l.reconciled and l.parent_state in ('posted', 'draft')
        )
        if not move_lines:
            raise UserError(_("No open journal items left to match."))

        if self.move_id.line_ids.matched_debit_ids or self.move_id.line_ids.matched_credit_ids:
            self.action_undo_reconciliation()

        liquidity_lines, _suspense_lines, _other_lines = self._seek_for_lines()
        if not liquidity_lines:
            raise UserError(_("This bank transaction has no liquidity line to reconcile."))

        (
            _tx_amount, transaction_currency,
            _journal_amount, _journal_currency,
            company_amount, company_currency,
        ) = self._get_accounting_amounts_and_currencies()

        tolerance = self._bank_rec_get_payment_tolerance()
        lines_to_add = []
        open_balance = company_amount
        open_amount_currency = self.amount_currency if self.foreign_currency_id else self.amount
        has_baked_fx = False

        for move_line in move_lines:
            residual = move_line.amount_residual
            residual_currency = move_line.amount_residual_currency
            if company_currency.is_zero(residual) and move_line.currency_id.is_zero(residual_currency):
                continue

            exchange_diff = self._bank_rec_exchange_diff(
                move_line.currency_id, residual, residual_currency,
            )
            if not company_currency.is_zero(exchange_diff):
                has_baked_fx = True

            # Counterpart is opposite residual, adjusted for statement rate FX.
            new_balance = -(residual + exchange_diff)
            rate_amounts = self._prepare_counterpart_amounts_using_st_line_rate(
                move_line.currency_id, residual, residual_currency,
            )
            new_amount_currency = -rate_amounts['amount_currency'] if self.foreign_currency_id else -residual_currency

            # Prefer EPD amounts when eligible and within remaining open.
            epd_lines, epd_balance, epd_amount_currency = self._bank_rec_prepare_epd_lines(
                move_line, open_balance, open_amount_currency, transaction_currency,
            )
            if epd_lines:
                lines_to_add.extend(epd_lines)
                open_balance -= epd_balance
                open_amount_currency -= epd_amount_currency
                # Counterpart that clears the receivable/payable via EPD path
                counterpart = {
                    'name': move_line.name or self.payment_ref or '/',
                    'account_id': move_line.account_id.id,
                    'partner_id': move_line.partner_id.id or self.partner_id.id,
                    'currency_id': move_line.currency_id.id,
                    'amount_currency': -move_line.amount_residual_currency,
                    'balance': -move_line.amount_residual,
                    'reconciled_lines_ids': [Command.set(move_line.ids)],
                }
                lines_to_add.append(counterpart)
                open_balance += counterpart['balance']
                open_amount_currency += self._bank_rec_convert_amount_currency(
                    move_line, counterpart['amount_currency'], counterpart['balance'],
                )
                continue

            overflows = (
                (company_currency.compare_amounts(company_amount, 0) > 0
                 and company_currency.compare_amounts(open_balance + new_balance, 0) < 0)
                or (company_currency.compare_amounts(company_amount, 0) < 0
                    and company_currency.compare_amounts(open_balance + new_balance, 0) > 0)
            )
            if overflows:
                leftover = abs(open_balance + new_balance)
                within_tol = (
                    not float_is_zero(tolerance, 6)
                    and company_currency.compare_amounts(leftover, tolerance * abs(residual)) < 0
                )
                if within_tol:
                    # Absorb small leftover: keep full AML clear.
                    pass
                else:
                    new_balance = -open_balance
                    if residual:
                        new_amount_currency = move_line.currency_id.round(
                            -residual_currency * abs(new_balance / residual)
                        )
                    else:
                        new_amount_currency = -open_amount_currency

            if company_currency.is_zero(new_balance) and move_line.currency_id.is_zero(new_amount_currency):
                continue

            open_balance += new_balance
            open_amount_currency += self._bank_rec_convert_amount_currency(
                move_line, new_amount_currency, new_balance,
            )
            lines_to_add.append({
                'name': move_line.name or self.payment_ref or '/',
                'account_id': move_line.account_id.id,
                'partner_id': move_line.partner_id.id or self.partner_id.id,
                'currency_id': move_line.currency_id.id,
                'amount_currency': new_amount_currency,
                'balance': new_balance,
                'reconciled_lines_ids': [Command.set(move_line.ids)],
            })

        if not lines_to_add:
            raise UserError(_("Nothing could be matched from the selected journal items."))

        # Tolerance write-off of residual open balance.
        if (
            not company_currency.is_zero(open_balance)
            and not float_is_zero(tolerance, 6)
            and company_currency.compare_amounts(abs(open_balance), tolerance * abs(company_amount)) < 0
        ):
            writeoff_account = (
                manual_account
                or self.company_id.expense_currency_exchange_account_id
                or self.company_id.income_currency_exchange_account_id
            )
            if writeoff_account:
                currency = self.foreign_currency_id or self.currency_id
                lines_to_add.append({
                    'name': _('Payment difference'),
                    'account_id': writeoff_account.id,
                    'partner_id': self.partner_id.id,
                    'currency_id': currency.id,
                    'amount_currency': -open_amount_currency if self.foreign_currency_id else -open_balance,
                    'balance': -open_balance,
                })
                open_balance = 0.0
                open_amount_currency = 0.0

        commands = [Command.set(liquidity_lines.ids)]
        commands.extend(Command.create(vals) for vals in lines_to_add)

        if not company_currency.is_zero(open_balance):
            counterpart_account = manual_account or self.journal_id.suspense_account_id
            if not counterpart_account:
                raise UserError(_(
                    "Set a suspense account on journal %s, or choose an Account "
                    "under Manual Operations for the remaining amount."
                ) % self.journal_id.display_name)
            currency = self.foreign_currency_id or self.currency_id
            commands.append(Command.create({
                'name': self.payment_ref or '/',
                'account_id': counterpart_account.id,
                'partner_id': self.partner_id.id,
                'currency_id': currency.id,
                'amount_currency': (
                    -open_amount_currency if self.foreign_currency_id else -open_balance
                ),
                'balance': -open_balance,
            }))

        write_ctx = {
            'force_delete': True,
            'skip_readonly_check': True,
        }
        if has_baked_fx:
            write_ctx['no_exchange_difference_no_recursive'] = True

        self.move_id.with_context(**write_ctx).write({'line_ids': commands})

        if hasattr(self.move_id, 'checked') and not self.move_id.checked:
            self.move_id.with_context(skip_readonly_check=True).checked = True

        self._compute_is_reconciled()

    def _bank_rec_prepare_epd_lines(self, move_line, open_balance, open_amount_currency, transaction_currency):
        """Build early payment discount counterpart lines when eligible.

        Returns (extra_lines, balance_consumed_by_epd, amount_currency_consumed).
        """
        self.ensure_one()
        invoice = move_line.move_id
        if not invoice.is_invoice(include_receipts=True):
            return [], 0.0, 0.0
        if not invoice._is_eligible_for_early_payment_discount(transaction_currency, self.date):
            return [], 0.0, 0.0
        if not move_line.discount_amount_currency and not move_line.discount_balance:
            return [], 0.0, 0.0
        discount_date = move_line.discount_date
        if discount_date and self.date > discount_date:
            return [], 0.0, 0.0

        company_currency = self.company_currency_id
        # Statement amount (remaining) should cover invoice residual after discount.
        discount_balance = move_line.discount_balance or 0.0
        pay_balance = move_line.amount_residual - discount_balance
        if company_currency.compare_amounts(abs(open_balance), abs(pay_balance)) < 0:
            return [], 0.0, 0.0

        try:
            epd_values = self.env['account.move']._get_invoice_counterpart_amls_for_early_payment_discount(
                [{
                    'aml': move_line,
                    'amount_currency': -move_line.amount_residual_currency,
                    'balance': -move_line.amount_residual,
                }],
                open_balance,
            )
        except Exception:  # noqa: BLE001 — EPD is best-effort enrichment
            _logger.debug('EPD computation failed for move line %s', move_line.id, exc_info=True)
            return [], 0.0, 0.0

        extra = []
        balance_sum = 0.0
        amount_currency_sum = 0.0
        # Skip exchange_lines — FX handled separately / baked into rates.
        for key in ('term_lines', 'tax_lines', 'base_lines'):
            for vals in epd_values.get(key) or []:
                line_vals = {
                    'name': vals.get('name') or _('Early Payment Discount'),
                    'account_id': vals['account_id'],
                    'partner_id': vals.get('partner_id') or move_line.partner_id.id,
                    'currency_id': vals.get('currency_id') or move_line.currency_id.id,
                    'amount_currency': vals.get('amount_currency', 0.0),
                    'balance': vals.get('balance', 0.0),
                }
                if vals.get('tax_ids'):
                    line_vals['tax_ids'] = vals['tax_ids']
                if vals.get('tax_repartition_line_id'):
                    line_vals['tax_repartition_line_id'] = vals['tax_repartition_line_id']
                if vals.get('tax_tag_ids'):
                    line_vals['tax_tag_ids'] = vals['tax_tag_ids']
                extra.append(line_vals)
                balance_sum += line_vals['balance']
                amount_currency_sum += line_vals['amount_currency']
        return extra, balance_sum, amount_currency_sum

    def _bank_rec_convert_amount_currency(self, move_line, amount_currency, balance):
        self.ensure_one()
        transaction_currency = self.foreign_currency_id or self.currency_id
        if move_line.currency_id == transaction_currency:
            return amount_currency
        if amount_currency:
            return transaction_currency.round(
                move_line.currency_id._convert(
                    amount_currency, transaction_currency, self.company_id, self.date,
                )
            )
        return transaction_currency.round(
            move_line.company_currency_id._convert(
                balance, transaction_currency, self.company_id, self.date,
            )
        )

    def _bank_rec_apply_manual_counterpart(self):
        self.ensure_one()
        manual_account = self._bank_rec_get_manual_account()
        if not manual_account:
            raise UserError(_(
                "Choose an Account under Manual Operations "
                "(not the bank or suspense account)."
            ))

        liquidity_lines, suspense_lines, other_lines = self._seek_for_lines()
        if not liquidity_lines:
            raise UserError(_("This bank transaction has no liquidity line."))

        lines_to_keep = liquidity_lines | other_lines
        commands = [Command.set(lines_to_keep.ids)]

        if suspense_lines:
            open_balance = sum(suspense_lines.mapped('balance'))
            open_amount_currency = sum(suspense_lines.mapped('amount_currency'))
            currency = suspense_lines[:1].currency_id or self.currency_id
            counterpart_vals = {
                'name': self.payment_ref or manual_account.display_name,
                'account_id': manual_account.id,
                'partner_id': self.partner_id.id,
                'currency_id': currency.id,
                'amount_currency': open_amount_currency,
                'balance': open_balance,
            }
            if self.tax_ids:
                counterpart_vals['tax_ids'] = [Command.set(self.tax_ids.ids)]
            commands.append(Command.create(counterpart_vals))
        elif not other_lines:
            line_vals_list = self._prepare_move_line_default_vals(
                counterpart_account_id=manual_account.id
            )
            counterpart_vals = line_vals_list[1]
            if self.tax_ids:
                counterpart_vals['tax_ids'] = [Command.set(self.tax_ids.ids)]
            if self.partner_id:
                counterpart_vals['partner_id'] = self.partner_id.id
            commands = [
                Command.set(liquidity_lines.ids),
                Command.create(counterpart_vals),
            ]
        else:
            return

        self.move_id.with_context(
            force_delete=True, skip_readonly_check=True,
        ).write({'line_ids': commands})
        if hasattr(self.move_id, 'checked') and not self.move_id.checked:
            self.move_id.with_context(skip_readonly_check=True).checked = True
        self._compute_is_reconciled()

    # -------------------------------------------------------------------------
    # Auto-reconciliation
    # -------------------------------------------------------------------------

    def _bank_rec_try_auto_reconcile(self):
        """Best-effort auto match for each unreconciled line."""
        for st_line in self.filtered(lambda l: not l.is_reconciled):
            try:
                st_line._bank_rec_auto_reconcile_one()
            except Exception:  # noqa: BLE001
                _logger.debug(
                    'Auto-reconcile skipped for statement line %s', st_line.id, exc_info=True,
                )

    # Hardened implementation lives in account_bank_statement_line_auto.py

    @api.depends('account_id', 'is_reconciled', 'matching_aml_ids', 'journal_id')
    def _compute_state(self):
        for record in self:
            if record.is_reconciled:
                record.bank_state = 'reconciled'
            elif record.matching_aml_ids or record._bank_rec_get_manual_account():
                record.bank_state = 'valid'
            else:
                record.bank_state = 'invalid'
