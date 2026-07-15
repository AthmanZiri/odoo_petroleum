# -*- coding: utf-8 -*-
"""Phase A/B enhancements: auto-match, partner retrieve, to-check, FX helpers.

Kept in a mixin-style inherit so the main validation module stays readable.
"""
import logging
import re
from itertools import combinations

from odoo import _, api, fields, models


_logger = logging.getLogger(__name__)


class AccountBankStatementLine(models.Model):
    _inherit = 'account.bank.statement.line'

    def _bank_rec_auto_reconcile_one(self):
        """Hardened auto-match: partner map → retrieve partner → ref → amount → models."""
        self.ensure_one()
        if self.is_reconciled:
            return

        # 1) Partner mapping models
        partner_models = self.env['account.reconcile.model'].search([
            ('company_id', '=', self.company_id.id),
            ('mapped_partner_id', '!=', False),
        ])
        for model in partner_models:
            if model._bank_rec_is_applicable_to_statement_line(self) and not self.partner_id:
                self.with_context(
                    skip_account_move_synchronization=True,
                ).partner_id = model.mapped_partner_id
                break

        # 2) Partner auto-retrieve from bank account / name / history
        if not self.partner_id:
            partner = self._bank_rec_retrieve_partner()
            if partner:
                self.with_context(
                    skip_account_move_synchronization=True,
                ).partner_id = partner

        # 3) Auto write-off models
        auto_models = self.env['account.reconcile.model'].search([
            ('company_id', '=', self.company_id.id),
            ('trigger', '=', 'auto_reconcile'),
            ('line_ids.account_id', '!=', False),
        ], order='sequence, id')
        for model in auto_models:
            if model._bank_rec_is_applicable_to_statement_line(self):
                model._bank_rec_apply_to_statement_line(self)
                if self.is_reconciled:
                    return

        # 4) Payment-ref / move-name token match
        candidates = self._bank_rec_find_amls_by_payment_ref()
        if len(candidates) == 1:
            self._bank_rec_match_move_lines(candidates.ids)
            return

        # 5) Amount (+ tolerance) match, preferring partner filter
        candidates = self._bank_rec_find_amls_by_amount()
        if len(candidates) == 1:
            self._bank_rec_match_move_lines(candidates.ids)
            return

        # 6) Multi-line: partner residuals that sum exactly to statement amount
        if self.partner_id:
            group = self._bank_rec_find_amls_exact_sum()
            if group:
                self._bank_rec_match_move_lines(group.ids)

    def _bank_rec_retrieve_partner(self):
        """Suggest a partner from account number, partner_name, or past ST lines."""
        self.ensure_one()
        Partner = self.env['res.partner']
        Bank = self.env['res.partner.bank']

        if self.account_number:
            banks = Bank.search([
                ('acc_number', '=', self.account_number),
                '|', ('company_id', '=', False), ('company_id', '=', self.company_id.id),
            ], limit=5)
            partners = banks.mapped('partner_id').filtered('active')
            if len(partners) == 1:
                return partners

        name = (self.partner_name or '').strip()
        if name:
            partners = Partner.search([
                ('name', '=ilike', name),
                '|', ('company_id', '=', False), ('company_id', '=', self.company_id.id),
            ], limit=5)
            if len(partners) == 1:
                return partners
            partners = Partner.search([
                ('name', 'ilike', name),
                '|', ('company_id', '=', False), ('company_id', '=', self.company_id.id),
            ], limit=5)
            if len(partners) == 1:
                return partners

        # History: previous reconciled lines with same payment_ref substring
        ref = (self.payment_ref or '').strip()
        if len(ref) >= 4:
            prev = self.search([
                ('journal_id', '=', self.journal_id.id),
                ('partner_id', '!=', False),
                ('is_reconciled', '=', True),
                ('payment_ref', 'ilike', ref[:20]),
                ('id', '!=', self.id),
            ], limit=5, order='date desc, id desc')
            partners = prev.mapped('partner_id')
            if len(partners) == 1:
                return partners
        return Partner

    def _bank_rec_tokenize_ref(self, text):
        if not text:
            return []
        # Keep tokens that look like invoice/payment numbers
        tokens = re.findall(r'[A-Za-z0-9][A-Za-z0-9\-_/]{2,}', text)
        stop = {'the', 'and', 'for', 'payment', 'transfer', 'bank', 'from', 'to'}
        return [t for t in tokens if t.lower() not in stop]

    def _bank_rec_find_amls_by_payment_ref(self):
        self.ensure_one()
        tokens = self._bank_rec_tokenize_ref(self.payment_ref)
        if not tokens:
            return self.env['account.move.line']
        domain = self._get_default_amls_matching_domain()
        if self.partner_id:
            domain = domain + [('partner_id', '=', self.partner_id.id)]
        amls = self.env['account.move.line']
        for token in tokens[:8]:
            hits = self.env['account.move.line'].search(
                domain + [
                    '|', '|',
                    ('name', 'ilike', token),
                    ('ref', 'ilike', token),
                    ('move_id.name', 'ilike', token),
                ],
                limit=10,
            )
            amls |= hits
        # Prefer residual close to statement amount
        return self._bank_rec_filter_amls_by_tolerance(amls)

    def _bank_rec_find_amls_by_amount(self):
        self.ensure_one()
        domain = self._get_default_amls_matching_domain()
        if self.partner_id:
            domain = domain + [('partner_id', '=', self.partner_id.id)]
        amls = self.env['account.move.line'].search(domain, limit=40)
        return self._bank_rec_filter_amls_by_tolerance(amls)

    def _bank_rec_filter_amls_by_tolerance(self, amls):
        self.ensure_one()
        company_currency = self.company_currency_id
        target = abs(self.amount)
        tolerance = self._bank_rec_get_payment_tolerance()
        threshold = (tolerance or 0.0) * target if tolerance else 0.0

        def matches(aml):
            # Compare company residual; also try amount_residual_currency vs st amount
            diff_company = abs(abs(aml.amount_residual) - target)
            if threshold:
                ok_company = company_currency.compare_amounts(diff_company, threshold) <= 0
            else:
                ok_company = company_currency.is_zero(diff_company)
            if ok_company:
                return True
            if aml.currency_id == (self.foreign_currency_id or self.currency_id):
                diff_curr = abs(abs(aml.amount_residual_currency) - abs(
                    self.amount_currency if self.foreign_currency_id else self.amount
                ))
                curr = aml.currency_id
                thr = (tolerance or 0.0) * abs(self.amount_currency or self.amount) if tolerance else 0.0
                return curr.compare_amounts(diff_curr, thr) <= 0 if thr else curr.is_zero(diff_curr)
            return False

        return amls.filtered(matches)

    def _bank_rec_find_amls_exact_sum(self):
        """If a small set of partner AMLs sum (residual) to statement amount, return them."""
        self.ensure_one()
        if not self.partner_id:
            return self.env['account.move.line']
        domain = self._get_default_amls_matching_domain() + [
            ('partner_id', '=', self.partner_id.id),
        ]
        amls = self.env['account.move.line'].search(domain, limit=15, order='date, id')
        if not amls:
            return amls
        company_currency = self.company_currency_id
        # Bank inbound (+) clears positive receivable residual (customer owes us).
        # Counterpart balances are -residual; sum(residual) should equal statement amount
        # for inbound when matching AR: sum(residuals) ≈ amount
        target = self.amount
        total = sum(amls.mapped('amount_residual'))
        # For inbound payment, residuals on AR are positive; statement amount positive.
        # Matching uses -residual on bank move, so open starts at +amount and adds -residual.
        # Success when sum(residuals) ≈ amount for inbound.
        if company_currency.is_zero(total - target):
            return amls
        # Try subsets of size 2..4 for small exact sums
        records = list(amls)
        n = len(records)
        if n > 8:
            return self.env['account.move.line']
        for size in (2, 3, 4):
            for combo in combinations(records, size):
                s = sum(l.amount_residual for l in combo)
                if company_currency.is_zero(s - target):
                    return self.env['account.move.line'].browse([l.id for l in combo])
        return self.env['account.move.line']

    def action_retrieve_partner(self):
        """Button: try to set partner from bank metadata."""
        for line in self:
            if line.partner_id or line.is_reconciled:
                continue
            partner = line._bank_rec_retrieve_partner()
            if partner:
                line.with_context(
                    skip_account_move_synchronization=True,
                ).partner_id = partner
        return True

    @api.model
    def bank_rec_search_move_lines(self, statement_line_id, search_term='', limit=40):
        """OWL search dialog: return matchable AML candidates for a statement line."""
        st_line = self.browse(statement_line_id).exists()
        if not st_line:
            return []
        domain = st_line._get_default_amls_matching_domain()
        if st_line.partner_id:
            domain = domain + [('partner_id', '=', st_line.partner_id.id)]
        if search_term:
            domain = domain + [
                '|', '|', '|', '|',
                ('name', 'ilike', search_term),
                ('ref', 'ilike', search_term),
                ('move_id.name', 'ilike', search_term),
                ('partner_id.name', 'ilike', search_term),
                ('amount_residual', 'ilike', search_term),
            ]
        amls = self.env['account.move.line'].search(domain, limit=limit, order='date desc, id desc')
        return [{
            'id': aml.id,
            'date': fields.Date.to_string(aml.date) if aml.date else False,
            'move_name': aml.move_id.display_name,
            'name': aml.name or '',
            'partner': aml.partner_id.display_name or '',
            'account': aml.account_id.display_name,
            'amount_residual': aml.amount_residual,
            'amount_residual_currency': aml.amount_residual_currency,
            'currency': aml.currency_id.symbol or aml.currency_id.name,
        } for aml in amls]

    def bank_rec_get_statement_summary(self):
        """OWL summary strip for the open statement line / journal."""
        self.ensure_one()
        journal = self.journal_id
        unmatched = self.search_count([
            ('journal_id', '=', journal.id),
            ('is_reconciled', '=', False),
            ('state', '!=', 'cancel'),
        ])
        to_check = self.search_count([
            ('journal_id', '=', journal.id),
            ('to_check', '=', True),
            ('state', '!=', 'cancel'),
        ])
        return {
            'journal': journal.display_name,
            'statement': self.statement_id.display_name if self.statement_id else False,
            'date': fields.Date.to_string(self.date) if self.date else False,
            'amount': self.amount,
            'currency': self.currency_id.symbol or self.currency_id.name,
            'unmatched_count': unmatched,
            'to_check_count': to_check,
            'is_reconciled': self.is_reconciled,
            'partner': self.partner_id.display_name or self.partner_name or '',
            'payment_ref': self.payment_ref or '',
        }
