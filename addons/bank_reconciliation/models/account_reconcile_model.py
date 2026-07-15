# -*- coding: utf-8 -*-
import logging
import re

from odoo import Command, _, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class AccountReconcileModel(models.Model):
    _inherit = 'account.reconcile.model'

    def _bank_rec_is_applicable_to_statement_line(self, st_line):
        """Return True if this model matches the statement line filters."""
        self.ensure_one()
        if self.match_journal_ids and st_line.journal_id not in self.match_journal_ids:
            return False
        if self.match_partner_ids and st_line.partner_id not in self.match_partner_ids:
            return False

        amount = abs(st_line.amount)
        if self.match_amount == 'lower' and amount > self.match_amount_max:
            return False
        if self.match_amount == 'greater' and amount < self.match_amount_min:
            return False
        if self.match_amount == 'between' and not (
            self.match_amount_min <= amount <= self.match_amount_max
        ):
            return False

        if self.match_label:
            haystack = ' '.join(filter(None, [
                st_line.payment_ref or '',
                st_line.narration or '',
                getattr(st_line, 'transaction_details', None) and str(st_line.transaction_details) or '',
            ])).lower()
            needle = (self.match_label_param or '').lower()
            if self.match_label == 'contains' and needle not in haystack:
                return False
            if self.match_label == 'not_contains' and needle in haystack:
                return False
            if self.match_label == 'match_regex':
                try:
                    if not re.search(self.match_label_param or '', haystack, flags=re.IGNORECASE):
                        return False
                except re.error:
                    return False
        return True

    def _bank_rec_apply_to_statement_line(self, st_line):
        """Apply write-off lines from this model onto the statement line move."""
        self.ensure_one()
        if st_line.is_reconciled:
            return

        liquidity_lines, suspense_lines, other_lines = st_line._seek_for_lines()
        if not liquidity_lines:
            raise UserError(_("This bank transaction has no liquidity line."))

        # Remaining open = suspense balances (or full amount if pristine).
        if suspense_lines:
            open_balance = sum(suspense_lines.mapped('balance'))
            open_amount_currency = sum(suspense_lines.mapped('amount_currency'))
            currency = suspense_lines[:1].currency_id or st_line.currency_id
        else:
            (
                _tx, _tx_curr, _j_amt, _j_curr, company_amount, _comp_curr
            ) = st_line._get_accounting_amounts_and_currencies()
            open_balance = -company_amount  # counterpart side of liquidity
            open_amount_currency = -(
                st_line.amount_currency if st_line.foreign_currency_id else st_line.amount
            )
            currency = st_line.foreign_currency_id or st_line.currency_id

        writeoff_vals = []
        residual_balance = open_balance
        residual_amount_currency = open_amount_currency

        st_amount = st_line.amount
        for line in self.line_ids.filtered('account_id'):
            balance, amount_currency = self._bank_rec_model_line_amounts(
                line, st_line, residual_balance, residual_amount_currency, st_amount,
            )
            if st_line.company_currency_id.is_zero(balance) and currency.is_zero(amount_currency):
                continue
            vals = {
                'name': line.label or self.name or st_line.payment_ref or '/',
                'account_id': line.account_id.id,
                'partner_id': (line.partner_id or st_line.partner_id).id,
                'currency_id': currency.id,
                'amount_currency': amount_currency,
                'balance': balance,
                'reconcile_model_id': self.id,
            }
            if line.tax_ids:
                vals['tax_ids'] = [Command.set(line.tax_ids.ids)]
            if line.analytic_distribution:
                vals['analytic_distribution'] = line.analytic_distribution
            writeoff_vals.append(vals)
            residual_balance -= balance
            residual_amount_currency -= amount_currency

        if not writeoff_vals:
            raise UserError(_("Reconciliation model %s has no account lines to apply.") % self.display_name)

        commands = [Command.set((liquidity_lines | other_lines).ids)]
        commands.extend(Command.create(v) for v in writeoff_vals)

        # Keep remainder on suspense unless fully consumed.
        if not st_line.company_currency_id.is_zero(residual_balance):
            suspense = st_line.journal_id.suspense_account_id
            if not suspense:
                raise UserError(_("Configure a suspense account on journal %s.") % st_line.journal_id.display_name)
            commands.append(Command.create({
                'name': st_line.payment_ref or '/',
                'account_id': suspense.id,
                'partner_id': st_line.partner_id.id,
                'currency_id': currency.id,
                'amount_currency': residual_amount_currency,
                'balance': residual_balance,
            }))

        st_line.move_id.with_context(
            force_delete=True, skip_readonly_check=True,
        ).write({'line_ids': commands})
        if hasattr(st_line.move_id, 'checked') and not st_line.move_id.checked:
            st_line.move_id.with_context(skip_readonly_check=True).checked = True
        st_line._compute_is_reconciled()

        if self.next_activity_type_id:
            st_line.activity_schedule(
                activity_type_id=self.next_activity_type_id.id,
                summary=_('Review: %s', self.name),
            )

    def _bank_rec_model_line_amounts(self, line, st_line, residual_balance, residual_amount_currency, st_amount):
        """Compute write-off balance/amount_currency for one model line."""
        company_currency = st_line.company_currency_id

        if line.amount_type == 'fixed':
            extracted = abs(line.amount or 0.0)
            balance = company_currency.round(
                extracted if residual_balance >= 0 else -extracted
            )
            amount_currency = balance
        elif line.amount_type == 'percentage':
            pct = (line.amount or 0.0) / 100.0
            balance = company_currency.round(residual_balance * pct)
            amount_currency = st_line.currency_id.round(residual_amount_currency * pct)
        elif line.amount_type == 'percentage_st_line':
            pct = (line.amount or 0.0) / 100.0
            (
                _tx, _txc, _ja, _jc, company_amount, _cc
            ) = st_line._get_accounting_amounts_and_currencies()
            balance = company_currency.round(-company_amount * pct)
            amount_currency = st_line.currency_id.round(
                -(st_line.amount_currency if st_line.foreign_currency_id else st_line.amount) * pct
            )
        elif line.amount_type == 'regex':
            balance = 0.0
            amount_currency = 0.0
            text = st_line.payment_ref or ''
            try:
                match = re.search(line.amount_string or '', text)
                if match:
                    raw = match.group(1) if match.lastindex else match.group(0)
                    raw = raw.replace(' ', '').replace(',', '.')
                    extracted = abs(float(raw))
                    balance = company_currency.round(
                        extracted if residual_balance >= 0 else -extracted
                    )
                    amount_currency = balance
            except (re.error, ValueError, TypeError):
                _logger.debug('Regex amount extraction failed for model line %s', line.id)
        else:
            balance = residual_balance
            amount_currency = residual_amount_currency

        return balance, amount_currency

    def trigger_reconciliation_model(self, statement_line_id):
        """Public RPC for OWL / kit widgets (Enterprise-compatible method name)."""
        st_line = self.env['account.bank.statement.line'].browse(statement_line_id).exists()
        if not st_line:
            raise UserError(_("Statement line not found."))
        for model in self:
            model._bank_rec_apply_to_statement_line(st_line)
        return True
